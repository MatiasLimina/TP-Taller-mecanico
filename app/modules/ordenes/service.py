"""Servicio de órdenes (C-13): catálogo de estados y alta de una orden de trabajo.

Los servicios no conocen HTTP: lanzan errores de aplicación (`app/core/errores.py`). El router
construye el Unit of Work (`OrdenesUoWDep`) y el servicio lo abre con `async with`; nunca lo
construye ni lo anida. La traducción de un error de integridad se hace FUERA del bloque y la salida
se arma DENTRO, con los valores aún cargados (misma convención que `clientes/service.py`).

Orden de las verificaciones del alta (design D7, el del Flujo 4 de la KB): catálogo (sin bloqueo,
así un 409 de catálogo no bloquea nada) -> vehículo (`FOR UPDATE`) -> repuestos (`FOR SHARE`, una
consulta, en orden ascendente de id) -> total. Es también el orden global de bloqueo de filas
(design D6): una orden existente -> vehículo -> repuestos por id ascendente; cada rechazo es una
excepción que sale del bloque y el Unit of Work revierte y libera los bloqueos.

Este módulo NUNCA escribe `stock` ni crea `MovimientoStock` (RN14, REPARTO §9): el stock baja
sólo al terminar una orden (C-14), por el punto único de escritura de `repuestos/service.py`.
"""

from app.modules.ordenes.schemas import EstadoOrdenSalida
from app.modules.ordenes.unit_of_work import OrdenesUoW


async def listar_estados(uow: OrdenesUoW) -> list[EstadoOrdenSalida]:
    """Catálogo completo en orden de `posicion` (RN19, sólo lectura); vacío -> `[]`."""
    async with uow:
        estados = await uow.estados.listar()
        salida = [EstadoOrdenSalida.model_validate(e) for e in estados]
    return salida
