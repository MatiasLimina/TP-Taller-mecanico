"""Unit of Work del módulo repuestos (C-11).

Sigue el patrón de `app/core/unit_of_work.py`: el router lo CONSTRUYE por inyección
(`RepuestosUoWDep`) y lo entrega sin abrir; el servicio lo ABRE con `async with` y nunca lo
construye ni lo anida. Los tres repositorios comparten la MISMA sesión de la petición.

`RepuestosUoW` cumple el protocolo `ConStock` del punto único de escritura de stock
(`app/modules/repuestos/service.py`: expone `repuestos` y `movimientos`), igual que lo cumplirá
el UoW de órdenes en C-13/C-14.
"""

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import SessionDep
from app.core.unit_of_work import UnitOfWork
from app.modules.repuestos.repository import (
    HistorialPrecioRepository,
    MovimientoStockRepository,
    RepuestoRepository,
)


class RepuestosUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repuestos = RepuestoRepository(session)
        self.movimientos = MovimientoStockRepository(session)
        self.historial_precios = HistorialPrecioRepository(session)


def get_repuestos_uow(session: SessionDep) -> RepuestosUoW:
    return RepuestosUoW(session)


RepuestosUoWDep = Annotated[RepuestosUoW, Depends(get_repuestos_uow)]
