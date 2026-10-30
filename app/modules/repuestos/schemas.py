"""Contratos de entrada y salida del módulo repuestos (C-11): alta, edición y salida del catálogo.

Entradas (heredan `EntradaBase`: un campo no declarado da 422, y por eso `stock` no se puede
fijar por el alta ni por el PATCH: RN14, el stock sólo cambia por el punto único de escritura):

- Código (S-05): se recorta y se pasa a mayúsculas ANTES de validar; 1 a 30 caracteres con la
  forma `AAA-BBB-01` (letras mayúsculas y dígitos separados por guiones simples). Así `fil-ace-01`
  y `FIL-ACE-01` son el mismo repuesto para `uq_repuesto_codigo`. El código no se edita: no está
  en el contrato del PATCH.
- Precio (S-06): `Decimal` mayor que 0, hasta 10 dígitos y 2 decimales (= `NUMERIC(10, 2)`),
  cuantizado a centavos. Se acepta como número o como texto JSON y se devuelve como texto
  (`"8500.00"`, como el ejemplo de la consigna). Nunca `float`; `NaN` e infinitos se rechazan.
- Descripción (S-07): se recorta y debe quedar con 1 a 200 caracteres. Sin unicidad.
- `stock_inicial` (S-04): entero de 0 a 100 000 (`CANTIDAD_MAXIMA_MOVIMIENTO`, tope por
  movimiento que C-12 reutiliza en `reponer`); opcional, 0 por defecto (con 0 no hay movimiento).
- PATCH (S-12): todos los campos son opcionales. `{}` es válido y no cambia nada; un campo
  presente con `null` es 422 sobre ese campo; el servicio usa `model_dump(exclude_unset=True)`
  para saber qué vino.

Salida (hereda `SalidaBase`): exactamente `id`, `codigo`, `descripcion`, `precio` y `stock`.
`borrado_en` nunca se expone.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    StringConstraints,
    field_validator,
)

from app.core.schemas import EntradaBase, SalidaBase

LARGO_MAXIMO_CODIGO = 30
LARGO_MAXIMO_DESCRIPCION = 200
LARGO_MAXIMO_BUSQUEDA = 100
CANTIDAD_MAXIMA_MOVIMIENTO = 100_000  # tope por movimiento; C-12 lo reutiliza en `reponer`
PATRON_CODIGO = r"^[A-Z0-9]+(-[A-Z0-9]+)*$"  # FIL-ACE-01, BUJ-01, ACE-5W30-1L, FRE-010
CENTAVO = Decimal("0.01")


def _a_centavos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO)  # 8500 -> 8500.00: la salida del alta = la del GET


def _normalizar_codigo(valor: object) -> object:
    # `StringConstraints(to_upper=True)` pasa a mayúsculas DESPUÉS de comprobar el patrón, así que
    # `fil-ace-01` se rechazaría: se normaliza antes de validar largo y patrón.
    return valor.strip().upper() if isinstance(valor, str) else valor


Codigo = Annotated[
    str,
    BeforeValidator(_normalizar_codigo),
    StringConstraints(min_length=1, max_length=LARGO_MAXIMO_CODIGO, pattern=PATRON_CODIGO),
]
Descripcion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=LARGO_MAXIMO_DESCRIPCION),
]
Precio = Annotated[
    Decimal, Field(gt=0, max_digits=10, decimal_places=2), AfterValidator(_a_centavos)
]
CantidadInicial = Annotated[int, Field(ge=0, le=CANTIDAD_MAXIMA_MOVIMIENTO)]


class RepuestoAltaEntrada(EntradaBase):
    codigo: Codigo
    descripcion: Descripcion
    precio: Precio
    stock_inicial: CantidadInicial = 0


class RepuestoEdicionEntrada(EntradaBase):
    descripcion: Descripcion | None = None
    precio: Precio | None = None

    @field_validator("descripcion", "precio", mode="before")
    @classmethod
    def _no_nulo(cls, valor: object) -> object:
        # Sólo corre si el campo vino en el cuerpo: `null` explícito -> 422 sobre ese campo;
        # ausente -> no está en model_fields_set y `exclude_unset` lo omite.
        if valor is None:
            raise ValueError("El campo no puede ser nulo")
        return valor


class RepuestoSalida(SalidaBase):
    id: int
    codigo: str
    descripcion: str
    precio: Decimal  # Pydantic v2 lo serializa como texto: "8500.00"
    stock: int
