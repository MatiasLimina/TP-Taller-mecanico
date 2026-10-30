from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI

# Registra los 13 modelos (y resuelve sus relaciones) antes de la primera consulta.
import app.modules.modelos
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.dependencies import exigir_password_al_dia
from app.core.errores import registrar_manejadores
from app.core.security import crear_hash_ficticio
from app.modules.clientes.router import (
    router_clientes,
    router_mis_vehiculos,
    router_vehiculos,
)
from app.modules.health.router import router as health_router
from app.modules.ordenes.router import router_estados
from app.modules.repuestos.router import router_admin_repuestos, router_catalogo
from app.modules.usuarios.router import router as auth_router
from app.modules.usuarios.router import router_eventos, router_personal


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    try:
        app.state.hash_ficticio = await crear_hash_ficticio()
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Taller mecánico", lifespan=lifespan)
registrar_manejadores(app)

# Grupo de rutas públicas (salud, registro, login, logout, perfil y cambio de contraseña).
rutas_abiertas = APIRouter()
rutas_abiertas.include_router(health_router)
rutas_abiertas.include_router(auth_router)

# Grupo de rutas protegidas (RN06): exige sesión y, si el usuario debe cambiar la contraseña,
# responde 403 en toda ruta del grupo. El control se monta UNA vez acá; no va en ningún router.
# Cada módulo incluye sus routers con `rutas_protegidas.include_router(...)` ANTES de
# `app.include_router(rutas_protegidas)`: `include_router` copia las rutas en ese momento y lo
# que se agregue después no queda montado. C-09: personal, roles de un usuario y eventos
# (sólo ADMIN); C-11: catálogo de repuestos (lectura: ADMIN, RECEPCION y MECANICO; escritura: sólo
# ADMIN); C-10: clientes, vehículos y mis-vehículos; C-13: catálogo de estados de las órdenes y
# alta de órdenes; los siguientes suman los suyos.
rutas_protegidas = APIRouter(dependencies=[Depends(exigir_password_al_dia)])
rutas_protegidas.include_router(router_personal)
rutas_protegidas.include_router(router_eventos)
rutas_protegidas.include_router(router_catalogo)
rutas_protegidas.include_router(router_admin_repuestos)
rutas_protegidas.include_router(router_clientes)
rutas_protegidas.include_router(router_vehiculos)
rutas_protegidas.include_router(router_mis_vehiculos)
rutas_protegidas.include_router(router_estados)

app.include_router(rutas_abiertas)
app.include_router(rutas_protegidas)
