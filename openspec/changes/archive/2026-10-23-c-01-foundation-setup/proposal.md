# Proposal — C-01 foundation-setup

## Why

El repositorio todavía no tiene código: sólo KB, roadmap y reglas. La consigna marca como **condición bloqueante** que el proyecto levante, que `alembic upgrade head` cree el esquema sobre una base vacía y que no haya credenciales en el repo; además, el Ej.1 (8 %) evalúa estructura, `Settings` sin secretos por defecto, motor y fábrica creados en el lifespan, `get_session` y salud. Todos los demás changes (C-02 en adelante) se apoyan en esta base, por eso va primero en el camino crítico.

## What Changes

- Estructura de directorios obligatoria: `main.py`, `app/core/`, `app/modules/{health,usuarios,clientes,repuestos,ordenes}/`, `migrations/`, `test/` (los módulos de dominio quedan como paquetes vacíos; sus capas llegan en C-03, C-07, C-10…).
- `requirements.txt` con el stack mínimo (fastapi[standard], sqlmodel, sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, bcrypt≥4.0, PyJWT).
- `.gitignore` que excluye `.env` (y artefactos locales), y `env.example` con **todas** las variables y ningún secreto.
- `app/core/config.py`: `Settings` (pydantic-settings) leído del entorno/`.env`; URL de la base armada con `@computed_field` desde `POSTGRES_*` con driver `postgresql+asyncpg`; `POSTGRES_PASSWORD` y `SECRET_KEY` **sin valor por defecto** (si faltan, la app no arranca); `BCRYPT_COST`, `BCRYPT_MAX_CONCURRENCY`, `POOL_SIZE`, `MAX_OVERFLOW`, `COOKIE_SECURE`, `ACCESS_TOKEN_EXPIRE_SECONDS=1800`, `SQL_ECHO`.
- `app/core/database.py`: funciones que crean el motor asincrónico (pool desde `Settings`) y la fábrica de sesiones (`expire_on_commit=False`), y `get_session` (una sesión por petición tomada de `app.state`, cerrada al terminar).
- `main.py`: aplicación con lifespan que crea motor y fábrica en `app.state` y hace `dispose()` al apagar; grupo de rutas abierto con el módulo de salud. (El hash ficticio del login se agrega en C-05; el grupo protegido, en C-08.)
- `app/modules/health/router.py`: `GET /health/live` (no toca la base) y `GET /health/ready` (`SELECT 1`; 503 si la base no contesta).
- Alembic inicializado con la plantilla asincrónica en `migrations/`; `alembic.ini` sin credenciales; `env.py` toma la URL de `Settings`. Sin versiones todavía (la primera llega en C-03).
- `test/health.http` con los casos de salud para la verificación manual.

## Capabilities

### New Capabilities
- `app-configuration`: carga de configuración desde entorno/`.env`, armado de la URL de la base, secretos obligatorios sin default, valores por defecto documentados y plantilla `env.example`.
- `runtime-lifecycle`: ciclo de vida del proceso: recursos de base creados al arrancar (no al importar), una sesión por petición que se cierra al terminar, liberación del motor al apagar.
- `service-health`: sondas de vida y de disponibilidad (`/health/live`, `/health/ready`) con sus códigos y sin filtrar detalles internos.
- `schema-migrations`: gestión del esquema exclusivamente por Alembic, sin credenciales en su configuración y aplicable sobre una base vacía.

### Modified Capabilities
- (ninguna — no hay specs previas en `openspec/specs/`)

## Impact

- **Código nuevo**: `main.py`, `app/core/{config,database}.py`, `app/modules/health/router.py`, paquetes `app/modules/*`, `migrations/` (env.py, script.py.mako), `alembic.ini`, `test/health.http`.
- **Archivos de proyecto**: `requirements.txt`, `.gitignore`, `env.example`.
- **Dependencias externas**: PostgreSQL 16 accesible con las credenciales del `.env` local de cada integrante.
- **Downstream**: C-02 (UoW/repos usan `get_session`), C-03 (modelos y primera migración usan `env.py`/`target_metadata`), C-05 (usa `BCRYPT_*`, `SECRET_KEY` y agrega el hash ficticio al lifespan), C-08 (agrega el grupo protegido en `main.py`).
- **Nombre del change**: el CLI exige minúsculas, por lo que el change se registró como `c-01-foundation-setup` (equivale a `C-01 foundation-setup` de CHANGES.md).
