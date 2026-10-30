"""Rutas del módulo órdenes (C-13): alta de una orden de trabajo y catálogo de estados.

Dos `APIRouter` en el grupo protegido (RN06, S-15):

- `router_ordenes` (`/ordenes`): SIN rol a nivel de router. `/ordenes` mezcla roles: el alta es
  RECEPCION/ADMIN (`alta_orden`, creada UNA vez), `GET /ordenes` (C-15) suma MECANICO, `iniciar` es
  MECANICO y `cancelar`/`terminar`/`GET /ordenes/{id}` no llevan `requiere_rol` (dueño, mecánico
  asignado). Un rol de router obligaría a C-14/C-15 a crear routers paralelos con el mismo prefijo:
  el rol va POR RUTA.
- `router_estados` (`/estados-orden`): cualquier usuario autenticado. Sólo depende del grupo
  protegido (`exigir_password_al_dia`: 401 sin sesión, 403 con cambio de contraseña pendiente); no
  lleva `requiere_rol` porque la matriz dice «Autenticado». Sólo lectura (RN19).

El handler del alta necesita el actor (se guarda en el historial), así que `AltaOrdenDep` va como
parámetro y FastAPI la resuelve antes de validar el cuerpo. Orden de los rechazos: 401 -> 403
(cambio pendiente) -> 403 (rol) -> 422 -> 409; un JSON mal formado da 422 antes de resolver
dependencias. El servicio recibe `actual.id` y no `UsuarioActual`: `ordenes.service` no depende de
`usuarios.service`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import requiere_rol
from app.modules.ordenes import service
from app.modules.ordenes.schemas import (
    EstadoOrdenSalida,
    OrdenAltaEntrada,
    OrdenDetalleSalida,
)
from app.modules.ordenes.unit_of_work import OrdenesUoWDep
from app.modules.usuarios.models import Rol
from app.modules.usuarios.service import UsuarioActual

alta_orden = requiere_rol(Rol.RECEPCION, Rol.ADMIN)  # UNA función
AltaOrdenDep = Annotated[UsuarioActual, Depends(alta_orden)]

router_ordenes = APIRouter(prefix="/ordenes", tags=["ordenes"])
router_estados = APIRouter(prefix="/estados-orden", tags=["estados-orden"])


@router_ordenes.post("", status_code=201)
async def alta(
    datos: OrdenAltaEntrada, actual: AltaOrdenDep, uow: OrdenesUoWDep
) -> OrdenDetalleSalida:
    return await service.alta(uow, datos, actual.id)


@router_estados.get("")
async def listar_estados(uow: OrdenesUoWDep) -> list[EstadoOrdenSalida]:
    return await service.listar_estados(uow)
