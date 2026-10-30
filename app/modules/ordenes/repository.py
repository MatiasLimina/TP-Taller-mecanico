"""Repositorios del módulo órdenes (C-13). Reglas generales: ver `app/core/repository.py`.

Todo con parámetros ligados y sin `commit()` (las escrituras hacen `flush()`); la precarga de las
relaciones que una lectura devuelve se declara en el método que la hace (`lazy="raise"` en los
modelos: leer una relación sin precargar lanza en lugar de consultar).

Orden de bloqueo de filas (design C-13 D6), que respetan los servicios de órdenes (C-13, C-14) y
los de clientes y repuestos que ya lo cumplen: 1) una orden existente (`FOR UPDATE`, C-14);
2) el vehículo (`FOR UPDATE`, C-10 baja y C-13 alta); 3) los repuestos en orden ascendente de id
(`FOR SHARE` en el alta, `FOR UPDATE` en PATCH/DELETE y `UPDATE` condicional en el punto único de
stock). Nunca se vuelve atrás: sin ciclos de espera, sin interbloqueos. C-14: `get_para_actualizar`
es el paso 1 y la primera sentencia con bloqueo de iniciar, terminar y cancelar; ninguna transición
bloquea un vehículo ni lee un repuesto con bloqueo antes de la orden.

`historial_estado_orden` es de sólo agregado (RN15, C-04): su repositorio solo se usa con `add()`;
nunca `update` ni `delete`. El catálogo `estado_orden` es de sólo lectura (RN19): lo carga el seed
(C-06) y la API no lo escribe.
"""

from collections.abc import Sequence

from sqlalchemy.orm import joinedload, selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.repository import BaseRepository
from app.modules.clientes.models import Cliente, Vehiculo
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

    async def get_para_actualizar(self, id: int) -> OrdenTrabajo | None:
        """Orden bloqueada con `FOR UPDATE`, sin relaciones (C-14).

        Es el paso 1 del orden global de bloqueo y la PRIMERA fila que toma toda transición:
        serializa dos transiciones sobre la misma orden (la segunda espera sin tener nada
        bloqueado y, al seguir, ve el estado confirmado). `populate_existing` hace que la fila
        bloqueada pise cualquier valor viejo del identity map.
        """
        consulta = (
            self._consulta_base()
            .where(col(OrdenTrabajo.id) == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(consulta)).first()

    async def get_usuario_dueno(self, orden_id: int) -> int | None:
        """`cliente.usuario_id` del vehículo de la orden, o None si la ficha no tiene usuario.

        Cuenta también si el vehículo está dado de baja (RN16). Devuelve None además cuando la
        orden no existe. Columna suelta, sin bloqueo y sin entidades en el identity map.
        """
        consulta = (
            select(col(Cliente.usuario_id))
            .join(Vehiculo, col(Vehiculo.cliente_id) == col(Cliente.id))
            .join(OrdenTrabajo, col(OrdenTrabajo.vehiculo_id) == col(Vehiculo.id))
            .where(col(OrdenTrabajo.id) == orden_id)
        )
        return (await self.session.exec(consulta)).first()


class ItemOrdenRepository(BaseRepository[ItemOrden]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ItemOrden)

    async def add_varios(self, items: Sequence[ItemOrden]) -> list[ItemOrden]:
        """Agrega todos los ítems con UN `flush()`: SQLAlchemy 2.0 (`insertmanyvalues`) emite un solo
        `INSERT … VALUES (…), (…) RETURNING id`, con los ids en el orden de la lista."""
        self.session.add_all(items)
        await self.session.flush()
        return list(items)

    async def listar_de_orden(self, orden_id: int) -> list[ItemOrden]:
        """Ítems de la orden en orden de id, sin relaciones (usa `uq_item_orden_orden_id_repuesto_id`).

        Una sola consulta para cualquier cantidad de ítems. No los bloquea: no hay ruta que los
        edite y la orden padre ya está bloqueada.
        """
        consulta = (
            self._consulta_base()
            .where(col(ItemOrden.orden_id) == orden_id)
            .order_by(col(ItemOrden.id))
        )
        return list((await self.session.exec(consulta)).all())


class HistorialEstadoOrdenRepository(BaseRepository[HistorialEstadoOrden]):
    """De sólo agregado (RN15): se usa únicamente `add()`; nunca `update` ni `delete`."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, HistorialEstadoOrden)
