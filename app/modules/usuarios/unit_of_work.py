"""Unit of Work del módulo usuarios y anotador de intentos de acceso (C-07).

`UsuariosUoW` agrupa los repositorios que usan registro, login, personal y roles con la MISMA
sesión de la petición. La ficha de cliente se escribe con `BaseRepository` (alcanza con
`add()`), así no se adelanta `app/modules/clientes/repository.py` (C-10); los eventos de
seguridad tienen su repositorio (C-09) porque además se listan.
"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.database import SessionDep
from app.core.repository import BaseRepository
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.models import Cliente
from app.modules.usuarios.models import IntentoAcceso
from app.modules.usuarios.repository import (
    AsignacionRolRepository,
    EventoSeguridadRepository,
    IntentoAccesoRepository,
    UsuarioRepository,
)


class UsuariosUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.usuarios = UsuarioRepository(session)
        self.asignaciones = AsignacionRolRepository(session)
        self.intentos = IntentoAccesoRepository(session)  # sólo lectura del conteo
        self.clientes = BaseRepository(session, Cliente)
        self.eventos = EventoSeguridadRepository(session)


def get_usuarios_uow(session: SessionDep) -> UsuariosUoW:
    return UsuariosUoW(session)


UsuariosUoWDep = Annotated[UsuariosUoW, Depends(get_usuarios_uow)]


class AnotadorIntentos:
    """Anota los intentos de login fuera de la transacción de la petición.

    EXCEPCIÓN DECLARADA (RN08, DD-07): sesión y transacción propias, confirmadas siempre,
    porque el fallo que se cuenta es el mismo que revierte la petición (el 401 se lanza
    después de anotar). Costo: una conexión extra del pool por intento y filas que persisten
    aunque la petición falle. La confirmación la hace el `UnitOfWork` base (sigue siendo el
    único lugar de `app/` que confirma); esta clase sólo crea y cierra su sesión.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def anotar(self, email: str, ip: str, exito: bool) -> None:
        async with self._session_factory() as session, UnitOfWork(session):
            await IntentoAccesoRepository(session).add(
                IntentoAcceso(email=email, ip=ip, exito=exito)
            )


def get_anotador_intentos(request: Request) -> AnotadorIntentos:
    return AnotadorIntentos(request.app.state.session_factory)


AnotadorIntentosDep = Annotated[AnotadorIntentos, Depends(get_anotador_intentos)]
