"""Rutas de autenticación: registro, login y logout (C-07). Todas abiertas (RN06)."""

from fastapi import APIRouter, Request, Response

from app.core.security import aplicar_cookie_acceso, eliminar_cookie_acceso
from app.modules.usuarios import service
from app.modules.usuarios.schemas import (
    LoginEntrada,
    LoginSalida,
    MensajeSalida,
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
