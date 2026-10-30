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

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.errores import Conflicto, EntradaInvalida, restriccion_violada
from app.modules.ordenes.models import (
    CodigoEstado,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.ordenes.schemas import (
    EstadoOrdenSalida,
    HistorialEstadoSalida,
    ItemAltaEntrada,
    ItemOrdenSalida,
    OrdenAltaEntrada,
    OrdenDetalleSalida,
)
from app.modules.ordenes.unit_of_work import OrdenesUoW

ESTADO_INICIAL = CodigoEstado.PENDIENTE
CENTAVO = Decimal("0.01")
TOTAL_MAXIMO = Decimal("9999999999.99")  # = NUMERIC(12, 2) de orden_trabajo.total
# La FK al catálogo rechaza un estado que alguien sacó por psql entre la verificación y el INSERT:
# se traduce al mismo 409 de catálogo (el catálogo no se edita desde la API, RN19).
RESTRICCIONES_DE_ESTADO = frozenset(
    {
        "fk_orden_trabajo_estado_estado_orden",
        "fk_historial_estado_orden_hasta_estado_estado_orden",
    }
)

MENSAJE_CATALOGO_SIN_ESTADO_INICIAL = (
    "No se pueden crear órdenes: el catálogo de estados está vacío o no tiene el estado PENDIENTE"
)
MENSAJE_VEHICULO_NO_DISPONIBLE = "El vehículo {vehiculo_id} no existe o está dado de baja"
MENSAJE_REPUESTOS_NO_DISPONIBLES = "Repuestos inexistentes o dados de baja: {ids}"
MENSAJE_TOTAL_EXCEDIDO = f"El total de la orden supera el máximo admitido ({TOTAL_MAXIMO})"


def calcular_total(items: Sequence[ItemAltaEntrada], precios: Mapping[int, Decimal]) -> Decimal:
    """Suma exacta en `Decimal` de `precio × cantidad` (S-13), cuantizada a centavos."""
    return sum((precios[i.repuesto_id] * i.cantidad for i in items), Decimal(0)).quantize(CENTAVO)


def armar_detalle(orden: OrdenTrabajo) -> OrdenDetalleSalida:
    """Salida de detalle desde una orden leída con `OrdenTrabajoRepository.get_detalle`.

    La usan el alta (C-13) y, en C-15, `GET /ordenes/{id}`: una sola forma y un solo armado. Sólo
    lee relaciones precargadas por `get_detalle` (con `lazy="raise"`, leer otra lanzaría en lugar
    de consultar). `items` e `historial` llegan en orden de id; los ítems se guardan en el orden
    del cuerpo, así que la respuesta lo respeta.
    """
    return OrdenDetalleSalida(
        id=orden.id,  # type: ignore[arg-type]
        estado=orden.estado,
        patente=orden.vehiculo.patente,
        total=orden.total,
        creada_en=orden.creada_en,
        mecanico_id=orden.mecanico_id,
        falla=orden.falla,
        cliente=orden.vehiculo.cliente.nombre,
        items=[
            ItemOrdenSalida(
                repuesto_id=i.repuesto_id,
                codigo=i.repuesto.codigo,
                descripcion=i.repuesto.descripcion,
                cantidad=i.cantidad,
                precio_unitario=i.precio_unitario,
                subtotal=(i.precio_unitario * i.cantidad).quantize(CENTAVO),
            )
            for i in orden.items
        ],
        historial=[HistorialEstadoSalida.model_validate(h) for h in orden.historial],
    )


async def alta(uow: OrdenesUoW, datos: OrdenAltaEntrada, usuario_id: int) -> OrdenDetalleSalida:
    """Alta atómica de una orden `PENDIENTE` con sus ítems y su primera línea de historial.

    Todos los rechazos de negocio se deciden ANTES de escribir, con mensaje propio (RN16, RN19):
    una excepción que sale del bloque revierte y libera los bloqueos, y no queda ni orden, ni
    ítems, ni historial. Después del primer `add` ningún paso falla por regla de negocio: el
    vehículo y los repuestos están bloqueados y nunca se borran físicamente, y el contrato impide
    el resto; si aun así una restricción de la base saltara, el manejador global responde un
    409/422 genérico (nunca 500 ni texto de la base).

    El precio de cada ítem se COPIA del repuesto leído bajo `FOR SHARE` y el total se calcula acá
    (RN10): el cliente no manda ninguno. `creada_en` y el `cuando` del historial son el MISMO
    instante (S-12). No toca `stock` ni crea movimientos (RN14, S-17): el stock se valida y baja
    al terminar la orden (C-14).
    """
    try:
        async with uow:
            if await uow.estados.get_por_codigo(ESTADO_INICIAL.value) is None:  # RN19
                raise Conflicto(MENSAJE_CATALOGO_SIN_ESTADO_INICIAL)
            # Orden de bloqueo (design D6): vehículo FOR UPDATE -> repuestos FOR SHARE ascendentes.
            vehiculo = await uow.vehiculos.get_vigente_para_actualizar(datos.vehiculo_id)
            if vehiculo is None:
                raise Conflicto(
                    MENSAJE_VEHICULO_NO_DISPONIBLE.format(vehiculo_id=datos.vehiculo_id)
                )
            pedidos = [i.repuesto_id for i in datos.items]
            repuestos = await uow.repuestos.listar_vigentes_para_orden(pedidos)
            precios = {r.id: r.precio for r in repuestos if r.id is not None}
            faltantes = sorted(set(pedidos) - precios.keys())
            if faltantes:
                raise Conflicto(
                    MENSAJE_REPUESTOS_NO_DISPONIBLES.format(ids=", ".join(map(str, faltantes)))
                )
            total = calcular_total(datos.items, precios)
            if total > TOTAL_MAXIMO:
                raise EntradaInvalida(MENSAJE_TOTAL_EXCEDIDO)
            ahora = datetime.now(UTC)
            orden = await uow.ordenes.add(
                OrdenTrabajo(  # sin mecanico_id: lo asigna `iniciar` (C-14)
                    vehiculo_id=datos.vehiculo_id,
                    estado=ESTADO_INICIAL.value,
                    falla=datos.falla,
                    total=total,
                    creada_en=ahora,
                )
            )
            assert orden.id is not None
            await uow.items.add_varios(
                [  # en el orden del cuerpo: los ids crecen en ese orden
                    ItemOrden(
                        orden_id=orden.id,
                        repuesto_id=i.repuesto_id,
                        cantidad=i.cantidad,
                        precio_unitario=precios[i.repuesto_id],
                    )
                    for i in datos.items
                ]
            )
            await uow.historial.add(
                HistorialEstadoOrden(
                    orden_id=orden.id,
                    desde_estado=None,
                    hasta_estado=ESTADO_INICIAL.value,
                    usuario_id=usuario_id,
                    cuando=ahora,
                )
            )
            detalle = await uow.ordenes.get_detalle(orden.id)
            assert detalle is not None
            salida = armar_detalle(detalle)  # dentro del bloque, con todo precargado
    except IntegrityError as exc:
        if restriccion_violada(exc) in RESTRICCIONES_DE_ESTADO:
            # El catálogo cambió por psql entre la verificación y el INSERT (RN19).
            raise Conflicto(MENSAJE_CATALOGO_SIN_ESTADO_INICIAL) from None
        raise
    return salida


async def listar_estados(uow: OrdenesUoW) -> list[EstadoOrdenSalida]:
    """Catálogo completo en orden de `posicion` (RN19, sólo lectura); vacío -> `[]`."""
    async with uow:
        estados = await uow.estados.listar()
        salida = [EstadoOrdenSalida.model_validate(e) for e in estados]
    return salida
