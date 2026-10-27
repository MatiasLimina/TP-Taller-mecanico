from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.errores import registrar_manejadores
import app.modules.modelos  # noqa: F401  (registra los modelos antes de la primera consulta)
from app.modules.health.router import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    # C-05: app.state.hash_ficticio = await hash_password(...)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Taller mecánico", lifespan=lifespan)
registrar_manejadores(app)

# Grupo de rutas públicas. C-08 agrega `rutas_protegidas` al lado.
rutas_abiertas = APIRouter()
rutas_abiertas.include_router(health_router)

app.include_router(rutas_abiertas)
