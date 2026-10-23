# Design — C-01 foundation-setup

## Context

Repositorio sin código Python (ver proposal.md — Why). Restricciones que moldean el diseño:

- Reglas duras de `CLAUDE.md`: sin `create_all`, secretos sin default y fuera del repo, handlers `async def`, ninguna entrada termina en 500 ni expone texto de la base.
- Consigna Ej.1: motor y fábrica creados **en el lifespan** y guardados en `app.state` (EA-08: nada construido al importar); `get_session` toma la fábrica de `app.state`, `expire_on_commit=False`, cierra la sesión al terminar; `dispose()` al apagar.
- Estructura de directorios obligatoria de `knowledge-base/08_arquitectura_propuesta.md`.
- Decisiones ya tomadas (KB 09, SU-01 y SU-05): nombres de variables `SECRET_KEY`, `BCRYPT_COST`, … y defaults 1800 s / 12 / 4 / 5 / 10 / `COOKIE_SECURE=false`.
- Sin pytest en el TP: la verificación es arrancando el servidor, archivos `.http` y comandos de Alembic.
- Entorno de desarrollo del equipo: Windows + PowerShell, PostgreSQL 16 local.

## Goals / Non-Goals

**Goals:**
- Dejar el esqueleto que cumple el Ej.1 completo y desbloquea C-02, C-03 y C-05.
- Que un `.env` mal armado falle **al arrancar** con un mensaje claro, no en la primera petición.
- Que `alembic upgrade head` funcione hoy (sin revisiones) y que C-03 sólo tenga que importar modelos y autogenerar.

**Non-Goals:**
- Hash ficticio en el lifespan (C-05), grupo de rutas protegido y dependencias de auth (C-08), UoW/repositorios/manejadores globales de `IntegrityError` (C-02), modelos y primera revisión (C-03), `seed.py` (C-06), `README.md` (C-16).
- Crear archivos vacíos para las seis capas de cada módulo: los módulos de dominio son sólo paquetes (`__init__.py`) hasta su change.
- Docker / docker-compose: no lo pide la consigna.

## Decisions

### D1 — `Settings` con pydantic-settings, campos en minúscula, sin instancia global
- `class Settings(BaseSettings)` con `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")`. Los campos se llaman `postgres_user`, `secret_key`, … (PEP 8) y mapean a `POSTGRES_USER`, `SECRET_KEY` por insensibilidad a mayúsculas.
- Acceso por `get_settings()` decorada con `@lru_cache`, llamada desde el lifespan y desde `migrations/env.py`. **No** hay `settings = Settings()` a nivel de módulo: así importar `main` no exige el `.env` (spec runtime-lifecycle, "Importar sin base disponible") y el error aparece en el arranque.
- *Alternativa descartada*: instancia global al importar — falla en el import con una traza menos clara y contradice EA-08.

### D2 — Secretos como `SecretStr` obligatorios y no vacíos
- `postgres_password: SecretStr` y `secret_key: SecretStr` **sin default** → `ValidationError` "Field required" que nombra el campo (pydantic lo imprime en minúscula: `secret_key`, `postgres_password`; es la misma variable por insensibilidad a mayúsculas). Un validador rechaza el string vacío (spec "Secreto vacío"). Para `secret_key` se exige además longitud mínima de 32 caracteres (clave de firma HS256 razonable; el `env.example` sugiere `python -c "import secrets; print(secrets.token_urlsafe(64))"`).
- `SecretStr` enmascara en `repr`/`str`/logs; el valor se lee con `.get_secret_value()` sólo donde se usa.
- *Alternativa*: `str` plano — expone el secreto si alguien imprime `Settings`.
- **Checkpoint (MEDIO)**: confirmar con el equipo el mínimo de 32 caracteres antes de escribir el validador (si un integrante ya tiene un `.env` con una clave más corta, el arranque fallará).

### D3 — `database_url` con `@computed_field` y `sqlalchemy.URL.create`
- `@computed_field(repr=False)` + `@property database_url -> str` que arma `URL.create("postgresql+asyncpg", username, password, host, port, database).render_as_string(hide_password=False)`. `URL.create` escapa `@`, `/`, `%` en la contraseña (spec "Contraseña con caracteres reservados"); `repr=False` evita que la URL con contraseña salga en el `repr` de `Settings`.
- *Alternativa*: f-string con `quote_plus` — funciona pero es fácil olvidarse del escape; `URL.create` es la API oficial.
- Riesgo: `model_dump()` sí incluye el campo calculado → nunca se loguea `model_dump()` de `Settings` (ver Riesgos).

