import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.core.database import SessionDep

logger = logging.getLogger(__name__)

READY_TIMEOUT_SECONDS = 3

router = APIRouter(prefix="/health", tags=["health"])


class EstadoSalud(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estado: str


class EstadoNoListo(EstadoSalud):
    detalle: str


@router.get("/live")
async def live() -> EstadoSalud:
    return EstadoSalud(estado="vivo")


@router.get("/ready", response_model=EstadoSalud, responses={503: {"model": EstadoNoListo}})
async def ready(session: SessionDep) -> EstadoSalud | JSONResponse:
    try:
        async with asyncio.timeout(READY_TIMEOUT_SECONDS):
            await session.exec(text("SELECT 1"))  # type: ignore[call-overload]
    except Exception as exc:  # noqa: BLE001
        # Amplio a proposito: asyncpg puede propagar sus excepciones (ClientError,
        # PostgresError) o OSError sin envolverlas en SQLAlchemyError al conectar.
        # Solo el tipo de error: el texto del driver puede traer host/usuario.
        logger.warning("Sonda ready fallida: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content=EstadoNoListo(
                estado="no listo", detalle="La base de datos no responde"
            ).model_dump(),
        )
    return EstadoSalud(estado="listo")
