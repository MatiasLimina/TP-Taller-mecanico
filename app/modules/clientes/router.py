"""Rutas del módulo clientes (C-10): fichas, vehículos y `/mis-vehiculos`.

Tres `APIRouter` en el grupo protegido (RN06, S-15):

- `router_clientes` (`/clientes`) y `router_vehiculos` (`/vehiculos`): sólo RECEPCION y ADMIN.
  El rol se controla a nivel de router con UNA función (`personal_clientes`): ninguna ruta nueva
  lo olvida y un usuario sin rol recibe 403 exista o no el id (S-08).
- `router_mis_vehiculos` (`/mis-vehiculos`): cualquier usuario autenticado (RN17); el filtro es
  siempre el usuario de la sesión, la ruta no acepta ningún id.

Orden de los rechazos: 401 -> 403 (cambio pendiente) -> 403 (rol) -> 422 -> 404 -> 409.
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import UsuarioActualDep, requiere_rol
from app.core.schemas import IdRuta
from app.modules.clientes import service
from app.modules.clientes.schemas import (
    ClienteAltaEntrada,
    ClienteDetalleSalida,
    ClienteSalida,
    VehiculoAltaEntrada,
    VehiculoSalida,
)
from app.modules.clientes.unit_of_work import ClientesUoWDep
from app.modules.usuarios.models import Rol

personal_clientes = requiere_rol(Rol.RECEPCION, Rol.ADMIN)  # UNA función para los dos routers

router_clientes = APIRouter(
    prefix="/clientes", tags=["clientes"], dependencies=[Depends(personal_clientes)]
)
router_vehiculos = APIRouter(
    prefix="/vehiculos", tags=["vehiculos"], dependencies=[Depends(personal_clientes)]
)
router_mis_vehiculos = APIRouter(prefix="/mis-vehiculos", tags=["mis-vehiculos"])


@router_clientes.post("", status_code=201)
async def alta_cliente(datos: ClienteAltaEntrada, uow: ClientesUoWDep) -> ClienteSalida:
    return await service.alta_cliente(uow, datos)


@router_clientes.get("/{cliente_id}")
async def detalle_cliente(cliente_id: IdRuta, uow: ClientesUoWDep) -> ClienteDetalleSalida:
    return await service.detalle_cliente(uow, cliente_id)


@router_clientes.post("/{cliente_id}/vehiculos", status_code=201)
async def alta_vehiculo(
    cliente_id: IdRuta, datos: VehiculoAltaEntrada, uow: ClientesUoWDep
) -> VehiculoSalida:
    return await service.alta_vehiculo(uow, cliente_id, datos)


@router_vehiculos.delete("/{vehiculo_id}", status_code=204)
async def baja_vehiculo(vehiculo_id: IdRuta, uow: ClientesUoWDep) -> None:
    await service.baja_vehiculo(uow, vehiculo_id)


@router_mis_vehiculos.get("")
async def mis_vehiculos(actual: UsuarioActualDep, uow: ClientesUoWDep) -> list[VehiculoSalida]:
    # RN17: el filtro es SIEMPRE el usuario de la sesión; la ruta no recibe ningún id.
    return await service.mis_vehiculos(uow, actual.id)