### D4 — Parámetros operativos con validación de rango
`Field` con límites: `bcrypt_cost: int = Field(12, ge=4, le=31)`, `bcrypt_max_concurrency: int = Field(4, ge=1)`, `pool_size: int = Field(5, ge=1)`, `max_overflow: int = Field(10, ge=0)`, `access_token_expire_seconds: int = Field(1800, gt=0)`, `postgres_port: int = Field(5432, ge=1, le=65535)`, `cookie_secure: bool = False`, `sql_echo: bool = False`, `postgres_host: str = "localhost"`. `postgres_user` y `postgres_db` sin default (no son secretos pero no hay un valor universal; `env.example` trae `taller`). Defaults en código para lo no sensible; `env.example` pone `SQL_ECHO=true` para desarrollo (evidencia C-15).

### D5 — `database.py`: funciones fábrica, sin estado de módulo
- `create_engine(settings) -> AsyncEngine`: `create_async_engine(settings.database_url, pool_size=..., max_overflow=..., pool_pre_ping=True, echo=settings.sql_echo, connect_args={"timeout": 5})`. `pool_pre_ping` descarta conexiones muertas tras una caída de la base (spec "Recuperación"); `timeout` acota el connect de asyncpg (por defecto 60 s).
- `create_session_factory(engine) -> async_sessionmaker[AsyncSession]` con `expire_on_commit=False` y `class_=AsyncSession` **de `sqlmodel.ext.asyncio.session`** (da `session.exec()` con tipado de SQLModel; es subclase de la de SQLAlchemy, así que C-02 puede usar `execute` igual).
- `async def get_session(request: Request) -> AsyncIterator[AsyncSession]`: `async with request.app.state.session_factory() as session: yield session`. El `async with` cierra la sesión aunque la petición falle. **No** hace commit ni rollback: eso es del UoW (C-02). Alias `SessionDep = Annotated[AsyncSession, Depends(get_session)]` (compact rule fastapi: `Annotated` + alias de dependencia).

### D6 — `main.py`: lifespan con `asynccontextmanager` y grupo abierto
```
@asynccontextmanager
async def lifespan(app):
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
```
- `app = FastAPI(title="Taller mecánico", lifespan=lifespan)`. Se define `rutas_abiertas = APIRouter()` que incluye `health.router`, y se monta en la app; C-08 agrega `rutas_protegidas` al lado. Así el patrón "dos grupos" ya tiene su lugar sin adelantar lógica de auth.
- `on_event` está deprecado (compact rule fastapi-python): sólo lifespan.

### D7 — Router de salud
- `router = APIRouter(prefix="/health", tags=["health"])` (prefix/tags en el router, no en `include_router`, compact rule fastapi). Dos funciones `async def`, una operación cada una.
- `live`: devuelve `{"estado": "vivo"}`; no declara dependencia de sesión.
- `ready(session: SessionDep)`: `async with asyncio.timeout(READY_TIMEOUT_SECONDS):  await session.exec(text("SELECT 1"))` (`exec` y no `execute`: `AsyncSession.execute` de SQLModel emite `DeprecationWarning`); ante **cualquier `Exception`** (captura amplia a propósito: asyncpg puede propagar errores sin envolver en `SQLAlchemyError`, p. ej. `ConnectionDoesNotExistError` o `gaierror`/`OSError`, además de `TimeoutError`; sólo `session.exec` está dentro del `try`, y se registra únicamente el nombre del tipo de excepción, nunca el texto del driver) → `JSONResponse(status_code=503, content={"estado": "no listo", "detalle": "La base de datos no responde"})` y log del error (con `logger.warning` sin la URL). Éxito → `{"estado": "listo"}`. `READY_TIMEOUT_SECONDS = 3` como constante del módulo (no es configuración de despliegue que el equipo vaya a tocar).
- *Alternativa*: usar `app.state.engine.connect()` directo — válido, pero usar `SessionDep` ejercita la misma vía que usarán los módulos y demuestra `get_session` en la corrección.
- Respuesta tipada: modelos `EstadoSalud` (Pydantic, `extra="forbid"`) declarados en el propio `router.py` (el módulo health "sólo tiene router.py" por consigna).

