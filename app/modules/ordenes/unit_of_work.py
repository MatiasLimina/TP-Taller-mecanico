"""Unit of Work del módulo órdenes (C-13).

Sigue el patrón de `app/core/unit_of_work.py`: el router lo CONSTRUYE por inyección
(`OrdenesUoWDep`) y lo entrega sin abrir; el servicio lo ABRE con `async with` y nunca lo
construye ni lo anida. Todos los repositorios comparten la MISMA sesión de la petición.

Compone los repositorios de órdenes con los de otros módulos que una operación de órdenes
necesita dentro de la MISMA transacción: el `VehiculoRepository` de clientes (bloqueo del
vehículo, C-10) y el `RepuestoRepository` y el `MovimientoStockRepository` de repuestos (lectura
`FOR SHARE` de los repuestos pedidos, y los dos que el punto único de escritura de stock necesita) y
el `AsignacionRolRepository` de usuarios (roles vigentes del actor para el permiso de terminar y
cancelar, RN04, C-14 S-03). No reutiliza ni abre `ClientesUoW` ni `RepuestosUoW` (tampoco el de
usuarios): nunca hay dos Unit of Work abiertos.

Cumple el protocolo `ConStock` (`repuestos` y `movimientos`) de `app/modules/repuestos/service.py`:
C-14 llama `aplicar_movimientos_stock(uow, …)` dentro del bloque que abre su servicio. C-13 no lo
usa: el alta nunca escribe `stock` (RN14).
"""

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import SessionDep
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.repository import VehiculoRepository
from app.modules.ordenes.repository import (
    EstadoOrdenRepository,
    HistorialEstadoOrdenRepository,
    ItemOrdenRepository,
    OrdenTrabajoRepository,
)
from app.modules.repuestos.repository import (
    MovimientoStockRepository,
    RepuestoRepository,
)
from app.modules.usuarios.repository import AsignacionRolRepository


class OrdenesUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.estados = EstadoOrdenRepository(session)
        self.ordenes = OrdenTrabajoRepository(session)
        self.items = ItemOrdenRepository(session)
        self.historial = HistorialEstadoOrdenRepository(session)
        self.vehiculos = VehiculoRepository(session)  # de clientes (C-10): bloqueo del vehículo
        self.repuestos = RepuestoRepository(session)  # de repuestos (C-11): lectura FOR SHARE
        # Sin uso en C-13: completa `ConStock` para C-14.
        self.movimientos = MovimientoStockRepository(session)
        # De usuarios: roles vigentes del actor leídos en la misma transacción (RN04, C-14 S-03).
        self.asignaciones = AsignacionRolRepository(session)


def get_ordenes_uow(session: SessionDep) -> OrdenesUoW:
    return OrdenesUoW(session)


OrdenesUoWDep = Annotated[OrdenesUoW, Depends(get_ordenes_uow)]
