"""Contratos de entrada y salida del módulo usuarios: registro, login y logout (C-07).

Entradas (heredan `EntradaBase`: un campo no declarado da 422):

- El correo se recorta, se valida como dirección y se pasa a minúsculas, en el registro Y en el
  login (S-01): así `uq_usuario_email` y el conteo de intentos son insensibles a mayúsculas sin
  índice funcional ni migración.
- La contraseña se valida en BYTES UTF-8 (bcrypt trunca en 72 bytes). El mínimo de 8 caracteres
  es una constante fija del registro; el login NUNCA lo aplica (S-02), así que no filtra la
  política a quien prueba credenciales.
- `nombre`, `documento` y `telefono` se recortan y deben quedar con 1..N caracteres tras el
  recorte (S-03). El recorte importa para la unicidad: `uq_cliente_documento` compara el texto
  exacto. Los largos máximos viven sólo acá; no hay validación de formato propio.

Salidas (heredan `SalidaBase`): nunca exponen el hash de la contraseña ni un token.
"""

from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, EmailStr, Field, StringConstraints

from app.core.schemas import EntradaBase, SalidaBase
from app.core.security import MAX_BYTES_BCRYPT

MIN_CARACTERES_PASSWORD = 8  # constante fija del registro (S-02); el login no la aplica
MAX_CARACTERES_EMAIL = 254


def _recortar(valor: object) -> object:
    return valor.strip() if isinstance(valor, str) else valor


def _normalizar_correo(valor: str) -> str:
    correo = valor.lower()
    if len(correo) > MAX_CARACTERES_EMAIL:
        raise ValueError(f"El correo no puede superar {MAX_CARACTERES_EMAIL} caracteres")
    return correo


def _limitar_bytes_password(valor: str) -> str:
    try:
        largo = len(valor.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValueError("La contraseña no se puede codificar en UTF-8") from None
    if largo > MAX_BYTES_BCRYPT:
        raise ValueError(f"La contraseña no puede superar {MAX_BYTES_BCRYPT} bytes en UTF-8")
    return valor


CorreoNormalizado = Annotated[
    EmailStr, BeforeValidator(_recortar), AfterValidator(_normalizar_correo)
]
PasswordRegistro = Annotated[
    str, Field(min_length=MIN_CARACTERES_PASSWORD), AfterValidator(_limitar_bytes_password)
]
PasswordLogin = Annotated[str, Field(min_length=1), AfterValidator(_limitar_bytes_password)]
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Documento = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Telefono = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]


class RegistroEntrada(EntradaBase):
    email: CorreoNormalizado
    password: PasswordRegistro
    nombre: Nombre
    documento: Documento
    telefono: Telefono


class LoginEntrada(EntradaBase):
    email: CorreoNormalizado
    password: PasswordLogin


class ClienteRegistradoSalida(SalidaBase):
    id: int
    nombre: str
    documento: str
    telefono: str


class RegistroSalida(SalidaBase):
    id: int
    email: str
    nombre: str
    cliente: ClienteRegistradoSalida


class LoginSalida(SalidaBase):
    mensaje: str
    debe_cambiar_password: bool
    expira_en_segundos: int


class MensajeSalida(SalidaBase):
    mensaje: str
