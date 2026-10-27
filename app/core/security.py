"""Primitivas de seguridad del proceso (C-05).

Contrato público:
- `hash_password(password)` y `verify_password(password, password_hash)`: bcrypt
  con sal aleatoria y costo `BCRYPT_COST`, ejecutado en `asyncio.to_thread` bajo
  un semáforo de `BCRYPT_MAX_CONCURRENCY` operaciones simultáneas. Una contraseña
  de más de `MAX_BYTES_BCRYPT` bytes UTF-8 se rechaza con `PasswordInvalidaError`
  antes de invocar bcrypt y sin truncarla. En el login (C-07) el DTO rechaza con
  422 una contraseña de más de 72 bytes antes de llegar al servicio; si igual
  llegara, el servicio traduce este error al 401 genérico, nunca a un 500.
- `crear_token_acceso(usuario_id, roles)` y `decodificar_token_acceso(token)`:
  JWT HS256 con `SECRET_KEY`, claims `sub` (texto), `iat` (numérico con
  fracción de segundo), `exp` y `roles` (informativos). Token vencido, alterado,
  firmado con otra clave, con claims faltantes o con `sub` no numérico se
  rechaza con `TokenInvalidoError` de mensaje genérico.
- `aplicar_cookie_acceso(response, token)` y `eliminar_cookie_acceso(response)`:
  cookie `access_token` con HttpOnly, SameSite=Lax, Path=/, Max-Age igual a
  `ACCESS_TOKEN_EXPIRE_SECONDS` y Secure según `COOKIE_SECURE`.
- `crear_hash_ficticio()`: hash de una contraseña aleatoria, con el mismo costo
  que los hashes reales, para que el login de un correo inexistente cueste lo
  mismo (anti-enumeración).

Este módulo no lee `Authorization` ni recibe `Request`: el token viaja sólo en
la cookie y los errores no revelan el token, la clave ni el motivo interno.
"""

import asyncio
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import bcrypt
import jwt
from starlette.responses import Response

from app.core.config import get_settings

NOMBRE_COOKIE_ACCESO = "access_token"
ALGORITMO_JWT = "HS256"
MAX_BYTES_BCRYPT = 72

_MENSAJE_PASSWORD_INVALIDA = "La contraseña no cumple el contrato de seguridad."
_MENSAJE_TOKEN_INVALIDO = "El token de acceso no es válido."


class PasswordInvalidaError(ValueError):
    """La contraseña no se puede codificar en UTF-8 o supera los 72 bytes."""


class TokenInvalidoError(Exception):
    """El token de acceso no es válido; el mensaje nunca incluye detalles internos."""


@dataclass(frozen=True, slots=True)
class TokenAcceso:
    usuario_id: int
    iat: datetime
    exp: datetime
    roles: tuple[str, ...]


_semaforo_bcrypt: asyncio.Semaphore | None = None


def _semaforo() -> asyncio.Semaphore:
    # Perezoza a propósito: crear el semáforo al importar leería `Settings`
    # antes de tiempo y rompería "importar sin .env". La asignación ocurre sin
    # ningún `await` de por medio, así que no hay carrera.
    global _semaforo_bcrypt
    if _semaforo_bcrypt is None:
        _semaforo_bcrypt = asyncio.Semaphore(get_settings().bcrypt_max_concurrency)
    return _semaforo_bcrypt


def _validar_password(password: str) -> bytes:
    try:
        codificada = password.encode("utf-8")
    except UnicodeEncodeError:
        raise PasswordInvalidaError(_MENSAJE_PASSWORD_INVALIDA) from None
    if len(codificada) > MAX_BYTES_BCRYPT:
        raise PasswordInvalidaError(_MENSAJE_PASSWORD_INVALIDA)
    return codificada


def _hashear_bcrypt(password: bytes, costo: int) -> bytes:
    return bcrypt.hashpw(password, bcrypt.gensalt(rounds=costo))


def _verificar_bcrypt(password: bytes, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Un hash almacenado ilegible es una verificación fallida, no un 500.
        return False


async def hash_password(password: str) -> str:
    codificada = _validar_password(password)
    settings = get_settings()
    async with _semaforo():
        hasheada = await asyncio.to_thread(
            _hashear_bcrypt, codificada, settings.bcrypt_cost
        )
    return hasheada.decode()


async def verify_password(password: str, password_hash: str) -> bool:
    codificada = _validar_password(password)
    async with _semaforo():
        return await asyncio.to_thread(_verificar_bcrypt, codificada, password_hash)


def crear_token_acceso(
    usuario_id: int,
    roles: Iterable[str],
    *,
    ahora: datetime | None = None,
) -> str:
    settings = get_settings()
    marca = ahora if ahora is not None else datetime.now(UTC)
    if marca.tzinfo is None or marca.utcoffset() is None:
        raise ValueError("`ahora` debe ser una fecha con zona horaria.")
    iat = marca.timestamp()
    payload = {
        "sub": str(usuario_id),
        "iat": iat,
        "exp": int(iat) + settings.access_token_expire_seconds,
        "roles": [str(rol) for rol in roles],
    }
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=ALGORITMO_JWT,
    )


def decodificar_token_acceso(token: str) -> TokenAcceso:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[ALGORITMO_JWT],
            options={"require": ["sub", "iat", "exp"]},
        )
        sub = payload["sub"]
        if not isinstance(sub, str):
            raise TypeError
        # ID decimal canónico: sin signo, espacios, ceros a la izquierda ni
        # dígitos no ASCII. `int()` solo no alcanza ("-5", " 7 ", "007").
        if not sub.isascii() or not sub.isdigit() or sub.startswith("0"):
            raise ValueError
        roles = payload.get("roles", [])
        if not isinstance(roles, list):
            raise TypeError
        if not all(isinstance(rol, str) for rol in roles):
            raise TypeError
        return TokenAcceso(
            usuario_id=int(sub),
            iat=datetime.fromtimestamp(float(payload["iat"]), tz=UTC),
            exp=datetime.fromtimestamp(float(payload["exp"]), tz=UTC),
            roles=tuple(roles),
        )
    except (jwt.PyJWTError, TypeError, ValueError, OverflowError, OSError):
        raise TokenInvalidoError(_MENSAJE_TOKEN_INVALIDO) from None


def aplicar_cookie_acceso(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        NOMBRE_COOKIE_ACCESO,
        token,
        max_age=settings.access_token_expire_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def eliminar_cookie_acceso(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        NOMBRE_COOKIE_ACCESO,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


async def crear_hash_ficticio() -> str:
    return await hash_password(secrets.token_urlsafe(32))
