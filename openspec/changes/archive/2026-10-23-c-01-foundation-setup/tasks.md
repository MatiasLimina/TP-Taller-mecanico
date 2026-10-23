# Tasks — C-01 foundation-setup

> **Verificación**: el TP no tiene test runner (sin pytest, decisión del proyecto). Strict TDD se reemplaza por verificación ejecutable: cada task indica el comando o la petición `.http` y el resultado esperado. Governance **MEDIO**: los ítems marcados **[checkpoint]** se frenan y se consultan al usuario antes de seguir.
> Skills a cargar antes de escribir código: `fastapi`, `fastapi-templates`, `sqlalchemy-alembic-expert-best-practices-code-review`.
> Prerrequisito local: Python 3.12, PostgreSQL 16 corriendo y una base vacía creada (p. ej. `taller`).

## 1. Estructura y dependencias

- [x] 1.1 Crear la estructura obligatoria: `main.py` (vacío por ahora), `app/__init__.py`, `app/core/__init__.py`, `app/modules/__init__.py`, `app/modules/{health,usuarios,clientes,repuestos,ordenes}/__init__.py`, `test/` — sin stubs de capas en los módulos de dominio (design D-Non-Goals). Verificar: `python -c "import app.modules.health, app.modules.usuarios, app.modules.clientes, app.modules.repuestos, app.modules.ordenes"` termina sin error.
- [x] 1.2 Escribir `requirements.txt` con los rangos de design D9 y crear venv (`py -3.12 -m venv .venv`). Verificar: `pip install -r requirements.txt` termina sin error y `python -c "import fastapi, sqlmodel, sqlalchemy, asyncpg, alembic, pydantic_settings, bcrypt, jwt"` importa todo.
- [x] 1.3 **[checkpoint]** Reportar al usuario las versiones resueltas (`pip freeze`) y preguntar si se fijan exactas o se mantienen rangos (D9). Verificar: decisión registrada en el resumen del apply.
- [x] 1.4 Escribir `.gitignore` según D10. **[checkpoint]** preguntar si se agregan `.atl/` y `/TP_Cap1a6_Consigna.pdf`. Verificar: `git check-ignore .env .venv` lista ambos y `git status` no muestra `.venv/` ni `__pycache__/`.

## 2. Configuración (`app/core/config.py`)

- [x] 2.1 **[checkpoint]** Confirmar con el usuario la longitud mínima de 32 caracteres para `SECRET_KEY` (D2) antes de escribir el validador.
- [x] 2.2 Implementar `Settings` (D1–D4): campos en minúscula, `SecretStr` sin default para `postgres_password` y `secret_key` con validador de no vacío (+ mínimo acordado), `@computed_field(repr=False) database_url` con `URL.create(...)`, defaults y rangos de D4, `get_settings()` con `@lru_cache`, sin instancia a nivel de módulo. Verificar con un `.env` de prueba: `python -c "from app.core.config import get_settings; s=get_settings(); print(s); print(s.database_url)"` → el `print(s)` muestra secretos como `**********` y no incluye la URL; `database_url` empieza con `postgresql+asyncpg://`.
- [x] 2.3 Verificar los escenarios de la spec `app-configuration` desde PowerShell: (a) sin `SECRET_KEY` → `ValidationError` que nombra `secret_key`; (b) sin `POSTGRES_PASSWORD` → idem; (c) `SECRET_KEY=` vacío → falla; (d) `$env:POOL_SIZE=8` pisa el `5` del `.env`; (e) `BCRYPT_COST=3`, `POOL_SIZE=0`, `POSTGRES_PORT=abc` → falla nombrando la variable; (f) contraseña con `@/%` genera URL escapada. Anotar el resultado de cada uno en el resumen.
- [x] 2.4 Escribir `env.example` (D10) con todas las variables de `Settings`, comentadas y agrupadas; `POSTGRES_PASSWORD=` y `SECRET_KEY=` vacíos; comando para generar la clave y nota de copiar con `Copy-Item env.example .env`. Verificar: copiar a un `.env` temporal, completar sólo los dos secretos y `get_settings()` carga sin error; `Select-String -Path env.example -Pattern "PASSWORD=.+|SECRET_KEY=.+"` no devuelve nada.

## 3. Base de datos y ciclo de vida

