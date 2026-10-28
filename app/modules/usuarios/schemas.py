"""Contratos de entrada y salida del módulo usuarios: registro, login, logout (C-07), perfil
de sesión y cambio de contraseña (C-08), alta de personal, roles y eventos de seguridad (C-09).

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

- Cambio de contraseña (C-08, S-01): `password_actual` sigue la regla del login (1 carácter a
  72 bytes, sin mínimo) y `password_nueva` la del registro (8 caracteres a 72 bytes); la nueva
  debe ser distinta de la actual (422).

- Alta de personal (C-09, S-01): `password_provisoria` sigue la regla del registro; el cuerpo no
  admite rol ni `debe_cambiar_password` (el servicio fija la bandera en verdadero).
- Asignación de rol (C-09, S-04): `vence_en` debe traer zona horaria y ser futuro; se valida en
  el contrato (422 por campo, no 409) y se guarda en UTC.

Salidas (heredan `SalidaBase`): nunca exponen el hash de la contraseña, la provisoria ni un token.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BeforeValidator,
    EmailStr,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.schemas import EntradaBase, SalidaBase
from app.core.security import MAX_BYTES_BCRYPT
from app.modules.usuarios.models import Rol

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


def _vencimiento_valido(valor: datetime) -> datetime:
    if valor.tzinfo is None or valor.utcoffset() is None:
        raise ValueError("El vencimiento debe indicar la zona horaria")
    if valor <= datetime.now(UTC):
        raise ValueError("El vencimiento debe ser una fecha futura")
    try:
        return valor.astimezone(UTC)
    except OverflowError:
        # Año 9999 con un huso negativo: la conversión a UTC se sale del rango de `datetime`.
        raise ValueError("El vencimiento está fuera del rango admitido") from None


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
Vencimiento = Annotated[datetime, AfterValidator(_vencimiento_valido)]


class RegistroEntrada(EntradaBase):
    email: CorreoNormalizado
    password: PasswordRegistro
    nombre: Nombre
    documento: Documento
    telefono: Telefono


class LoginEntrada(EntradaBase):
    email: CorreoNormalizado
    password: PasswordLogin


class CambioPasswordEntrada(EntradaBase):
    password_actual: PasswordLogin
    password_nueva: PasswordRegistro

    @model_validator(mode="after")
    def _nueva_distinta_de_la_actual(self) -> "CambioPasswordEntrada":
        if self.password_nueva == self.password_actual:
            raise ValueError("La contraseña nueva debe ser distinta de la actual")
        return self


class PersonalAltaEntrada(EntradaBase):
    email: CorreoNormalizado
    nombre: Nombre
    password_provisoria: PasswordRegistro


class AsignacionRolEntrada(EntradaBase):
    rol: Rol
    vence_en: Vencimiento | None = None


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


class PerfilSalida(SalidaBase):
    """`roles_vigentes` sale de la base en esta petición; `roles_token` es lo que dice el token."""

    id: int
    email: str
    nombre: str
    debe_cambiar_password: bool
    roles_vigentes: list[str]
    roles_token: list[str]


class PersonalSalida(SalidaBase):
    id: int
    email: str
    nombre: str
    activo: bool
    debe_cambiar_password: bool


class AsignacionSalida(SalidaBase):
    """Una fila de `asignacion_rol`; `vigente` lo calcula el servicio a la hora de la petición."""

    id: int
    usuario_id: int
    rol: str
    desde: datetime
    vence_en: datetime | None
    revocada_en: datetime | None
    otorgada_por: int | None
    vigente: bool


class RolesUsuarioSalida(SalidaBase):
    usuario_id: int
    email: str
    nombre: str
    roles_vigentes: list[str]
    asignaciones: list[AsignacionSalida]


class EventoSalida(SalidaBase):
    id: int
    cuando: datetime
    actor: str
    accion: str