### D8 — Alembic plantilla async, URL inyectada en `env.py`
- `alembic init -t async migrations` (genera `alembic.ini`, `migrations/env.py`, `script.py.mako`, `versions/`).
- `alembic.ini`: se **borra** la línea `sqlalchemy.url` (sin credenciales; spec "alembic.ini sin credenciales") y `script_location = %(here)s/migrations` (desvío respecto de `migrations` a secas: `%(here)s` resuelve la ruta relativa al `.ini`, así `alembic` funciona desde cualquier directorio; es el valor que genera la plantilla actual de Alembic).
- `env.py`: `settings = get_settings()`; en `run_async_migrations()` se construye `create_async_engine(settings.database_url, poolclass=NullPool)` en lugar de `async_engine_from_config`. Se evita `config.set_main_option("sqlalchemy.url", ...)` porque `configparser` interpreta `%` y rompe contraseñas con ese carácter. En modo offline se usa `context.configure(url=settings.database_url, ...)`.
- `target_metadata = SQLModel.metadata`; bloque comentado `# C-03: importar app.modules.*.models para registrar las tablas` donde C-03 agregará los imports. `compare_type=True` en `context.configure` (online y offline).
- `script.py.mako`: agregar `import sqlmodel` junto a `import sqlalchemy as sa` — las columnas `str` de SQLModel autogeneran `sqlmodel.sql.sqltypes.AutoString()` y sin el import la revisión de C-03 no corre (gotcha conocido).
- `migrations/versions/.gitkeep` para versionar la carpeta vacía.
- Consecuencia aceptada: Alembic también exige `SECRET_KEY` (usa el mismo `Settings`). Está en el mismo `.env`, así que no agrega fricción.
- Compact rules de sqlalchemy-alembic (índices `concurrently`, `NOT VALID`, cambios multi-paso) aplican a migraciones sobre tablas con datos; no aplican aquí (sin revisiones) y C-03 crea tablas nuevas sobre base vacía — se registran para C-03/C-04.

### D9 — `requirements.txt` con cotas inferiores y techo de mayor
`fastapi[standard]>=0.111,<1`, `sqlmodel>=0.0.24,<0.1`, `sqlalchemy[asyncio]>=2.0,<2.1`, `asyncpg>=0.30,<1`, `alembic>=1.13,<2`, `pydantic-settings>=2.0,<3`, `bcrypt>=4.0,<6`, `PyJWT>=2.8,<3`. Cotas mínimas del stack declarado en CLAUDE.md; techos para no recibir un mayor incompatible el día de la corrección. `uvicorn` llega con `fastapi[standard]`. Sin herramientas de test (no hay pytest en el TP).
- **Checkpoint (MEDIO)**: tras instalar en un venv limpio, decidir si se fija `pip freeze` exacto o se mantienen rangos; se reporta la versión resuelta de cada paquete.

### D10 — `.gitignore` y `env.example`
- `.gitignore`: `.env`, `.env.*` (`env.example` no coincide con ese patrón, así que queda versionado), `.venv/`, `venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.idea/`, `.vscode/`, `*.log`.
- **Checkpoint (MEDIO)**: `.atl/` (registro de skills local, declarado "no versionado" en CLAUDE.md) y el PDF duplicado en la raíz (`TP_Cap1a6_Consigna.pdf`, ya existe en `docs/`) están sin trackear: proponer agregarlos a `.gitignore` y que el usuario decida.
- `env.example`: todas las variables de `Settings`, agrupadas (Base de datos / Seguridad / Pool / Diagnóstico), con comentario por variable; `POSTGRES_PASSWORD=` y `SECRET_KEY=` vacíos; comentario con el comando para generar la clave.

### D11 — Verificación sin test runner
Strict TDD está activo globalmente, pero el proyecto no tiene test runner (decisión del TP). Se reemplaza el ciclo RED/GREEN por verificación ejecutable: `test/health.http` (live, ready) + comandos de arranque/Alembic con resultado esperado escrito en cada task. Cada escenario de las specs tiene un paso de verificación manual asociado.

## Risks / Trade-offs

- [`model_dump()` de `Settings` incluye `database_url` con contraseña] → nunca loguear `Settings` completo; los logs de arranque sólo mencionan host/puerto/base. Se deja comentario en `config.py`.
- [`lru_cache` en `get_settings` congela la config durante el proceso] → es lo esperado; en C-16 los `.http` corren contra un proceso arrancado con el `.env` final.
- [Usar `SessionDep` en `/health/ready` consume una conexión del pool por sonda] → pool chico (5) pero las sondas son esporádicas; la sesión se libera al terminar la petición.
- [`asyncio.timeout` cancela la conexión de asyncpg a mitad del handshake] → `pool_pre_ping` + `connect_args timeout` hacen que la siguiente sonda abra una conexión nueva; aceptable para una sonda.
- [`.env` con encoding distinto a UTF-8 en Windows (PowerShell `>` escribe UTF-16)] → `env_file_encoding="utf-8"` y nota en `env.example`: copiar con `Copy-Item env.example .env`, no con redirección.
- [Alembic pide `SECRET_KEY` aunque no lo use] → trade-off aceptado por tener una sola fuente de configuración.

## Migration Plan

No hay sistema previo. Puesta en marcha local: crear venv → `pip install -r requirements.txt` → `Copy-Item env.example .env` y completar secretos → crear la base vacía en PostgreSQL → `alembic upgrade head` → `uvicorn main:app --reload`. Rollback: borrar los archivos nuevos (nada toca la base salvo la tabla `alembic_version`).

## Open Questions

- Mínimo de 32 caracteres para `SECRET_KEY` (D2) y si se ignoran `.atl/` y el PDF de la raíz (D10): checkpoints a confirmar durante el apply; no cambian specs ni tasks.