- [x] 3.1 Implementar `app/core/database.py` (D5): `create_engine(settings)` (pool, `pool_pre_ping`, `echo`, `connect_args={"timeout": 5}`), `create_session_factory(engine)` con `expire_on_commit=False` y `AsyncSession` de SQLModel, `get_session(request)` con `async with` (sin commit/rollback) y alias `SessionDep`. Sin estado a nivel de módulo. Verificar: `python -c "import app.core.database"` con PostgreSQL apagado no intenta conectar ni falla.
- [x] 3.2 Implementar `main.py` (D6): `lifespan` con `asynccontextmanager` que guarda `settings`, `engine` y `session_factory` en `app.state`, comentario de lugar para el hash ficticio (C-05), `try/finally` con `await engine.dispose()`; `rutas_abiertas = APIRouter()` montado en la app. Verificar: `python -c "import main"` sin `.env` no falla (EA-08); `uvicorn main:app` sin `.env` aborta el arranque con el error de `Settings` y no queda escuchando.

## 4. Salud (`app/modules/health/router.py`)

- [x] 4.1 Implementar el router de salud (D7): `APIRouter(prefix="/health", tags=["health"])`, `GET /live` sin dependencias, `GET /ready` con `SessionDep` + `asyncio.timeout(3)` + `SELECT 1`, 503 con mensaje propio ante cualquier `Exception` (captura amplia a propósito: asyncpg lanza errores sin envolver, p. ej. `ConnectionDoesNotExistError`/`gaierror`; sólo `session.exec` queda dentro del `try` y se loguea sólo el nombre del tipo), modelos de respuesta con `extra="forbid"`; incluirlo en `rutas_abiertas`. Ambos handlers `async def`. Verificar: `uvicorn main:app` arranca y `/docs` lista las dos rutas.
- [x] 4.2 Escribir `test/health.http` con `GET /health/live` y `GET /health/ready` (variable `@base = http://localhost:8000`) y el resultado esperado comentado en cada caso. Verificar con la base arriba: live → 200 `{"estado":"vivo"}`, ready → 200 `{"estado":"listo"}`; con `SQL_ECHO=true` la consola muestra `SELECT 1`.
- [x] 4.3 Verificar degradación (spec `service-health`): detener el servicio de PostgreSQL → ready → 503 en ≤ 5 s con cuerpo sin host/usuario/texto del driver, live → 200; volver a levantarlo → ready → 200 sin reiniciar uvicorn. Repetir con `POSTGRES_PASSWORD` incorrecta → ready 503 con el mismo cuerpo. Ctrl+C → el proceso termina sin advertencias de conexiones abiertas. *(Verificado sin detener el servicio: contraseña incorrecta → 503 con cuerpo propio y live 200; host inalcanzable → 503 en ~3 s por el timeout; apagado del lifespan sin advertencias. La recuperación tras stop/start del servicio de PostgreSQL NO se probó: se evitó reiniciar el servidor local del usuario.)*

## 5. Migraciones (Alembic async)

- [x] 5.1 Ejecutar `alembic init -t async migrations`; en `alembic.ini` borrar `sqlalchemy.url` y dejar `script_location = %(here)s/migrations` (valor de la plantilla; desvío menor respecto de `migrations`); agregar `migrations/versions/.gitkeep`. Verificar: `Select-String -Path alembic.ini -Pattern "sqlalchemy.url|postgresql"` no devuelve nada.
- [x] 5.2 Adaptar `migrations/env.py` (D8): `get_settings()`, `create_async_engine(settings.database_url, poolclass=NullPool)` en online, `url=settings.database_url` en offline, `target_metadata = SQLModel.metadata`, `compare_type=True`, comentario de lugar para los imports de modelos de C-03; agregar `import sqlmodel` en `script.py.mako`. Verificar: `alembic current` contra la base vacía termina sin error.
- [x] 5.3 Verificar la spec `schema-migrations`: `alembic upgrade head` sobre base vacía → código 0; tras arrancar la app, `\dt` en psql muestra sólo `alembic_version` (ninguna tabla creada por la app); sin `POSTGRES_PASSWORD` → `alembic current` falla nombrando la variable. Confirmar con `Select-String -Path app,main.py -Pattern "create_all" -Recurse` que no hay `create_all`.

## 6. Cierre integrado

- [x] 6.1 Recorrido desde cero en un clon limpio (o carpeta temporal): venv → `pip install -r requirements.txt` → `Copy-Item env.example .env` + secretos → `alembic upgrade head` → `uvicorn main:app` → `test/health.http` en verde. Verificar además: `git status --ignored` muestra `.env` como ignorado y ningún archivo versionado contiene credenciales (`git grep -n -i "password=\|secret_key=" -- . ':!openspec' ':!knowledge-base'` sin valores reales). No commitear: el usuario decide cuándo.
