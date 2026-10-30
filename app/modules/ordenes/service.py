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

Transiciones de estado (C-14: `iniciar`, `terminar`, `cancelar`). Las tres siguen el mismo contrato,
en este orden y dentro de UN bloque `async with uow`: bloquear la orden (`FOR UPDATE`, siempre la
PRIMERA fila que se bloquea; 404 si no existe) -> permiso (403, con los roles vigentes leídos en la
base, RN04; `iniciar` lo resuelve el router con `requiere_rol`) -> estado (409, guiado por el
catálogo) -> escribir (`terminar` descuenta el stock) -> releer el detalle con `get_detalle` y
armar la salida. Orden de bloqueo (design D3): la orden, después los repuestos por id ascendente
(sólo por el punto único de stock); nunca un vehículo. El stock cambia ÚNICAMENTE por
`aplicar_movimientos_stock` y `StockInsuficiente` no se captura dentro del bloque: sale y el Unit of
Work revierte todo (RN13). El servicio no conoce `BackgroundTasks`: el aviso al cliente lo agenda el
router DESPUÉS de que `terminar` vuelve (es decir, después del commit).
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

from sqlalchemy.exc import IntegrityError

from app.core.errores import (
    Conflicto,
    EntradaInvalida,
    NoEncontrado,
    SinPermiso,
    restriccion_violada,
)
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
from app.modules.repuestos.service import MovimientoPedido, aplicar_movimientos_stock
from app.modules.usuarios.models import Rol

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

# -- Transiciones (C-14) ---------------------------------------------------------------------
# Único estado de origen de cada destino (RN11): iniciar PENDIENTE -> EN_REPARACION, terminar
# EN_REPARACION -> TERMINADA y cancelar PENDIENTE -> CANCELADA (RN12). Si el estado actual es final
# según el catálogo (RN19), ninguna transición es posible, sea cual sea el destino.
ORIGEN: Mapping[CodigoEstado, CodigoEstado] = MappingProxyType(
    {
        CodigoEstado.EN_REPARACION: CodigoEstado.PENDIENTE,
        CodigoEstado.TERMINADA: CodigoEstado.EN_REPARACION,
        CodigoEstado.CANCELADA: CodigoEstado.PENDIENTE,
    }
)
ACCION: Mapping[CodigoEstado, str] = MappingProxyType(
    {
        CodigoEstado.EN_REPARACION: "iniciar",
        CodigoEstado.TERMINADA: "terminar",
        CodigoEstado.CANCELADA: "cancelar",
    }
)
# Personal que puede cancelar cualquier orden; además puede cancelar el dueño del vehículo (S-08).
ROLES_QUE_CANCELAN = frozenset({Rol.RECEPCION.value, Rol.ADMIN.value})
MOTIVO_ORDEN_TERMINADA = "Orden #{orden_id} terminada"

MENSAJE_ORDEN_INEXISTENTE = "La orden no existe"
MENSAJE_SIN_PERMISO_TERMINAR = "Sólo el mecánico asignado o un administrador puede terminar la orden"
MENSAJE_SIN_PERMISO_CANCELAR = (
    "Sólo la recepción, un administrador o el dueño del vehículo puede cancelar la orden"
)
MENSAJE_ESTADO_FINAL = "La orden {orden_id} está {estado}, un estado final: no admite más cambios"
MENSAJE_TRANSICION_INVALIDA = (
    "No se puede {accion} la orden {orden_id}: está {estado} y debe estar {origen}"
)
MENSAJE_CATALOGO_SIN_ESTADO = "El catálogo de estados no tiene el estado {estado}"
MENSAJE_AVISO = "Aviso simulado al cliente: la orden #{orden_id} del vehículo {patente} está terminada"

DEMORA_AVISO_SEGUNDOS = 0.5
# Hereda el nivel INFO y la salida de consola que uvicorn ya configura para `uvicorn.error`, así el
# aviso sale en el registro sin tocar `main.py` ni `core` (S-13).
logger_avisos = logging.getLogger("uvicorn.error.avisos")


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


# -- Transiciones: auxiliares comunes (C-14) --------------------------------------------------


async def _bloquear_orden(uow: OrdenesUoW, orden_id: int) -> OrdenTrabajo:
    """Paso 1 del orden global de bloqueo: la orden `FOR UPDATE`, siempre la PRIMERA sentencia con
    bloqueo de una transición. 404 si no existe (se decide antes que el permiso, S-07)."""
    orden = await uow.ordenes.get_para_actualizar(orden_id)
    if orden is None:
        raise NoEncontrado(MENSAJE_ORDEN_INEXISTENTE)
    return orden


