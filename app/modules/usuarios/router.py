"""Rutas de autenticación: registro, login, logout (C-07), perfil y cambio de contraseña (C-08).

Todas viven en el grupo abierto (RN06): `/auth/yo` y `/auth/cambiar-password` piden la sesión por
ruta (`UsuarioActualDep`) y responden aunque haya un cambio de contraseña pendiente.
"""

from fastapi import APIRouter, Request, Response

from app.core.dependencies import UsuarioActualDep
from app.core.security import aplicar_cookie_acceso, eliminar_cookie_acceso
from app.modules.usuarios import service
from app.modules.usuarios.schemas import (
    CambioPasswordEntrada,
    LoginEntrada,
    LoginSalida,
    MensajeSalida,
    PerfilSalida,
    RegistroEntrada,
    RegistroSalida,
)
from app.modules.usuarios.unit_of_work import AnotadorIntentosDep, UsuariosUoWDep

router = APIRouter(prefix="/auth", tags=["auth"])

MENSAJE_SESION_CERRADA = "Sesión cerrada"
IP_DESCONOCIDA = "desconocida"


@router.post("/registro", status_code=201)
async def registro(datos: RegistroEntrada, uow: UsuariosUoWDep) -> RegistroSalida:
    return await service.registrar(uow, datos)


@router.post("/login")
async def login(
    datos: LoginEntrada,
    request: Request,
    response: Response,
    uow: UsuariosUoWDep,
    anotador: AnotadorIntentosDep,
) -> LoginSalida:
    # No se lee `X-Forwarded-For`: lo controla el cliente y permitiría evadir el límite.
    ip = request.client.host if request.client else IP_DESCONOCIDA
    sesion = await service.iniciar_sesion(
        uow, anotador, datos, ip, request.app.state.hash_ficticio
    )
    aplicar_cookie_acceso(response, sesion.token)
    return sesion.salida


@router.post("/logout")
async def logout(response: Response) -> MensajeSalida:
    eliminar_cookie_acceso(response)
    return MensajeSalida(mensaje=MENSAJE_SESION_CERRADA)


@router.get("/yo")
async def yo(actual: UsuarioActualDep, uow: UsuariosUoWDep) -> PerfilSalida:
    return await service.perfil(uow, actual)


@router.post("/cambiar-password")
async def cambiar_password(
    datos: CambioPasswordEntrada,
    actual: UsuarioActualDep,
    uow: UsuariosUoWDep,
    response: Response,
) -> LoginSalida:
    sesion = await service.cambiar_password(uow, actual, datos)
    aplicar_cookie_acceso(response, sesion.token)
    return sesion.salida
