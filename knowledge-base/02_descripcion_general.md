# Descripción General

## Stack tecnológico
| Capa | Tecnología | Versión mínima |
|------|-----------|----------------|
| Lenguaje | Python | 3.12 |
| Framework web | FastAPI (todos los handlers `async def`) | 0.111 |
| Modelos de tabla | SQLModel | 0.0.24 |
| ORM / motor | SQLAlchemy 2.0 asincrónico | 2.0 |
| Driver | asyncpg (o psycopg 3 asincrónico) | 0.30 |
| Base de datos | PostgreSQL | 16 |
| Migraciones | Alembic, plantilla asincrónica | 1.13 |
| Configuración | pydantic-settings | 2.0 |
| Hash de contraseñas | bcrypt | 4.0 (la consigna menciona comportamiento de v5: rechaza >72 bytes) |
| Token | PyJWT | 2.8 |
| Servidor | uvicorn (de `fastapi[standard]`) | el que instala |

## Arquitectura general
Capas por módulo funcional, mismas seis en todos los módulos:

```
HTTP → router.py → service.py → unit_of_work.py → repository.py → models.py → PostgreSQL
        (rutas,      (reglas de     (transacción,     (acceso a datos,   (tablas,
        UoW por       negocio;       compone repos,    flush, nunca       restricciones)
        dependencia)  abre el UoW)   misma sesión)     commit)
```

- Router construye el UoW con una dependencia y se lo pasa al servicio **sin abrirlo**; el servicio lo abre con `async with` y **nunca lo construye**.
- UoW base: confirma al salir del bloque, revierte ante excepción, **no cierra la sesión** (no la creó).
- Motor y fábrica de sesiones se crean en el `lifespan` y viven en `app.state` (no al importar).
- Recursos del lifespan: motor (con pool configurado), fábrica de sesiones, hash ficticio de login (calculado una vez); `dispose()` al apagar.

## Integraciones externas
| Servicio | Propósito | Tipo |
|----------|-----------|------|
| PostgreSQL 16 | Persistencia, integridad, triggers | asyncpg / psycopg3 |
| Aviso al cliente | Simulado: `await asyncio.sleep(0.5)` + log, vía `BackgroundTasks` | in-process |

No hay servicios externos reales.

## API REST (resumen por grupo)
Dos grupos de rutas en `main.py`: **abierto** (health, auth) y **protegido** (lleva el control de cambio-de-contraseña-obligatorio montado una sola vez).

| Recurso | Endpoints |
|---------|-----------|
| health | `GET /health/live`, `GET /health/ready` |
| auth | `POST /auth/registro`, `/auth/login`, `/auth/logout`, `GET /auth/yo`, `POST /auth/cambiar-password` |
| usuarios | `POST /usuarios`, `POST/GET /usuarios/{id}/roles`, `DELETE /usuarios/{id}/roles/{rol}`, `GET /eventos` |
| clientes | `POST /clientes`, `GET /clientes/{id}`, `POST /clientes/{id}/vehiculos`, `DELETE /vehiculos/{id}`, `GET /mis-vehiculos` |
| repuestos | `GET/POST /repuestos`, `GET/PATCH/DELETE /repuestos/{id}`, `POST /repuestos/{id}/reponer`, `GET /repuestos/{id}/movimientos`, `GET /repuestos/{id}/precios` |
| ordenes | `GET/POST /ordenes`, `GET /ordenes/{id}`, `POST /ordenes/{id}/iniciar|terminar|cancelar`, `GET /estados-orden`, `GET /mis-ordenes` |

La matriz validada de roles y códigos está en `03_actores_y_roles.md`.

Detalle completo en `03` (permisos) y `06` (funcionalidades). Listados usan el envoltorio `{items, total, page, size, pages}`.

## Requisitos no funcionales
| Requisito | Detalle |
|-----------|---------|
| Asincronía | Todos los handlers `async def`; bcrypt siempre fuera del bucle (`to_thread` + semáforo) |
| Credenciales | Ninguna contraseña ni clave de firma en el código (ni por defecto), ni en `alembic.ini` ni en el repo |
| Token | Sólo en cookie HttpOnly; nunca en el cuerpo ni leído de `Authorization` |
| Esquema | Sólo Alembic; sin `create_all` |
| Transacciones | Ningún repo confirma; ningún servicio construye su UoW; el UoW no cierra la sesión |
| Carga perezosa | Prohibida: toda relación leída se precarga en el repositorio |
| SQL | Nunca por concatenación con datos del usuario |
| Errores | Mensajes propios; nunca texto de la base ni traza; ninguna entrada inválida termina en 500 |
| Unicidad | Garantizada por la base; sin consulta previa |
| Diagnóstico | Consultas visibles en consola (`SQL_ECHO=true`) |