async def _roles_vigentes(uow: OrdenesUoW, usuario_id: int) -> frozenset[str]:
    """Roles vigentes del actor leídos en la base, en la misma transacción (RN04, S-03)."""
    return frozenset(await uow.asignaciones.roles_vigentes(usuario_id, datetime.now(UTC)))


async def _exigir_transicion(uow: OrdenesUoW, orden: OrdenTrabajo, destino: CodigoEstado) -> None:
    """Reglas de estado guiadas por el catálogo (una consulta) más la tabla `ORIGEN` (S-10).

    1) Un estado actual final (`es_final`) no admite más cambios, cualquiera sea el destino.
    2) Cada destino tiene un único origen. 3) El destino tiene que existir en el catálogo (RN19).
    """
    catalogo = {e.codigo: e for e in await uow.estados.listar()}
    actual = catalogo.get(orden.estado)  # existe siempre: la FK al catálogo es NO ACTION
    if actual is not None and actual.es_final:
        raise Conflicto(MENSAJE_ESTADO_FINAL.format(orden_id=orden.id, estado=orden.estado))
    origen = ORIGEN[destino]
    if orden.estado != origen.value:
        raise Conflicto(
            MENSAJE_TRANSICION_INVALIDA.format(
                accion=ACCION[destino],
                orden_id=orden.id,
                estado=orden.estado,
                origen=origen.value,
            )
        )
    if destino.value not in catalogo:
        raise Conflicto(MENSAJE_CATALOGO_SIN_ESTADO.format(estado=destino.value))


async def _aplicar_transicion(
    uow: OrdenesUoW,
    orden: OrdenTrabajo,
    destino: CodigoEstado,
    usuario_id: int,
    *,
    mecanico_id: int | None = None,
) -> OrdenDetalleSalida:
    """Cambia el estado, agrega la línea de historial (RN15, sólo agregado) y relee todo.

    `mecanico_id` sólo lo fija `iniciar` (el actor); `terminar` y `cancelar` no lo tocan (S-05).
    La salida se arma con `get_detalle` (relee con `populate_existing`), dentro del bloque del
    llamador y nunca con valores de entidades leídas antes de escribir.
    """
    assert orden.id is not None
    desde = orden.estado
    cambios: dict[str, object] = {"estado": destino.value}
    if mecanico_id is not None:
        cambios["mecanico_id"] = mecanico_id
    await uow.ordenes.update(orden, cambios)
    await uow.historial.add(
        HistorialEstadoOrden(
            orden_id=orden.id,
            desde_estado=desde,
            hasta_estado=destino.value,
            usuario_id=usuario_id,
            cuando=datetime.now(UTC),
        )
    )
    detalle = await uow.ordenes.get_detalle(orden.id)
    assert detalle is not None
    return armar_detalle(detalle)


def _traducir_catalogo(exc: IntegrityError, destino: CodigoEstado) -> None:
    """Se llama FUERA del bloque. Si alguien sacó el estado destino del catálogo por `psql` entre la
    verificación y el `UPDATE`, la FK rechaza la escritura: se traduce al mismo 409 de catálogo.
    Cualquier otra restricción sigue su camino (manejador global)."""
    if restriccion_violada(exc) in RESTRICCIONES_DE_ESTADO:
        raise Conflicto(MENSAJE_CATALOGO_SIN_ESTADO.format(estado=destino.value)) from None


# -- Transiciones (C-14) -----------------------------------------------------------------------


async def iniciar(uow: OrdenesUoW, orden_id: int, usuario_id: int) -> OrdenDetalleSalida:
    """PENDIENTE -> EN_REPARACION; el actor queda como mecánico asignado (RN11, S-05).

    El rol MECANICO lo exige el router con `requiere_rol` (antes de buscar la orden); acá no hay
    permiso por relación. Una orden ya iniciada (propia o de otro mecánico) da 409 sin reasignar.
    """
    destino = CodigoEstado.EN_REPARACION
    try:
        async with uow:
            orden = await _bloquear_orden(uow, orden_id)  # paso 1 — 404
            await _exigir_transicion(uow, orden, destino)  # 409
            salida = await _aplicar_transicion(
                uow, orden, destino, usuario_id, mecanico_id=usuario_id
            )
    except IntegrityError as exc:
        _traducir_catalogo(exc, destino)
        raise
    return salida


