"""Repositorios genéricos: acceso a datos por entidad sobre una sesión recibida.

Reglas que heredan todos los repositorios de módulo (clientes, repuestos, órdenes…):

- Reciben la sesión y la clase del modelo en el constructor (los genéricos se borran en
  tiempo de ejecución, por eso `BaseRepository` no puede inferir `T`).
- `add`, `update` y `delete` hacen `flush()` y NUNCA confirman la transacción: las restricciones se
  evalúan en esa llamada y los ids quedan disponibles, pero confirmar o revertir es del
  Unit of Work (`app/core/unit_of_work.py`).
- Los valores del usuario viajan siempre como parámetros ligados (sin SQL armado a mano)
  y las relaciones que una lectura devuelve se precargan EN el método que la hace
  (`selectinload`/`joinedload`), nunca por carga perezosa posterior: en asyncio una carga
  perezosa lanza `MissingGreenlet`.
- Tras un `add`, si hace falta una relación, releer con el método del repositorio que la
  precarga en lugar de acceder al atributo.
- Los métodos nuevos parten de `self._consulta_base()` y cuentan con `self._contar(...)`,
  así el `total` usa los mismos filtros que la página y las bajas lógicas quedan excluidas.

Ejemplo de repositorio de módulo::

    class ClienteRepository(BaseRepository[Cliente]):
        def __init__(self, session: AsyncSession) -> None:
            super().__init__(session, Cliente)

        async def get_by_documento(self, documento: str) -> Cliente | None:
            consulta = self._consulta_base().where(Cliente.documento == documento)
            return (await self.session.exec(consulta)).first()

        async def get_detalle_by_id(self, id: int) -> Cliente | None:
            consulta = (
                self._consulta_base()
                .where(Cliente.id == id)
                .options(selectinload(Cliente.vehiculos))  # precarga declarada acá
            )
            return (await self.session.exec(consulta)).first()
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar


class BaseRepository[T: SQLModel]:
    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self.session = session
        self.model = model

    # -- consultas -----------------------------------------------------------------

    def _consulta_base(self) -> SelectOfScalar[T]:
        """Punto de partida de toda lectura; las subclases agregan filtros fijos acá."""
        return select(self.model)

    async def _contar(self, consulta: SelectOfScalar[T]) -> int:
        """`SELECT count(*) FROM (<consulta>)`: sin orden, desplazamiento ni límite."""
        sin_orden = consulta.order_by(None).offset(None).limit(None)
        total = select(func.count()).select_from(sin_orden.subquery())
        return (await self.session.exec(total)).one()

    async def get_by_id(self, id: int) -> T | None:
        # `select`, no `session.get()`: `get()` responde desde el identity map sin pasar
        # por los filtros de `_consulta_base()` (bajas lógicas).
        consulta = self._consulta_base().where(col(self.model.id) == id)  # type: ignore[attr-defined]
        return (await self.session.exec(consulta)).first()

    async def get_all(self, *, offset: int = 0, limit: int | None = None) -> list[T]:
        consulta = self._consulta_base().order_by(col(self.model.id))  # type: ignore[attr-defined]
        consulta = consulta.offset(offset)
        if limit is not None:
            consulta = consulta.limit(limit)
        return list((await self.session.exec(consulta)).all())

    async def count(self) -> int:
        return await self._contar(self._consulta_base())

    # -- escrituras (flush, nunca commit) -----------------------------------------

    async def add(self, entidad: T) -> T:
        # Sin refresh(): el INSERT trae PK y defaults de servidor con RETURNING. Regla
        # para los modelos: sin `server_onupdate`; si hiciera falta, `session.refresh()`
        # dentro del método del repositorio.
        self.session.add(entidad)
        await self.session.flush()
        return entidad

    async def update(self, entidad: T, datos: Mapping[str, Any]) -> T:
        """Actualización parcial: sólo se tocan las claves de `datos`.

        `datos` suele ser `dto.model_dump(exclude_unset=True)`. Una clave que no es campo
        del modelo, o `id`, es un error de programación: `ValueError` antes de escribir.
        """
        campos = self.model.model_fields
        invalidas = [clave for clave in datos if clave == "id" or clave not in campos]
        if invalidas:
            raise ValueError(f"Campos no actualizables en {self.model.__name__}: {invalidas}")
        for clave, valor in datos.items():
            setattr(entidad, clave, valor)
        await self.session.flush()
        return entidad

    async def delete(self, entidad: T) -> None:
        # flush() para que una FK que impida el borrado falle acá y no al confirmar.
        await self.session.delete(entidad)
        await self.session.flush()


class SoftDeleteRepository[T: SQLModel](BaseRepository[T]):
    """Repositorio de entidades con borrado lógico (columna `borrado_en`, timestamptz).

    `_consulta_base()` excluye las bajas, así que `get_by_id`, `get_all`, `count` y todo
    método de subclase que parta de ella las ocultan sin repetir el filtro. Las reglas de
    negocio previas a la baja (p. ej. RN16) las decide el servicio antes de llamar.
    """

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        if "borrado_en" not in model.model_fields:
            raise TypeError(f"{model.__name__} no tiene la columna 'borrado_en'")
        super().__init__(session, model)

    def _consulta_base(self) -> SelectOfScalar[T]:
        return super()._consulta_base().where(col(self.model.borrado_en).is_(None))  # type: ignore[attr-defined]

    async def get_by_id_including_deleted(self, id: int) -> T | None:
        consulta = select(self.model).where(col(self.model.id) == id)  # type: ignore[attr-defined]
        return (await self.session.exec(consulta)).first()

    async def soft_delete(self, entidad: T) -> T:
        # Valor Python con zona (no func.now()): una expresión SQL dejaría el atributo
        # expirado y leerlo después sería una carga perezosa.
        if entidad.borrado_en is None:  # type: ignore[attr-defined]
            entidad.borrado_en = datetime.now(UTC)  # type: ignore[attr-defined]
            await self.session.flush()
        return entidad
