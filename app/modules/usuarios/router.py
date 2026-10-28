"""Rutas del módulo usuarios.

`router` (`/auth`): registro, login, logout (C-07), perfil y cambio de contraseña (C-08). Vive
en el grupo abierto (RN06): `/auth/yo` y `/auth/cambiar-password` piden la sesión por ruta
(`UsuarioActualDep`) y responden aunque haya un cambio de contraseña pendiente.

`router_personal` (`/usuarios`) y `router_eventos` (`/eventos`) (C-09): grupo protegido, sólo
ADMIN. `requiere_rol` con `Rol.ADMIN` se crea UNA vez (`solo_admin`) y se usa a nivel de router y
como `AdminDep` en los handlers: FastAPI cachea la misma función por petición y los roles se
consultan una sola vez. No hay `GET /usuarios` (IN-02).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.dependencies import UsuarioActualDep, requiere_rol
from app.core.paginacion import Pagina, PaginacionDep
from app.core.schemas import IdRuta
from app.core.security import aplicar_cookie_acceso, eliminar_cookie_acceso
from app.modules.usuarios import service
from app.modules.usuarios.models import Rol
from app.modules.usuarios.schemas import (
    AsignacionRolEntrada,
    AsignacionSalida,
    CambioPasswordEntrada,
    EventoSalida,
    LoginEntrada,
    LoginSalida,
    MensajeSalida,
    PerfilSalida,
    PersonalAltaEntrada,
    PersonalSalida,
    RegistroEntrada,
    RegistroSalida,
    RolesUsuarioSalida,
)
from app.modules.usuarios.service import UsuarioActual
from app.modules.usuarios.unit_of_work import AnotadorIntentosDep, UsuariosUoWDep

router = APIRouter(prefix="/auth", tags=["auth"])

solo_admin = requiere_rol(Rol.ADMIN)  # UNA función: FastAPI la cachea por petición
AdminDep = Annotated[UsuarioActual, Depends(solo_admin)]

router_personal = APIRouter(prefix="/usuarios", tags=["personal"], dependencies=[Depends(solo_admin)])
router_eventos = APIRouter(prefix="/eventos", tags=["eventos"], dependencies=[Depends(solo_admin)])

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


@router_eventos.get("")
async def eventos(pag: PaginacionDep, uow: UsuariosUoWDep) -> Pagina[EventoSalida]:
    return await service.listar_eventos(uow, pag)


@router_personal.post("", status_code=201)
async def alta(
    datos: PersonalAltaEntrada, actual: AdminDep, uow: UsuariosUoWDep
) -> PersonalSalida:
    return await service.alta_personal(uow, actual, datos)


@router_personal.post("/{usuario_id}/roles", status_code=201)
async def asignar_rol(
    usuario_id: IdRuta, datos: AsignacionRolEntrada, actual: AdminDep, uow: UsuariosUoWDep
) -> AsignacionSalida:
    return await service.asignar_rol(uow, actual, usuario_id, datos)


@router_personal.get("/{usuario_id}/roles")
async def roles_de_usuario(usuario_id: IdRuta, uow: UsuariosUoWDep) -> RolesUsuarioSalida:
    return await service.roles_de_usuario(uow, usuario_id)


@router_personal.delete("/{usuario_id}/roles/{rol}")
async def revocar_rol(
    usuario_id: IdRuta, rol: Rol, actual: AdminDep, uow: UsuariosUoWDep
) -> AsignacionSalida:
    return await service.revocar_rol(uow, actual, usuario_id, rol)
