"""Contratos de entrada y salida del módulo órdenes (C-13): alta de una orden y catálogo de estados.

Entrada del alta (heredan `EntradaBase`: un campo no declarado da 422, y por eso nadie puede fijar
`precio`, `precio_unitario`, `total`, `estado`, `creada_en` ni `mecanico_id`: RN10, el servidor los
calcula, copia o decide; tampoco dentro de un ítem):

- `vehiculo_id` y `repuesto_id` (S-07): enteros de 1 a `INT4_MAX`; uno mayor daría un error de la
  base en lugar de un 422 limpio.
- `falla` (S-06): se recorta y debe quedar con 1 a 500 caracteres (la columna no tiene largo).
- `items` (S-07): de 1 a 50 ítems; `cantidad` entera de 1 a 1000. Se guardan y se devuelven en el
  orden del cuerpo.
- Repuesto repetido (S-08): 422 sobre `["body", "items"]` con los ids repetidos. El validador corre
  después de validar cada ítem: un ítem inválido da su propio error y no se evalúan repetidos.

Salida (heredan `SalidaBase`): `OrdenDetalleSalida` tiene la forma y el orden de campos del
ejemplo de la consigna (S-05) y la reutilizan el alta y, en C-15, `GET /ordenes/{id}`. Los
`Decimal` salen como texto (`"68000.00"`, Pydantic v2), igual que `RepuestoSalida.precio`.
`EstadoOrdenSalida` es una fila del catálogo (S-14). Las clases anidadas se definen antes.

`OrdenResumenSalida` (C-15) es un elemento de `GET /ordenes` y `GET /mis-ordenes`: la cabecera del detalle, sin ítems ni historial; lo arma `service.armar_resumen` desde una orden con el vehículo y su cliente precargados.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from app.core.schemas import INT4_MAX, EntradaBase, SalidaBase

CANTIDAD_MAXIMA_ITEMS = 50
CANTIDAD_MAXIMA_POR_ITEM = 1_000
LARGO_MAXIMO_FALLA = 500

IdEntidad = Annotated[int, Field(ge=1, le=INT4_MAX)]
Falla = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LARGO_MAXIMO_FALLA)
]
Cantidad = Annotated[int, Field(ge=1, le=CANTIDAD_MAXIMA_POR_ITEM)]


class ItemAltaEntrada(EntradaBase):
    repuesto_id: IdEntidad
    cantidad: Cantidad


class OrdenAltaEntrada(EntradaBase):
    vehiculo_id: IdEntidad
    falla: Falla
    items: Annotated[
        list[ItemAltaEntrada], Field(min_length=1, max_length=CANTIDAD_MAXIMA_ITEMS)
    ]

    @field_validator("items")
    @classmethod
    def _sin_repetidos(cls, items: list[ItemAltaEntrada]) -> list[ItemAltaEntrada]:
        vistos: set[int] = set()
        repetidos: set[int] = set()
        for item in items:
            (repetidos if item.repuesto_id in vistos else vistos).add(item.repuesto_id)
        if repetidos:
            ids = ", ".join(map(str, sorted(repetidos)))
            raise ValueError(f"Hay repuestos repetidos en la orden: {ids}")
        return items


class ItemOrdenSalida(SalidaBase):
    repuesto_id: int
    codigo: str
    descripcion: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal


class HistorialEstadoSalida(SalidaBase):
    desde_estado: str | None
    hasta_estado: str
    usuario_id: int
    cuando: datetime


class OrdenDetalleSalida(SalidaBase):
    id: int
    estado: str
    patente: str
    total: Decimal
    creada_en: datetime
    mecanico_id: int | None
    falla: str
    cliente: str
    items: list[ItemOrdenSalida]
    historial: list[HistorialEstadoSalida]


class EstadoOrdenSalida(SalidaBase):
    codigo: str
    descripcion: str
    posicion: int
    es_final: bool


class OrdenResumenSalida(SalidaBase):
    id: int
    estado: str
    patente: str
    total: Decimal
    creada_en: datetime
    mecanico_id: int | None
    falla: str
    cliente: str
