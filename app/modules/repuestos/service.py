"""Servicio de repuestos (C-11): catálogo y PUNTO ÚNICO DE ESCRITURA DE STOCK (RN14).

Los servicios no conocen HTTP: lanzan errores de aplicación (`app/core/errores.py`). El router
construye el Unit of Work y el servicio lo abre con `async with`.

Punto único (design C-11 D4): `aplicar_movimientos_stock` es el único código de `app/` que
escribe `repuesto.stock` (vía `RepuestoRepository.sumar_stock`) e inserta en `movimiento_stock`.
Se llama DENTRO de un Unit of Work ya abierto por el servicio que lo usa (repuestos u órdenes),
nunca abre ni confirma, y aplica los pedidos en orden ascendente de `repuesto_id` para que dos
transacciones con los mismos repuestos no se interbloqueen.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.errores import Conflicto, NoEncontrado, restriccion_violada
from app.core.paginacion import Pagina, Paginacion, armar_pagina, verificar_pagina
from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)
from app.modules.repuestos.repository import (
    MovimientoStockRepository,
    RepuestoRepository,
)
from app.modules.repuestos.schemas import (
    RepuestoAltaEntrada,
    RepuestoEdicionEntrada,
    RepuestoSalida,
)
from app.modules.repuestos.unit_of_work import RepuestosUoW

MOTIVO_STOCK_INICIAL = "Stock inicial"  # mismo texto que seed.py (C-06)

MENSAJE_REPUESTO_INEXISTENTE = "El repuesto no existe"
MENSAJE_CODIGO_REPETIDO = "Ya existe un repuesto vigente con el código {codigo}"
MENSAJE_STOCK_INSUFICIENTE = (
    "Stock insuficiente para el repuesto {codigo}: hay {disponible} y se necesitan {requerido}"
)


@dataclass(frozen=True, slots=True)
class MovimientoPedido:
    repuesto_id: int
    cantidad: int  # con signo y distinta de 0: positivo entra, negativo sale
    motivo: str
    orden_id: int | None = None  # C-14: la orden que termina


class StockInsuficiente(Conflicto):
    """409 por el manejador global. C-14 puede capturarla FUERA del bloque para un mensaje propio."""

    def __init__(self, codigo: str, disponible: int, requerido: int) -> None:
        super().__init__(
            MENSAJE_STOCK_INSUFICIENTE.format(
                codigo=codigo, disponible=disponible, requerido=requerido
            )
        )
        self.codigo = codigo
        self.disponible = disponible
        self.requerido = requerido


class ConStock(Protocol):
    """Lo cumplen `RepuestosUoW` y el `OrdenesUoW` de C-13/C-14 (misma sesión, sin anidar)."""

    repuestos: RepuestoRepository
    movimientos: MovimientoStockRepository


def _validar_pedidos(movimientos: Sequence[MovimientoPedido]) -> None:
    """Errores de programación (`ValueError`), nunca del cliente: los contratos ya los filtran.

    Rechaza: lista vacía, `cantidad == 0`, `motivo` vacío tras `strip()` y el mismo
    `repuesto_id` dos veces en una llamada.
    """
    if not movimientos:
        raise ValueError("aplicar_movimientos_stock sin movimientos")
    vistos: set[int] = set()
    for pedido in movimientos:
        if pedido.cantidad == 0:
            raise ValueError(f"Movimiento con cantidad 0 para el repuesto {pedido.repuesto_id}")
        if not pedido.motivo.strip():
            raise ValueError(f"Movimiento sin motivo para el repuesto {pedido.repuesto_id}")
        if pedido.repuesto_id in vistos:
            raise ValueError(f"Repuesto {pedido.repuesto_id} repetido en la misma llamada")
        vistos.add(pedido.repuesto_id)


async def aplicar_movimientos_stock(
    uow: ConStock,
    movimientos: Sequence[MovimientoPedido],
    *,
    usuario_id: int,
    incluir_bajas: bool = False,
) -> dict[int, int]:
    """PUNTO ÚNICO DE ESCRITURA DE STOCK (RN14). Contrato completo en design C-11 D4.

    Se llama DENTRO de un `async with uow` que abrió el servicio llamador; nunca abre,
    confirma ni revierte. Si lanza (`NoEncontrado`, `StockInsuficiente`), el llamador NO la
    captura dentro del bloque: sale y el UoW revierte TODO (stock, movimientos y cualquier otra
    escritura de esa transacción). Un llamador que además bloquee otras filas (C-14: la orden)
    las bloquea ANTES de llamar. `incluir_bajas=True` sólo lo usa C-14 (S-11).

    Devuelve `{repuesto_id: stock_resultante}`. Usar ese valor y no `repuesto.stock` de una
    entidad ya cargada, que queda vieja (`synchronize_session=False`).
    """
    _validar_pedidos(movimientos)
    resultado: dict[int, int] = {}
    for pedido in sorted(movimientos, key=lambda m: m.repuesto_id):  # orden de bloqueo fijo
        stock = await uow.repuestos.sumar_stock(
            pedido.repuesto_id, pedido.cantidad, incluir_bajas=incluir_bajas
        )
        if stock is None:
            fila = await uow.repuestos.leer_stock(pedido.repuesto_id)
            if fila is None or (fila.borrado_en is not None and not incluir_bajas):
                raise NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)
            raise StockInsuficiente(fila.codigo, fila.stock, -pedido.cantidad)
        await uow.movimientos.add(
            MovimientoStock(
                repuesto_id=pedido.repuesto_id,
                orden_id=pedido.orden_id,
                usuario_id=usuario_id,
                cantidad=pedido.cantidad,
                motivo=pedido.motivo,
            )
        )
        resultado[pedido.repuesto_id] = stock
    return resultado


async def listar(uow: RepuestosUoW, pag: Paginacion, q: str | None) -> Pagina[RepuestoSalida]:
    """Catálogo vigente paginado, en orden de id; `q` busca en descripción o código (S-08).

    `q` se recorta y, si queda vacío, no filtra. Contar primero evita traer filas de una página
    que da 422 (`verificar_pagina`).
    """
    if q is not None:
        q = q.strip() or None
    async with uow:
        total = await uow.repuestos.contar(q)
        verificar_pagina(pag, total)
        repuestos = await uow.repuestos.listar(q, offset=pag.offset, limit=pag.size)
        items = [RepuestoSalida.model_validate(repuesto) for repuesto in repuestos]
    return armar_pagina(items, total, pag)


async def detalle(uow: RepuestosUoW, repuesto_id: int) -> RepuestoSalida:
    """Un repuesto vigente; uno dado de baja responde igual que uno inexistente (RN16)."""
    async with uow:
        repuesto = await uow.repuestos.get_by_id(repuesto_id)
        if repuesto is None:
            raise NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)
        salida = RepuestoSalida.model_validate(repuesto)
    return salida


async def alta(uow: RepuestosUoW, datos: RepuestoAltaEntrada, usuario_id: int) -> RepuestoSalida:
    """Alta de un repuesto con su stock inicial, todo o nada (C-11, D6).

    El repuesto nace con stock 0 y el stock inicial entra por el punto único (RN14): el
    `INSERT` nunca fija stock. Con `stock_inicial` 0 no hay movimiento. La unicidad del código
    la decide `uq_repuesto_codigo` (RN01, sin consulta previa; también con altas simultáneas) y
    se traduce fuera del bloque, con el código del DTO y no el de la entidad.
    """
    try:
        async with uow:
            repuesto = await uow.repuestos.add(
                Repuesto(
                    codigo=datos.codigo, descripcion=datos.descripcion, precio=datos.precio
                )
            )
            assert repuesto.id is not None
            stock = 0
            if datos.stock_inicial > 0:
                stock = (
                    await aplicar_movimientos_stock(
                        uow,
                        [MovimientoPedido(repuesto.id, datos.stock_inicial, MOTIVO_STOCK_INICIAL)],
                        usuario_id=usuario_id,
                    )
                )[repuesto.id]
            # El stock devuelto por el punto único, no el atributo de la entidad (que queda viejo).
            salida = RepuestoSalida(
                id=repuesto.id,
                codigo=repuesto.codigo,
                descripcion=repuesto.descripcion,
                precio=repuesto.precio,
                stock=stock,
            )
    except IntegrityError as exc:
        if restriccion_violada(exc) == "uq_repuesto_codigo":
            raise Conflicto(MENSAJE_CODIGO_REPETIDO.format(codigo=datos.codigo)) from None
        raise
    return salida


async def editar(
    uow: RepuestosUoW, repuesto_id: int, datos: RepuestoEdicionEntrada, usuario_id: int
) -> RepuestoSalida:
    """Edita descripción y/o precio; un cambio de precio deja su línea de historial (RN20, S-03).

    El repuesto se bloquea con `FOR UPDATE`: dos cambios de precio simultáneos quedan encadenados
    (el segundo lee el precio que confirmó el primero) y una baja simultánea da 404. `{}` o el
    mismo precio no cambian nada ni dejan historial (S-12).
    """
    async with uow:
        repuesto = await uow.repuestos.get_vigente_para_actualizar(repuesto_id)
        if repuesto is None:
            raise NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)
        cambios = datos.model_dump(exclude_unset=True)
        precio_anterior = repuesto.precio
        if "precio" in cambios and cambios["precio"] == precio_anterior:
            del cambios["precio"]  # mismo precio: sin línea (el CHECK precio_distinto es la red)
        if cambios:
            await uow.repuestos.update(repuesto, cambios)
        if "precio" in cambios:
            assert repuesto.id is not None
            await uow.historial_precios.add(
                HistorialPrecioRepuesto(
                    repuesto_id=repuesto.id,
                    usuario_id=usuario_id,
                    precio_anterior=precio_anterior,
                    precio_nuevo=cambios["precio"],
                )
            )
        salida = RepuestoSalida.model_validate(repuesto)
    return salida


async def baja(uow: RepuestosUoW, repuesto_id: int) -> None:
    """Baja lógica (RN16): conserva stock, movimientos e historial y libera el código (S-11)."""
    async with uow:
        repuesto = await uow.repuestos.get_vigente_para_actualizar(repuesto_id)
        if repuesto is None:
            raise NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)
        await uow.repuestos.soft_delete(repuesto)
