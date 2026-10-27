"""Errores de aplicación y traducción de errores a respuestas HTTP (RN18).

Convención (la heredan todos los módulos):

- Los SERVICIOS lanzan `NoEncontrado` (404), `Conflicto` (409) o `EntradaInvalida` (422)
  con un mensaje propio en español; no conocen HTTP. Un manejador global los traduce a
  `{"detail": mensaje}`.
- Un error de integridad específico se traduce en el servicio, FUERA del bloque del Unit of
  Work, con `restriccion_violada(exc)` (requiere restricciones con nombre estable, C-03).
  Sin traducción propia, el manejador global responde un mensaje genérico propio.
- Ninguna respuesta de error lleva texto de PostgreSQL o del driver, nombres de tablas o
  restricciones, SQL ni trazas. El detalle va sólo al log del servidor.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

logger = logging.getLogger(__name__)

MENSAJE_CONFLICTO_BASE = "La operación choca con datos ya registrados"
MENSAJE_RESTRICCION = "Los datos no cumplen las restricciones del sistema"
MENSAJE_RANGO = "Algún valor está fuera del rango o del formato permitido"
MENSAJE_INTERNO = "Error interno del servidor"

# SQLSTATE de PostgreSQL: 23505 unicidad, 23503 clave foránea, 23514 CHECK, 23502 NOT NULL,
# 22xxx errores de dato (tipo/rango/formato).
_SQLSTATE_CONFLICTO = {"23505", "23503"}


class ErrorDeAplicacion(Exception):
    status_code: int = 500

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


class NoEncontrado(ErrorDeAplicacion):
    status_code = 404


class Conflicto(ErrorDeAplicacion):
    status_code = 409


class EntradaInvalida(ErrorDeAplicacion):
    status_code = 422


def sqlstate(exc: BaseException) -> str | None:
    """SQLSTATE del error de base, o None. Defensiva: nunca lanza."""
    orig = getattr(exc, "orig", None)
    causa = getattr(orig, "__cause__", None)
    for candidato in (
        getattr(orig, "pgcode", None),
        getattr(orig, "sqlstate", None),
        getattr(causa, "sqlstate", None),
    ):
        if isinstance(candidato, str) and candidato:
            return candidato
    return None


def restriccion_violada(exc: BaseException) -> str | None:
    """Nombre de la restricción violada (p. ej. `uq_usuario_email`), o None. Nunca lanza."""
    orig = getattr(exc, "orig", None)
    causa = getattr(orig, "__cause__", None)
    for candidato in (getattr(causa, "constraint_name", None), getattr(orig, "constraint_name", None)):
        if isinstance(candidato, str) and candidato:
            return candidato
    return None


def _es_error_de_dato(exc: DBAPIError) -> bool:
    codigo = sqlstate(exc)
    if codigo is not None and codigo.startswith("22"):
        return True
    # Error de codificación del lado cliente (p. ej. entero fuera de int32) sin SQLSTATE.
    causa = getattr(getattr(exc, "orig", None), "__cause__", None) or exc.__cause__
    return causa is not None and any(c.__name__ == "DataError" for c in type(causa).__mro__)


def _respuesta(status_code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


async def _manejar_aplicacion(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ErrorDeAplicacion)
    return _respuesta(exc.status_code, exc.mensaje)


async def _manejar_integridad(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IntegrityError)
    codigo = sqlstate(exc)
    # Sólo SQLSTATE y restricción: el texto del driver puede traer valores del usuario.
    logger.warning("Violación de integridad: sqlstate=%s restriccion=%s", codigo, restriccion_violada(exc))
    if codigo in _SQLSTATE_CONFLICTO:
        return _respuesta(409, MENSAJE_CONFLICTO_BASE)
    return _respuesta(422, MENSAJE_RESTRICCION)


async def _manejar_dbapi(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DBAPIError)
    if _es_error_de_dato(exc):
        logger.warning("Dato rechazado por la base: sqlstate=%s", sqlstate(exc))
        return _respuesta(422, MENSAJE_RANGO)
    logger.exception("Error de base de datos no previsto: sqlstate=%s", sqlstate(exc))
    return _respuesta(500, MENSAJE_INTERNO)


async def _manejar_validacion(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Sin `input` (reflejaría contraseñas), `ctx` ni `url`.
    errores = [
        {"loc": jsonable_encoder(e["loc"]), "msg": str(e["msg"]), "type": str(e["type"])}
        for e in exc.errors()
    ]
    return _respuesta(422, errores)


async def _manejar_inesperado(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return _respuesta(500, MENSAJE_INTERNO)


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(ErrorDeAplicacion, _manejar_aplicacion)
    app.add_exception_handler(IntegrityError, _manejar_integridad)
    app.add_exception_handler(DBAPIError, _manejar_dbapi)
    app.add_exception_handler(RequestValidationError, _manejar_validacion)
    app.add_exception_handler(Exception, _manejar_inesperado)
