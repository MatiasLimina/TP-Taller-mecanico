"""Verificación reproducible de C-05 security-core.

Uso, desde la raíz del TP:

    .venv\\Scripts\\python.exe test\\verificar_security_core.py

No usa pytest ni necesita PostgreSQL: configura variables de entorno de prueba,
usa `TestClient` sólo para el lifespan y sale con código 1 si alguna
verificación falla.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# Configuración mínima y determinista: no depende del `.env` local ni de una
# base real. `BCRYPT_COST=4` mantiene el script rápido; el código usa el valor
# configurado, no un 12 hardcodeado.
os.environ["POSTGRES_USER"] = "verificacion"
os.environ["POSTGRES_PASSWORD"] = "verificacion"
os.environ["POSTGRES_DB"] = "verificacion"
os.environ["SECRET_KEY"] = "x" * 64
os.environ["BCRYPT_COST"] = "4"
os.environ["BCRYPT_MAX_CONCURRENCY"] = "4"
os.environ.pop("COOKIE_SECURE", None)

import jwt
from fastapi.testclient import TestClient
from starlette.responses import Response

from app.core import security
from app.core.config import get_settings
from app.core.security import (
    PasswordInvalidaError,
    TokenInvalidoError,
    aplicar_cookie_acceso,
    crear_hash_ficticio,
    crear_token_acceso,
    decodificar_token_acceso,
    eliminar_cookie_acceso,
    hash_password,
    verify_password,
)

_verificaciones = 0


def verificar(nombre: str, condicion: bool) -> None:
    global _verificaciones
    if not condicion:
        raise AssertionError(nombre)
    _verificaciones += 1
    print(f"OK  {nombre}")


def _token_con_sub(sub: object) -> str:
    ahora = datetime.now(UTC)
    payload = {
        "sub": sub,
        "iat": ahora.timestamp(),
        "exp": int(ahora.timestamp()) + 1800,
    }
    return jwt.encode(
        payload,
        get_settings().secret_key.get_secret_value(),
        algorithm="HS256",
    )


async def probar_passwords() -> None:
    costo = get_settings().bcrypt_cost
    h1 = await hash_password("secreto-123")
    h2 = await hash_password("secreto-123")
    verificar("hash con sal distinta", h1 != h2)
    verificar("hash con el costo configurado", h1.startswith(f"$2b${costo:02d}$"))
    verificar(
        "verifica la contraseña correcta", await verify_password("secreto-123", h1)
    )
    verificar("rechaza la contraseña incorrecta", not await verify_password("otra", h1))
    verificar(
        "hash ilegible devuelve False", not await verify_password("x", "no-es-hash")
    )
    h72 = await hash_password("a" * 72)
    verificar("72 bytes exactos se aceptan", await verify_password("a" * 72, h72))

    try:
        await hash_password("a" * 73)
    except PasswordInvalidaError:
        verificar("73 bytes se rechazan al hashear", True)
    else:
        verificar("73 bytes se rechazan al hashear", False)

    try:
        await hash_password("ñ" * 40)
    except PasswordInvalidaError:
        verificar("40 caracteres ñ (80 bytes) se rechazan", True)
    else:
        verificar("40 caracteres ñ (80 bytes) se rechazan", False)

    try:
        await verify_password("a" * 73, h72)
    except PasswordInvalidaError:
        verificar("73 bytes no se truncan al verificar", True)
    else:
        verificar("73 bytes no se truncan al verificar", False)


async def probar_concurrencia() -> None:
    original = security._hashear_bcrypt
    activos = 0
    maximo = 0
    candado = threading.Lock()

    def lento(password: bytes, costo: int) -> bytes:
        nonlocal activos, maximo
        with candado:
            activos += 1
            maximo = max(maximo, activos)
        try:
            time.sleep(0.03)
            return original(password, costo)
        finally:
            with candado:
                activos -= 1

    security._hashear_bcrypt = lento
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    tarea = asyncio.create_task(ticker())
    try:
        hashes = await asyncio.gather(*(hash_password(f"pw-{i}") for i in range(8)))
        await asyncio.sleep(0)
    finally:
        tarea.cancel()
        security._hashear_bcrypt = original
        try:
            await tarea
        except asyncio.CancelledError:
            pass
    verificar("8 hashes concurrentes terminan", len(hashes) == 8)
    verificar("máximo de bcrypt simultáneos <= 4", maximo <= 4)
    verificar("el bucle no se bloquea durante bcrypt", ticks > 0)


async def probar_tokens() -> None:
    marca = datetime.now(UTC).replace(microsecond=123456)
    token = crear_token_acceso(7, ["ADMIN", "MECANICO"], ahora=marca)
    datos = decodificar_token_acceso(token)
    verificar("sub vuelve como entero", datos.usuario_id == 7)
    verificar("roles se conservan", datos.roles == ("ADMIN", "MECANICO"))
    verificar("iat conserva microsegundos", datos.iat.microsecond == 123456)
    verificar("iat y exp son UTC", datos.iat.tzinfo is UTC and datos.exp.tzinfo is UTC)
    verificar(
        "vigencia de 1800 s",
        int((datos.exp - datos.iat).total_seconds()) in (1799, 1800),
    )

    vencido = crear_token_acceso(
        7, [], ahora=datetime.now(UTC) - timedelta(seconds=4000)
    )
    try:
        decodificar_token_acceso(vencido)
    except TokenInvalidoError:
        verificar("token vencido => TokenInvalidoError", True)
    else:
        verificar("token vencido => TokenInvalidoError", False)

    try:
        decodificar_token_acceso(token[:-2] + "xx")
    except TokenInvalidoError:
        verificar("token alterado => TokenInvalidoError", True)
    else:
        verificar("token alterado => TokenInvalidoError", False)

    ahora = datetime.now(UTC)
    ajeno = jwt.encode(
        {"sub": "7", "iat": ahora.timestamp(), "exp": int(ahora.timestamp()) + 1800},
        "otra-clave-" * 4,
        algorithm="HS256",
    )
    try:
        decodificar_token_acceso(ajeno)
    except TokenInvalidoError:
        verificar("token con otra clave => TokenInvalidoError", True)
    else:
        verificar("token con otra clave => TokenInvalidoError", False)

    sin_claims = jwt.encode(
        {"sub": "7"},
        get_settings().secret_key.get_secret_value(),
        algorithm="HS256",
    )
    try:
        decodificar_token_acceso(sin_claims)
    except TokenInvalidoError:
        verificar("token sin iat/exp => TokenInvalidoError", True)
    else:
        verificar("token sin iat/exp => TokenInvalidoError", False)

    verificar(
        "sub decimal válido se acepta",
        decodificar_token_acceso(_token_con_sub("10")).usuario_id == 10,
    )
    for sub in ("-5", " 7 ", "007", "0", "٧", "²", "abc", ""):
        try:
            decodificar_token_acceso(_token_con_sub(sub))
        except TokenInvalidoError:
            verificar(f"sub inválido rechazado: {sub!a}", True)
        else:
            verificar(f"sub inválido rechazado: {sub!a}", False)

    for sub in (7, None):
        try:
            decodificar_token_acceso(_token_con_sub(sub))
        except TokenInvalidoError:
            verificar(f"sub no textual rechazado: {sub!a}", True)
        else:
            verificar(f"sub no textual rechazado: {sub!a}", False)


def probar_cookies() -> None:
    token = crear_token_acceso(7, [])
    respuesta = Response()
    aplicar_cookie_acceso(respuesta, token)
    cookie = respuesta.headers["set-cookie"]
    verificar("cookie con nombre access_token", "access_token=" in cookie)
    verificar("cookie HttpOnly", "HttpOnly" in cookie)
    verificar("cookie SameSite=Lax", "SameSite=lax" in cookie)
    verificar("cookie Path=/", "Path=/" in cookie)
    verificar(
        "cookie Max-Age",
        f"Max-Age={get_settings().access_token_expire_seconds}" in cookie,
    )
    verificar("cookie sin Secure en desarrollo", "Secure" not in cookie)

    borrada = Response()
    eliminar_cookie_acceso(borrada)
    verificar("logout borra la cookie", "Max-Age=0" in borrada.headers["set-cookie"])

    os.environ["COOKIE_SECURE"] = "true"
    get_settings.cache_clear()
    try:
        segura = Response()
        aplicar_cookie_acceso(segura, token)
        verificar(
            "cookie Secure configurable", "Secure" in segura.headers["set-cookie"]
        )
    finally:
        os.environ.pop("COOKIE_SECURE", None)
        get_settings.cache_clear()


async def probar_hash_ficticio() -> None:
    h1 = await crear_hash_ficticio()
    h2 = await crear_hash_ficticio()
    verificar(
        "hash ficticio con bcrypt",
        h1.startswith(f"$2b${get_settings().bcrypt_cost:02d}$"),
    )
    verificar("hash ficticio distinto por llamada", h1 != h2)
    verificar("hash ficticio no verifica", not await verify_password("cualquiera", h1))


def probar_lifespan() -> None:
    security._semaforo_bcrypt = None
    from main import app

    with TestClient(app) as cliente:
        verificar("lifespan crea hash_ficticio", hasattr(app.state, "hash_ficticio"))
        primero = app.state.hash_ficticio
        verificar(
            "hash_ficticio tiene bcrypt",
            primero.startswith(f"$2b${get_settings().bcrypt_cost:02d}$"),
        )
        verificar(
            "health/live responde 200", cliente.get("/health/live").status_code == 200
        )
        verificar(
            "hash_ficticio estable entre peticiones", app.state.hash_ficticio == primero
        )


async def probar_core() -> None:
    await probar_passwords()
    await probar_concurrencia()
    await probar_tokens()
    probar_cookies()
    await probar_hash_ficticio()


def main() -> None:
    print("== C-05 security-core: verificación reproducible ==")
    probar_lifespan()
    security._semaforo_bcrypt = None
    asyncio.run(probar_core())
    print(f"\nOK: {_verificaciones} verificaciones pasaron.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nFALLA: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc
