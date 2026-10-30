"""Repositorios del módulo órdenes (C-13). Reglas generales: ver `app/core/repository.py`.

Todo con parámetros ligados y sin `commit()` (las escrituras hacen `flush()`); la precarga de las
relaciones que una lectura devuelve se declara en el método que la hace (`lazy="raise"` en los
modelos: leer una relación sin precargar lanza en lugar de consultar).

Orden de bloqueo de filas (design C-13 D6), que respetan los servicios de órdenes (C-13, C-14) y
los de clientes y repuestos que ya lo cumplen: 1) una orden existente (`FOR UPDATE`, C-14);
2) el vehículo (`FOR UPDATE`, C-10 baja y C-13 alta); 3) los repuestos en orden ascendente de id
(`FOR SHARE` en el alta, `FOR UPDATE` en PATCH/DELETE y `UPDATE` condicional en el punto único de
stock). Nunca se vuelve atrás: sin ciclos de espera, sin interbloqueos.

`historial_estado_orden` es de sólo agregado (RN15, C-04): su repositorio solo se usa con `add()`;
nunca `update` ni `delete`. El catálogo `estado_orden` es de sólo lectura (RN19): lo carga el seed
(C-06) y la API no lo escribe.
"""

from collections.abc import Sequence

from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.repository import BaseRepository
from app.modules.clientes.models import Vehiculo
from app.modules.ordenes.models import (
    EstadoOrden,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)


class EstadoOrdenRepository:
    """Catálogo de estados de sólo lectura: sin `BaseRepository` (la PK es `codigo` y no expone
    `add`, `update` ni `delete`)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def listar(self) -> list[EstadoOrden]:
        """Todo el catálogo en orden de `posicion` (indexada por `uq_estado_orden_posicion`)."""
        consulta = select(EstadoOrden).order_by(col(EstadoOrden.posicion))
        return list((await self.session.exec(consulta)).all())

    async def get_por_codigo(self, codigo: str) -> EstadoOrden | None:
        # `select`, no `session.get()`: una consulta por PK que siempre llega a la base.
        consulta = select(EstadoOrden).where(col(EstadoOrden.codigo) == codigo)
        return (await self.session.exec(consulta)).first()


class OrdenTrabajoRepository(BaseRepository[OrdenTrabajo]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OrdenTrabajo)

    async def get_detalle(self, id: int) -> OrdenTrabajo | None:
        """Orden con todo lo que muestra el detalle: 3 SELECT fijos para cualquier cantidad de ítems.

        1) la orden con su vehículo y el cliente del vehículo (dos JOIN), 2) los ítems con su
        repuesto (en orden de id), 3) el historial (en orden de id). El vehículo y el repuesto se
        cargan aunque estén dados de baja: conservan sus datos (RN16). La reutiliza C-15 en
        `GET /ordenes/{id}`.

        `populate_existing` es obligatorio: tras el alta, la orden, sus ítems y su historial ya están
        en el identity map con las relaciones sin cargar; sin él, una colección ya presente podría
        no refrescarse.
        """
        consulta = (
            self._consulta_base()
            .where(col(OrdenTrabajo.id) == id)
            .options(
                joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente),
                selectinload(OrdenTrabajo.items).joinedload(ItemOrden.repuesto),
                selectinload(OrdenTrabajo.historial),
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(consulta)).unique().first()


class ItemOrdenRepository(BaseRepository[ItemOrden]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ItemOrden)

    async def add_varios(self, items: Sequence[ItemOrden]) -> list[ItemOrden]:
        """Agrega todos los ítems con UN `flush()`: SQLAlchemy 2.0 (`insertmanyvalues`) emite un solo
        `INSERT … VALUES (…), (…) RETURNING id`, con los ids en el orden de la lista."""
        self.session.add_all(items)
        await self.session.flush()
        return list(items)


class HistorialEstadoOrdenRepository(BaseRepository[HistorialEstadoOrden]):
    """De sólo agregado (RN15): se usa únicamente `add()`; nunca `update` ni `delete`."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, HistorialEstadoOrden)
