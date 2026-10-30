"""Repositorios del módulo clientes (C-10). Reglas generales: ver `app/core/repository.py`.

Todo con parámetros ligados y sin `commit()`. La precarga de relaciones se declara en el
método que la usa. La consulta de órdenes abiertas vive acá (S-01) porque responde una
pregunta del vehículo ("¿se puede dar de baja?") y sólo necesita los modelos de `ordenes`; la
baja bloquea la fila del vehículo (S-02) para serializarse con el alta de órdenes de C-13.
"""

from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.repository import BaseRepository, SoftDeleteRepository
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import EstadoOrden, OrdenTrabajo


class ClienteRepository(BaseRepository[Cliente]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Cliente)

    async def get_con_vehiculos(self, id: int) -> Cliente | None:
        # Precarga declarada acá, con criterio: sólo vehículos vigentes (RN16). 2 SELECT fijos.
        consulta = (
            self._consulta_base()
            .where(col(Cliente.id) == id)
            .options(
                selectinload(
                    Cliente.vehiculos.and_(col(Vehiculo.borrado_en).is_(None))  # type: ignore[attr-defined]
                )
            )
        )
        return (await self.session.exec(consulta)).first()


class VehiculoRepository(SoftDeleteRepository[Vehiculo]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Vehiculo)

    async def listar_de_usuario(self, usuario_id: int) -> list[Vehiculo]:
        """Vehículos vigentes de la ficha vinculada al usuario (RN17): 1 SELECT, sin relaciones."""
        consulta = (
            self._consulta_base()
            .join(Cliente, col(Cliente.id) == col(Vehiculo.cliente_id))
            .where(col(Cliente.usuario_id) == usuario_id)
            .order_by(col(Vehiculo.id))
        )
        return list((await self.session.exec(consulta)).all())

    async def get_vigente_para_actualizar(self, id: int) -> Vehiculo | None:
        """Vehículo vigente con la fila bloqueada (`FOR UPDATE`, S-02)."""
        consulta = (
            self._consulta_base()
            .where(col(Vehiculo.id) == id)
            # FOR UPDATE simple, no `key_share` ni quitarlo (S-02): es el único modo que choca con el
            # FOR KEY SHARE que toma un INSERT en orden_trabajo por la FK; el UPDATE de la baja sólo
            # toma FOR NO KEY UPDATE y dejaría pasar una orden nueva sin esperar.
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(consulta)).first()

    async def tiene_ordenes_abiertas(self, vehiculo_id: int) -> bool:
        """RN16: hay alguna orden cuyo estado no es final según el catálogo `estado_orden`."""
        consulta = (
            select(col(OrdenTrabajo.id))
            .join(EstadoOrden, col(EstadoOrden.codigo) == col(OrdenTrabajo.estado))
            .where(
                col(OrdenTrabajo.vehiculo_id) == vehiculo_id,
                col(EstadoOrden.es_final).is_(False),
            )
            .limit(1)
        )
        return (await self.session.exec(consulta)).first() is not None
