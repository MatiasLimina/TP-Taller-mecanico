"""Servicio de clientes y vehículos (C-10): fichas, vehículos, lo propio y la baja lógica.

Los servicios no conocen HTTP: lanzan errores de aplicación (`app/core/errores.py`). El router
construye el Unit of Work y el servicio lo abre con `async with`. La unicidad (documento,
patente vigente) la decide la base, sin consulta previa (RN01): el servicio traduce la violación
FUERA del bloque y arma la salida DENTRO, con los valores aún cargados.
"""

from sqlalchemy.exc import IntegrityError

from app.core.errores import Conflicto, NoEncontrado, restriccion_violada
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.clientes.schemas import (
    ClienteAltaEntrada,
    ClienteDetalleSalida,
    ClienteSalida,
    VehiculoAltaEntrada,
    VehiculoSalida,
)
from app.modules.clientes.unit_of_work import ClientesUoW

MENSAJE_CLIENTE_INEXISTENTE = "El cliente no existe"
MENSAJE_DOCUMENTO_REPETIDO = "El documento ya pertenece a un cliente del taller"
MENSAJE_PATENTE_REPETIDA = "Ya hay un vehículo vigente con la patente {patente}"
MENSAJE_VEHICULO_INEXISTENTE = "El vehículo no existe"
MENSAJE_VEHICULO_CON_ORDENES = "El vehículo tiene órdenes abiertas y no se puede dar de baja"


async def alta_cliente(uow: ClientesUoW, datos: ClienteAltaEntrada) -> ClienteSalida:
    try:
        async with uow:
            cliente = await uow.clientes.add(
                Cliente(nombre=datos.nombre, documento=datos.documento, telefono=datos.telefono)
            )
            salida = ClienteSalida.model_validate(cliente)
    except IntegrityError as exc:
        if restriccion_violada(exc) == "uq_cliente_documento":
            raise Conflicto(MENSAJE_DOCUMENTO_REPETIDO) from None
        raise
    return salida


async def detalle_cliente(uow: ClientesUoW, cliente_id: int) -> ClienteDetalleSalida:
    async with uow:
        cliente = await uow.clientes.get_con_vehiculos(cliente_id)
        if cliente is None:
            raise NoEncontrado(MENSAJE_CLIENTE_INEXISTENTE)
        # La precarga no tiene `order_by` (los modelos no se tocan, S-17): se ordena acá.
        vehiculos = sorted(cliente.vehiculos, key=lambda v: v.id or 0)
        salida = ClienteDetalleSalida(
            id=cliente.id,  # type: ignore[arg-type]
            usuario_id=cliente.usuario_id,
            nombre=cliente.nombre,
            documento=cliente.documento,
            telefono=cliente.telefono,
            vehiculos=[VehiculoSalida.model_validate(v) for v in vehiculos],
        )
    return salida


async def alta_vehiculo(
    uow: ClientesUoW, cliente_id: int, datos: VehiculoAltaEntrada
) -> VehiculoSalida:
    try:
        async with uow:
            if await uow.clientes.get_by_id(cliente_id) is None:
                raise NoEncontrado(MENSAJE_CLIENTE_INEXISTENTE)
            vehiculo = await uow.vehiculos.add(
                Vehiculo(
                    cliente_id=cliente_id,
                    patente=datos.patente,
                    marca=datos.marca,
                    modelo=datos.modelo,
                    anio=datos.anio,
                )
            )
            salida = VehiculoSalida.model_validate(vehiculo)
    except IntegrityError as exc:
        if restriccion_violada(exc) == "uq_vehiculo_patente":
            # El mensaje sale del contrato (`datos`), no de la entidad que el rollback expiró.
            raise Conflicto(MENSAJE_PATENTE_REPETIDA.format(patente=datos.patente)) from None
        raise
    return salida


async def mis_vehiculos(uow: ClientesUoW, usuario_id: int) -> list[VehiculoSalida]:
    """Vehículos vigentes de la ficha del usuario (RN17); sin ficha vinculada, lista vacía."""
    async with uow:
        vehiculos = await uow.vehiculos.listar_de_usuario(usuario_id)
        salida = [VehiculoSalida.model_validate(v) for v in vehiculos]
    return salida


async def baja_vehiculo(uow: ClientesUoW, vehiculo_id: int) -> None:
    async with uow:
        # La fila queda bloqueada hasta confirmar (S-02): la baja se serializa con el alta de
        # órdenes de C-13, que bloquea la misma fila al verificar "vehículo vigente". Si la
        # orden se confirma primero, acá se la ve (409); si la baja va primero, el alta no
        # encuentra el vehículo vigente.
        vehiculo = await uow.vehiculos.get_vigente_para_actualizar(vehiculo_id)
        if vehiculo is None:  # inexistente o ya dado de baja (S-18)
            raise NoEncontrado(MENSAJE_VEHICULO_INEXISTENTE)
        # RN16: lo decide el catálogo de estados (`es_final`), no una lista de códigos.
        if await uow.vehiculos.tiene_ordenes_abiertas(vehiculo_id):
            raise Conflicto(MENSAJE_VEHICULO_CON_ORDENES)
        await uow.vehiculos.soft_delete(vehiculo)
