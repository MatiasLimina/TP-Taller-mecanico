"""Contratos del módulo clientes (C-10): alta de ficha, alta de vehículo y sus salidas.

- `ClienteAltaEntrada` reutiliza `Nombre`, `Documento` y `Telefono` del registro (S-11): el
  documento se recorta igual en los dos caminos, y eso importa para `uq_cliente_documento`.
  No acepta `usuario_id`: la ficha de recepción nace sin cuenta (S-04, `extra="forbid"`).
- `VehiculoAltaEntrada` normaliza la patente (S-09): sin espacios ni guiones, en mayúsculas y
  con 6 a 8 letras o dígitos, así `ab123cd`, `AB 123 CD` y `AB-123-CD` chocan como la misma
  patente en el índice único parcial. `anio` se valida acá (S-10) con las mismas constantes
  que `ck_vehiculo_anio_rango` (el CHECK queda de respaldo); marca y modelo, 1 a 50
  caracteres tras recortar (S-13). No acepta `cliente_id`: sale de la ruta.
- Las salidas heredan `SalidaBase` y no llevan `borrado_en` (toda ruta devuelve sólo
  vehículos vigentes) ni nada de la cuenta del usuario.
"""

import re
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from app.core.schemas import EntradaBase, SalidaBase
from app.modules.usuarios.schemas import Documento, Nombre, Telefono

ANIO_MINIMO = 1950
ANIO_MAXIMO = 2100
MAX_CARACTERES_MARCA_MODELO = 50
PATRON_PATENTE = re.compile(r"[A-Z0-9]{6,8}")
MENSAJE_PATENTE_INVALIDA = (
    "La patente debe tener de 6 a 8 letras o dígitos, sin contar espacios ni guiones"
)


def _normalizar_patente(valor: str) -> str:
    patente = "".join(valor.split()).replace("-", "").upper()
    if PATRON_PATENTE.fullmatch(patente) is None:
        raise ValueError(MENSAJE_PATENTE_INVALIDA)
    return patente


Patente = Annotated[str, AfterValidator(_normalizar_patente)]
Marca = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CARACTERES_MARCA_MODELO),
]
Modelo = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CARACTERES_MARCA_MODELO),
]
Anio = Annotated[int, Field(ge=ANIO_MINIMO, le=ANIO_MAXIMO)]


class ClienteAltaEntrada(EntradaBase):
    nombre: Nombre
    documento: Documento
    telefono: Telefono


class VehiculoAltaEntrada(EntradaBase):
    patente: Patente
    marca: Marca
    modelo: Modelo
    anio: Anio


class VehiculoSalida(SalidaBase):
    id: int
    cliente_id: int
    patente: str
    marca: str
    modelo: str
    anio: int


class ClienteSalida(SalidaBase):
    id: int
    usuario_id: int | None
    nombre: str
    documento: str
    telefono: str


class ClienteDetalleSalida(ClienteSalida):
    vehiculos: list[VehiculoSalida]
