"""Rutas del módulo repuestos (C-11 catálogo, alta, edición y baja; C-12 reposición e historiales).

Dos `APIRouter` con el mismo prefijo `/repuestos` (S-13), ambos en el grupo protegido (RN06):

- `router_catalogo` (lectura): ADMIN, RECEPCION y MECANICO.
- `router_admin_repuestos` (escritura): sólo ADMIN. C-12 cuelga de acá `POST /{id}/reponer`,
  `GET /{id}/movimientos` y `GET /{id}/precios` (S-12: `main.py` no cambia; una consulta de
  roles por petición). Los historiales van sin paginar y en orden cronológico (S-05, S-06).

Cada `requiere_rol` se crea UNA vez (`personal_repuestos`, `solo_admin`) y se usa a nivel de
router (y como `AdminDep` en los handlers que necesitan el id del actor): FastAPI cachea la
misma función por petición, así cada petición consulta los roles una sola vez. Starlette, ante
`PATCH /repuestos/{id}`, pasa por la coincidencia parcial del `GET` y sigue hasta la ruta
`PATCH` del segundo router: no hay conflicto.

Orden de los rechazos: 401 -> 403 (cambio pendiente) -> 403 (rol) -> 422 -> 404 -> 409.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import requiere_rol
from app.core.paginacion import Pagina, PaginacionDep
from app.core.schemas import IdRuta
from app.modules.repuestos import service
from app.modules.repuestos.schemas import (
    LARGO_MAXIMO_BUSQUEDA,
    MovimientoSalida,
    PrecioHistorialSalida,
    ReposicionEntrada,
    RepuestoAltaEntrada,
    RepuestoEdicionEntrada,
    RepuestoSalida,
)
from app.modules.repuestos.unit_of_work import RepuestosUoWDep
from app.modules.usuarios.models import Rol
from app.modules.usuarios.service import UsuarioActual

personal_repuestos = requiere_rol(Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO)  # UNA función
solo_admin = requiere_rol(Rol.ADMIN)  # UNA función
AdminDep = Annotated[UsuarioActual, Depends(solo_admin)]
Busqueda = Annotated[str | None, Query(max_length=LARGO_MAXIMO_BUSQUEDA)]

router_catalogo = APIRouter(
    prefix="/repuestos", tags=["repuestos"], dependencies=[Depends(personal_repuestos)]
)
router_admin_repuestos = APIRouter(
    prefix="/repuestos", tags=["repuestos"], dependencies=[Depends(solo_admin)]
)


@router_catalogo.get("")
async def listar(
    pag: PaginacionDep, uow: RepuestosUoWDep, q: Busqueda = None
) -> Pagina[RepuestoSalida]:
    return await service.listar(uow, pag, q)


@router_catalogo.get("/{repuesto_id}")
async def detalle(repuesto_id: IdRuta, uow: RepuestosUoWDep) -> RepuestoSalida:
    return await service.detalle(uow, repuesto_id)


@router_admin_repuestos.post("", status_code=201)
async def alta(
    datos: RepuestoAltaEntrada, actual: AdminDep, uow: RepuestosUoWDep
) -> RepuestoSalida:
    return await service.alta(uow, datos, actual.id)


@router_admin_repuestos.patch("/{repuesto_id}")
async def editar(
    repuesto_id: IdRuta,
    datos: RepuestoEdicionEntrada,
    actual: AdminDep,
    uow: RepuestosUoWDep,
) -> RepuestoSalida:
    return await service.editar(uow, repuesto_id, datos, actual.id)


@router_admin_repuestos.delete("/{repuesto_id}", status_code=204)
async def baja(repuesto_id: IdRuta, uow: RepuestosUoWDep) -> None:
    await service.baja(uow, repuesto_id)


@router_admin_repuestos.post("/{repuesto_id}/reponer", status_code=200)
async def reponer(
    repuesto_id: IdRuta,
    datos: ReposicionEntrada,
    actual: AdminDep,
    uow: RepuestosUoWDep,
) -> RepuestoSalida:
    return await service.reponer(uow, repuesto_id, datos, actual.id)


@router_admin_repuestos.get("/{repuesto_id}/movimientos")
async def listar_movimientos(repuesto_id: IdRuta, uow: RepuestosUoWDep) -> list[MovimientoSalida]:
    return await service.listar_movimientos(uow, repuesto_id)


@router_admin_repuestos.get("/{repuesto_id}/precios")
async def listar_precios(repuesto_id: IdRuta, uow: RepuestosUoWDep) -> list[PrecioHistorialSalida]:
    return await service.listar_precios(uow, repuesto_id)
