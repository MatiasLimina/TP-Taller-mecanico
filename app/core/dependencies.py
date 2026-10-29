"""Dependencias de autenticación y autorización (C-08): adaptador HTTP fino.

- `get_usuario_actual` lee la cookie `access_token` (DD-04: el token no viaja en otro encabezado) y llama al
  servicio. Las reglas (401, RN07) viven en `usuarios/service.py`; el Unit of Work llega por
  inyección (`UsuariosUoWDep`) y el servicio lo abre. FastAPI ejecuta la dependencia una sola
  vez por petición aunque la pidan el grupo, `requiere_rol` y el handler.
- `exigir_password_al_dia` (RN06) se monta UNA vez, en el grupo `rutas_protegidas` de `main.py`.
- `requiere_rol(*roles)` (RN04) consulta los roles vigentes en la base en cada petición; los
  roles del token son informativos. Sin comodín: `ADMIN` pasa sólo donde se lo nombra.

Orden de los rechazos: 401 (sesión) -> 403 (cambio pendiente) -> 403 (rol) -> 422 -> operación.
La única excepción es un JSON mal formado, que FastAPI rechaza (422) antes de resolver
dependencias.

Esta es la única dependencia de `core` hacia un módulo de dominio (S-09): la ubicación la fija
la KB y mantiene la lógica de negocio en el servicio.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from app.core.errores import SinPermiso
from app.core.security import NOMBRE_COOKIE_ACCESO
from app.modules.usuarios import service
from app.modules.usuarios.models import Rol
from app.modules.usuarios.service import UsuarioActual
from app.modules.usuarios.unit_of_work import UsuariosUoWDep


async def get_usuario_actual(request: Request, uow: UsuariosUoWDep) -> UsuarioActual:
    return await service.autenticar(uow, request.cookies.get(NOMBRE_COOKIE_ACCESO))


UsuarioActualDep = Annotated[UsuarioActual, Depends(get_usuario_actual)]


async def exigir_password_al_dia(actual: UsuarioActualDep) -> None:
    if actual.debe_cambiar_password:
        raise SinPermiso(service.MENSAJE_CAMBIO_PENDIENTE)


def requiere_rol(*roles: Rol) -> Callable[..., Awaitable[UsuarioActual]]:
    if not roles:
        raise ValueError("requiere_rol necesita al menos un rol")
    permitidos = frozenset(rol.value for rol in roles)

    # RN06 también acá (no sólo en el grupo): una ruta con rol no se saltea el 403 por cambio
    # pendiente aunque se monte fuera de `rutas_protegidas`. FastAPI cachea ambas dependencias
    # por petición (costo cero) y el orden de los parámetros fija 401 -> 403 cambio -> 403 rol.
    async def dependencia(
        actual: UsuarioActualDep,
        _cambio_al_dia: Annotated[None, Depends(exigir_password_al_dia)],
        uow: UsuariosUoWDep,
    ) -> UsuarioActual:
        await service.exigir_roles(uow, actual.id, permitidos)
        return actual

    return dependencia
