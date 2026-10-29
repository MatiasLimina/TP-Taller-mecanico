"""Repositorios del módulo repuestos (C-11). Reglas generales: ver `app/core/repository.py`.

Todo con parámetros ligados (la búsqueda es un valor ligado con `%`, `_` y `\\` escapados, nunca
SQL armado con datos del usuario); las escrituras hacen `flush()` o ejecutan una sentencia y
NUNCA confirman la transacción. Las lecturas devuelven entidades sin relaciones o columnas
sueltas: no hay carga perezosa posible.

`movimiento_stock` e `historial_precio_repuesto` son de sólo agregado (C-04): sus repositorios
solo exponen `add()`; C-12 les agrega el listado.
"""

from datetime import datetime
from typing import NamedTuple

from sqlalchemy import or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

from app.core.repository import BaseRepository, SoftDeleteRepository
from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)

CARACTER_ESCAPE_LIKE = "\\"


class FilaStock(NamedTuple):
    """Lo que el punto único necesita saber de un repuesto cuando no puede aplicar un pedido."""

    codigo: str
    stock: int
    borrado_en: datetime | None


def _escapar_like(texto: str) -> str:
    """Escapa `\\`, `%` y `_` para que `ILIKE` los trate como caracteres literales."""
    return (
        texto.replace(CARACTER_ESCAPE_LIKE, CARACTER_ESCAPE_LIKE * 2)
        .replace("%", CARACTER_ESCAPE_LIKE + "%")
        .replace("_", CARACTER_ESCAPE_LIKE + "_")
    )


class RepuestoRepository(SoftDeleteRepository[Repuesto]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Repuesto)

    def _filtrada(self, q: str | None) -> SelectOfScalar[Repuesto]:
        """Repuestos vigentes cuya descripción o código contiene `q` (sin distinguir mayúsculas)."""
        consulta = self._consulta_base()
        if q:
            patron = f"%{_escapar_like(q)}%"  # valor ligado, nunca SQL
            consulta = consulta.where(
                or_(
                    col(Repuesto.descripcion).ilike(patron, escape=CARACTER_ESCAPE_LIKE),
                    col(Repuesto.codigo).ilike(patron, escape=CARACTER_ESCAPE_LIKE),
                )
            )
        return consulta

    async def contar(self, q: str | None) -> int:
        return await self._contar(self._filtrada(q))

    async def listar(self, q: str | None, *, offset: int, limit: int) -> list[Repuesto]:
        """Página de repuestos vigentes en orden de id (estable para paginar)."""
        consulta = self._filtrada(q).order_by(col(Repuesto.id)).offset(offset).limit(limit)
        return list((await self.session.exec(consulta)).all())

    async def get_vigente_para_actualizar(self, id: int) -> Repuesto | None:
        """Repuesto vigente bloqueado con `FOR UPDATE` (edición y baja, C-11).

        El bloqueo serializa escrituras sobre la misma fila; al seguir, PostgreSQL reevalúa el
        `WHERE` y no devuelve un repuesto que la otra transacción ya dio de baja.
        `populate_existing` refresca una instancia que el identity map ya tuviera cargada.
        """
        consulta = (
            self._consulta_base()
            .where(col(Repuesto.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(consulta)).first()

    async def sumar_stock(
        self, repuesto_id: int, delta: int, *, incluir_bajas: bool = False
    ) -> int | None:
        """ÚNICA escritura de `repuesto.stock` en `app/` (RN14): la llama sólo el punto único.

        UPDATE repuesto SET stock = stock + :delta
         WHERE id = :id [AND borrado_en IS NULL] AND stock + :delta >= 0
        RETURNING stock

        Devuelve el stock resultante, o `None` si ninguna fila cumple (no existe, está dada de
        baja sin `incluir_bajas`, o no alcanza el stock): el llamador distingue el caso con
        `leer_stock`. La sentencia toma el bloqueo de la fila y, si otra transacción la cambió,
        PostgreSQL reevalúa la condición sobre la versión confirmada: no hay actualización
        perdida ni stock negativo, sin `SELECT … FOR UPDATE` previo.

        ADVERTENCIA: `synchronize_session=False`. Una entidad `Repuesto` ya cargada en la sesión
        queda con el stock VIEJO; usar el valor devuelto o releer con `populate_existing`.
        """
        condiciones = [
            col(Repuesto.id) == repuesto_id,
            col(Repuesto.stock) + delta >= 0,
        ]
        if not incluir_bajas:
            condiciones.append(col(Repuesto.borrado_en).is_(None))
        sentencia = (
            update(Repuesto)
            .where(*condiciones)
            .values(stock=col(Repuesto.stock) + delta)
            .returning(col(Repuesto.stock))
            .execution_options(synchronize_session=False)
        )
        return (await self.session.exec(sentencia)).scalar_one_or_none()

    async def leer_stock(self, repuesto_id: int) -> FilaStock | None:
        """`codigo`, `stock` y `borrado_en` de un repuesto, también si está dado de baja.

        Columnas y no entidad: no pasa por el identity map (stock actual, no uno cacheado) ni
        por el filtro de bajas.
        """
        consulta = select(
            col(Repuesto.codigo), col(Repuesto.stock), col(Repuesto.borrado_en)
        ).where(col(Repuesto.id) == repuesto_id)
        fila = (await self.session.exec(consulta)).first()
        return None if fila is None else FilaStock(*fila)


class MovimientoStockRepository(BaseRepository[MovimientoStock]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MovimientoStock)


class HistorialPrecioRepository(BaseRepository[HistorialPrecioRepuesto]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, HistorialPrecioRepuesto)
