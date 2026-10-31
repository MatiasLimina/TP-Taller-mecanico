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

Transiciones (C-14, `POST /ordenes/{orden_id}/iniciar|terminar|cancelar`): sin cuerpo (nada viaja
del cliente: estado destino, mecánico y actor los decide el servidor) y con `IdRuta` (422 si el id
no es entero o está fuera de 1..INT4). Orden de los rechazos:

- `iniciar` (`iniciar_orden = requiere_rol(Rol.MECANICO)`, creada UNA vez): 401 -> 403 (cambio
  pendiente) -> 403 (rol; un ADMIN sin MECANICO no pasa) -> 422 -> 404 -> 409.
- `terminar` y `cancelar` NO llevan `requiere_rol`: el permiso depende de la relación con la orden
  (mecánico asignado, dueño), que sólo se conoce después de leerla. Lo decide el servicio, con los
  roles vigentes de la base: 401 -> 403 (cambio pendiente) -> 422 -> 404 -> 403 (sin relación) ->
  409. Primero 404 y después 403 (S-07): el PDF pide 403 para «una orden ajena».

Lecturas (C-15): `GET /ordenes` exige RECEPCION, ADMIN o MECANICO vigentes con `lectura_ordenes` en `dependencies=` de la ruta (el handler no usa al actor): 401 -> 403 (cambio pendiente) -> 403 (rol) -> 422 (`estado`, `page`, `size`). `GET /ordenes/{orden_id}` no lleva `requiere_rol`: personal o dueño del vehículo lo decide el servicio, 401 -> 403 (cambio pendiente) -> 422 -> 404 -> 403. `GET /mis-ordenes` (`router_mis_ordenes`, montado en `main.py`) sólo pide sesión y filtra siempre por el usuario de la sesión (RN17).
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.core.dependencies import UsuarioActualDep, requiere_rol
from app.core.paginacion import Pagina, PaginacionDep
from app.core.schemas import IdRuta
from app.modules.ordenes import service
from app.modules.ordenes.models import CodigoEstado
from app.modules.ordenes.schemas import (
    EstadoOrdenSalida,
    OrdenAltaEntrada,
    OrdenDetalleSalida,
    OrdenResumenSalida,
)
from app.modules.ordenes.unit_of_work import OrdenesUoWDep
from app.modules.usuarios.models import Rol
from app.modules.usuarios.service import UsuarioActual

alta_orden = requiere_rol(Rol.RECEPCION, Rol.ADMIN)  # UNA función
AltaOrdenDep = Annotated[UsuarioActual, Depends(alta_orden)]
iniciar_orden = requiere_rol(Rol.MECANICO)  # UNA función (C-14)
IniciarOrdenDep = Annotated[UsuarioActual, Depends(iniciar_orden)]

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


@router_ordenes.post("/{orden_id}/iniciar", status_code=200)
async def iniciar(
    orden_id: IdRuta, actual: IniciarOrdenDep, uow: OrdenesUoWDep
) -> OrdenDetalleSalida:
    return await service.iniciar(uow, orden_id, actual.id)


@router_ordenes.post("/{orden_id}/cancelar", status_code=200)
async def cancelar(
    orden_id: IdRuta, actual: UsuarioActualDep, uow: OrdenesUoWDep
) -> OrdenDetalleSalida:
    return await service.cancelar(uow, orden_id, actual.id)


@router_ordenes.post("/{orden_id}/terminar", status_code=200)
async def terminar(
    orden_id: IdRuta, actual: UsuarioActualDep, uow: OrdenesUoWDep, tareas: BackgroundTasks
) -> OrdenDetalleSalida:
    salida = await service.terminar(uow, orden_id, actual.id)  # al volver, YA confirmó
    # Recién ahora se agenda el aviso (corre después de la respuesta): si el servicio lanzó
    # (403/404/409), esta línea no se ejecuta. Se llama por el módulo, no por import directo.
    tareas.add_task(service.avisar_orden_terminada, salida.id, salida.patente)
    return salida


lectura_ordenes = requiere_rol(Rol.RECEPCION, Rol.ADMIN, Rol.MECANICO)  # UNA función (C-15)
FiltroEstado = Annotated[CodigoEstado | None, Query()]


@router_ordenes.get("", dependencies=[Depends(lectura_ordenes)])
async def listar_ordenes(
    pag: PaginacionDep, uow: OrdenesUoWDep, estado: FiltroEstado = None
) -> Pagina[OrdenResumenSalida]:
    return await service.listar_ordenes(uow, pag, estado)


@router_ordenes.get("/{orden_id}")
async def detalle_orden(
    orden_id: IdRuta, actual: UsuarioActualDep, uow: OrdenesUoWDep
) -> OrdenDetalleSalida:
    return await service.detalle_orden(uow, orden_id, actual.id)
