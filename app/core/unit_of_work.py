"""Unit of Work: el límite transaccional de cada operación de negocio.

Todas las escrituras de un bloque `async with uow:` se confirman juntas al salir con
normalidad, o se revierten juntas si el bloque termina con una excepción (que se propaga
sin modificar). Este es el ÚNICO lugar de `app/` que confirma la transacción.

- Recibe una sesión ya creada y NUNCA la cierra: la crea y la cierra la dependencia de
  sesión por petición (`get_session`).
- No se puede abrir dos veces a la vez (`RuntimeError`): un bloque interno confirmaría a
  mitad de la operación del externo. Bloques sucesivos son transacciones independientes.
- No hay método público para confirmar: confirmar es salir del bloque.

Patrón por módulo (lo siguen clientes, repuestos, órdenes…)::

    class ClientesUoW(UnitOfWork):
        def __init__(self, session: AsyncSession) -> None:
            super().__init__(session)
            self.clientes = ClienteRepository(session)    # todos con la MISMA sesión
            self.vehiculos = VehiculoRepository(session)

    def get_clientes_uow(session: SessionDep) -> ClientesUoW:
        return ClientesUoW(session)

    ClientesUoWDep = Annotated[ClientesUoW, Depends(get_clientes_uow)]

    # router: lo CONSTRUYE (inyección) y lo entrega sin abrir
    @router.post("")
    async def alta(datos: ClienteAlta, uow: ClientesUoWDep) -> ClienteSalida:
        return await servicio.alta(uow, datos)

    # servicio: lo ABRE, nunca lo construye
    async def alta(uow: ClientesUoW, datos: ClienteAlta) -> ClienteSalida:
        async with uow:
            ...

Traducción de un error de integridad específico: fuera del bloque, nunca dentro::

    try:
        async with uow:
            ...
    except IntegrityError as exc:
        if restriccion_violada(exc) == "uq_usuario_email":
            raise Conflicto("El correo ya está registrado") from None
        raise

No leas atributos de entidades después de un bloque fallido: el rollback expira las
instancias y leer un atributo expirado dispara una carga perezosa (`MissingGreenlet`), que
terminaría en un 500 genérico en lugar del 409/422 que querías responder. Capturá antes de
salir del bloque los valores que la traducción necesite (ids, nombres) en variables locales.

Única escritura fuera de este Unit of Work (RN08): el registro de `intento_acceso` usa una
sesión y una transacción propias (`request.app.state.session_factory()`) que se confirman
siempre, para que el intento quede registrado aunque la petición falle. Quien la escriba
debe declarar esa excepción en un comentario junto con su costo (una conexión extra y
filas que persisten aunque la operación principal se revierta).
"""

import logging
from types import TracebackType
from typing import Self

from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._abierto = False

    async def __aenter__(self) -> Self:
        if self._abierto:
            raise RuntimeError(
                "El Unit of Work ya está abierto: un bloque interno confirmaría "
                "antes de tiempo el trabajo del externo"
            )
        self._abierto = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is None:
                try:
                    await self.session.commit()
                except BaseException:
                    await self._revertir()
                    raise
            else:
                await self._revertir()
        finally:
            self._abierto = False
        # Devuelve None: nunca suprime la excepción del bloque. La sesión no se cierra.

    async def _revertir(self) -> None:
        """Rollback que nunca reemplaza la excepción original: si falla, sólo se registra.

        Se captura `Exception` y no `BaseException`: una cancelación sí debe propagarse.
        """
        try:
            await self.session.rollback()
        except Exception:
            logger.exception(
                "El rollback del Unit of Work falló; se propaga la excepción original"
            )
