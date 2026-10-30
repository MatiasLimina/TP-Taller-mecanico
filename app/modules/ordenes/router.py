"""Rutas del módulo órdenes (C-13): `GET /estados-orden` (y, desde 5.2, el alta de órdenes).

Dos `APIRouter` en el grupo protegido (RN06, S-15):

- `router_estados` (`/estados-orden`): cualquier usuario autenticado. Sólo depende del grupo
  protegido (`exigir_password_al_dia`: 401 sin sesión, 403 con cambio de contraseña pendiente);
  no lleva `requiere_rol` porque la matriz dice «Autenticado». Sólo lectura (RN19).
- `router_ordenes` (`/ordenes`): SIN rol a nivel de router. `/ordenes` mezcla roles: el alta es
  RECEPCION/ADMIN, `GET /ordenes` (C-15) suma MECANICO, `iniciar` es MECANICO y
  `cancelar`/`terminar`/`GET /ordenes/{id}` no llevan `requiere_rol` (dueño, mecánico asignado).
  Un rol de router obligaría a C-14/C-15 a crear routers paralelos con el mismo prefijo: el rol
  va POR RUTA.

Orden de los rechazos: 401 -> 403 (cambio pendiente) -> 403 (rol) -> 422 -> 409.
"""

from fastapi import APIRouter

from app.modules.ordenes import service
from app.modules.ordenes.schemas import EstadoOrdenSalida
from app.modules.ordenes.unit_of_work import OrdenesUoWDep

router_estados = APIRouter(prefix="/estados-orden", tags=["estados-orden"])


@router_estados.get("")
async def listar_estados(uow: OrdenesUoWDep) -> list[EstadoOrdenSalida]:
    return await service.listar_estados(uow)