async def cancelar(uow: OrdenesUoW, orden_id: int, usuario_id: int) -> OrdenDetalleSalida:
    """PENDIENTE -> CANCELADA por la recepción, la administración o el dueño del vehículo (RN12).

    Orden de los rechazos: 404 (orden inexistente) -> 403 (ni RECEPCION/ADMIN vigente, ni dueño;
    S-07, antes que el estado, RN12) -> 409 (estado). El dueño es el usuario de la ficha del
    cliente del vehículo, también si el vehículo está dado de baja (S-08); una ficha sin usuario no
    tiene dueño que cancele. Cancelar no mueve stock (el alta nunca lo descontó, RN14) y no toca
    `mecanico_id`.
    """
    destino = CodigoEstado.CANCELADA
    try:
        async with uow:
            orden = await _bloquear_orden(uow, orden_id)  # paso 1 — 404
            roles = await _roles_vigentes(uow, usuario_id)
            es_personal = not roles.isdisjoint(ROLES_QUE_CANCELAN)
            # el personal no necesita más consultas; el resto tiene que ser el dueño
            if not es_personal and await uow.ordenes.get_usuario_dueno(orden_id) != usuario_id:
                raise SinPermiso(MENSAJE_SIN_PERMISO_CANCELAR)  # 403 antes que 409
            await _exigir_transicion(uow, orden, destino)  # 409
            salida = await _aplicar_transicion(uow, orden, destino, usuario_id)
    except IntegrityError as exc:
        _traducir_catalogo(exc, destino)
        raise
    return salida


async def terminar(uow: OrdenesUoW, orden_id: int, usuario_id: int) -> OrdenDetalleSalida:
    """EN_REPARACION -> TERMINADA: descuenta el stock de cada ítem y deja todo o nada (RN13, RN14).

    Orden de los rechazos: 404 -> 403 (ni el mecánico asignado con MECANICO vigente, ni ADMIN;
    antes que el estado, S-04/S-06) -> 409 de estado -> 409 de stock. Stock, movimientos, estado e
    historial se escriben en la MISMA transacción: si falta stock (o falla cualquier otra cosa), la
    excepción sale del bloque y el Unit of Work revierte TODO, también los descuentos de los ítems
    anteriores. `StockInsuficiente` no se captura (su mensaje de C-11 ya es el del PDF).

    El descuento es sólo por el punto único de escritura de stock, con `incluir_bajas=True`: un
    repuesto dado de baja después del alta se descuenta igual (S-11, RN16). El movimiento lo firma
    el actor que terminó (el mecánico o el ADMIN), con el motivo `Orden #<id> terminada` (S-12).
    El aviso al cliente NO se agenda acá: lo agenda el router cuando este servicio vuelve (commit).
    """
    destino = CodigoEstado.TERMINADA
    try:
        async with uow:
            orden = await _bloquear_orden(uow, orden_id)  # paso 1 — 404
            roles = await _roles_vigentes(uow, usuario_id)
            asignado = orden.mecanico_id == usuario_id and Rol.MECANICO.value in roles
            if not (asignado or Rol.ADMIN.value in roles):
                raise SinPermiso(MENSAJE_SIN_PERMISO_TERMINAR)  # 403 antes que 409
            await _exigir_transicion(uow, orden, destino)  # 409 de estado
            assert orden.id is not None
            items = await uow.items.listar_de_orden(orden.id)
            if items:  # siempre >= 1 (C-13); defensivo ante una orden cargada por psql
                await aplicar_movimientos_stock(  # paso 3 — PUNTO ÚNICO de escritura de stock
                    uow,
                    [
                        MovimientoPedido(
                            i.repuesto_id,
                            -i.cantidad,
                            MOTIVO_ORDEN_TERMINADA.format(orden_id=orden.id),
                            orden_id=orden.id,
                        )
                        for i in items
                    ],
                    usuario_id=usuario_id,
                    incluir_bajas=True,
                )  # `StockInsuficiente` NO se captura
            salida = await _aplicar_transicion(uow, orden, destino, usuario_id)
    except IntegrityError as exc:
        _traducir_catalogo(exc, destino)
        raise
    return salida  # confirmado


async def avisar_orden_terminada(orden_id: int, patente: str) -> None:
    """Aviso SIMULADO al cliente (DD-10): lo corre `BackgroundTasks` DESPUÉS de enviar la respuesta
    y sólo si `terminar` confirmó. Recibe valores (nunca entidades ni la sesión, ya cerrada); la
    línea no lleva nombre, correo ni teléfono del cliente. `asyncio.sleep`, nunca `time.sleep`."""
    await asyncio.sleep(DEMORA_AVISO_SEGUNDOS)
    logger_avisos.info(MENSAJE_AVISO.format(orden_id=orden_id, patente=patente))
