"""Unit of Work del módulo clientes (C-10).

Sigue el patrón de `app/core/unit_of_work.py`: el router lo CONSTRUYE por inyección
(`ClientesUoWDep`) y lo entrega sin abrir; el servicio lo ABRE con `async with` y nunca lo
construye ni lo anida. Los dos repositorios comparten la MISMA sesión de la petición.
"""

from typing import Annotated

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import SessionDep
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.repository import ClienteRepository, VehiculoRepository


class ClientesUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.clientes = ClienteRepository(session)
        self.vehiculos = VehiculoRepository(session)


def get_clientes_uow(session: SessionDep) -> ClientesUoW:
    return ClientesUoW(session)


ClientesUoWDep = Annotated[ClientesUoW, Depends(get_clientes_uow)]
