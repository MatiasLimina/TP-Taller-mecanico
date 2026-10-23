# Arquitectura Propuesta

## Patrones aplicados
| Patrón | Dónde | Por qué |
|--------|-------|---------|
| Arquitectura en capas por módulo | `app/modules/<m>/{models,schemas,repository,unit_of_work,service,router}.py` | Cada capa sabe lo suyo y nada más |
| Repository genérico | `core/repository.py`: `BaseRepository[T]` (sesión + clase del modelo en el constructor; `get_by_id`, `get_all`, `count`, `add`, `update`, `delete`) y `SoftDeleteRepository[T]` (filtra bajas; `get_by_id_including_deleted`, `soft_delete`) | Los genéricos se borran en runtime; `add`/`update` hacen `flush()`, nunca `commit()` |
| Repositorio de catálogo de sólo lectura | `EstadoOrdenRepository` (no hereda de `BaseRepository`) | PK no es `id`; la API no escribe |
| Unit of Work | `core/unit_of_work.py` base + un UoW por módulo | Confirma al salir, revierte ante excepción, no cierra la sesión; mismas sesión para todos los repos |
| Inyección de dependencias | `get_session`, `get_usuario_actual`, `requiere_rol`, UoW por dependencia | Router construye UoW; servicio lo abre |
| Dos grupos de rutas | `main.py`: abierto / protegido | FastAPI suma dependencias y no las resta (RN06) |
| Punto único de escritura de stock | Servicio/repo de repuestos | RN14 |
| Sesión propia para auditoría de login | `intento_acceso` | El fallo que se cuenta es el que revierte la petición (declararlo en comentario) |
| Eager loading en el repositorio | `selectinload`/`joinedload` dentro del método que lo necesita | Sin N+1 ni carga perezosa |
| Traducción de errores | `IntegrityError` → 409/422 con mensaje propio | RN18 |

## Estructura de directorios (obligatoria)
```
proyecto/
├── main.py                 # app, lifespan, dos grupos de rutas
├── seed.py                 # estado inicial conocido (vacía y carga)
├── alembic.ini             # sin credenciales
├── env.example             # todas las variables, sin secretos
├── requirements.txt
├── README.md
├── app/
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── database.py      # create_engine / sessionmaker (lifespan) y get_session
│   │   ├── security.py      # bcrypt (to_thread + semáforo), emisión/verificación JWT
│   │   ├── dependencies.py  # usuario actual, roles vigentes, control de cambio, requiere_rol
│   │   ├── repository.py    # BaseRepository[T], SoftDeleteRepository[T]
│   │   ├── paginacion.py    # envoltorio de listados y cálculo de páginas
│   │   └── unit_of_work.py  # UnitOfWork base
│   └── modules/
│       ├── health/router.py             # sólo router
│       ├── usuarios/   (models, schemas, repository, unit_of_work, service, router)  # + AsignacionRol, IntentoAcceso, EventoSeguridad
│       ├── clientes/   (…)                                                            # + Vehiculo
│       ├── repuestos/  (…)                                                            # + MovimientoStock, HistorialPrecioRepuesto
│       └── ordenes/    (…)                                                            # + EstadoOrden, ItemOrden, HistorialEstadoOrden
├── migrations/             # Alembic plantilla async; 2 versiones
└── test/                   # *.http (C-01…C-19) y solo_agregado.sql
```

## Migraciones
1. Autogenerada (`--autogenerate`): todas las tablas, índices (incl. 3 únicos parciales con `postgresql_where`), CHECKs, FKs; catálogo `estado_orden` **vacío**.
2. Manual: función + trigger "sólo agregado" sobre `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`. Cada migración lleva comentario "leída antes de aplicar".
3. `upgrade head` / `downgrade base` / `upgrade head` deben funcionar (el downgrade elimina el trigger y la función).

## Seguridad
- **Autenticación:** bcrypt con costo en Settings; hash fuera del bucle (`asyncio.to_thread`) bajo semáforo, y **antes** de abrir la transacción; JWT (PyJWT) con `sub`, `iat` (con fracción), `exp`, roles; cookie `access_token` HttpOnly, SameSite=Lax, Max-Age, Secure configurable; no se acepta `Authorization: Bearer`.
- **Autorización:** roles vigentes consultados en base por petición; 401 vs 403 siempre distintos; permisos por dueño en servicio.
- **Validación de input:** DTOs con `extra="forbid"`, tipos, límites (72 bytes en campos bcrypt, `size` 1–100); sin 500 por entrada inválida.
- **Anti-enumeración:** mismo mensaje y tiempo similar en login (hash ficticio calculado una vez en el lifespan).
- **Fuerza bruta:** RN08 por (email, IP).
- **SQL:** parámetros ligados; nunca concatenación.
- **Secrets:** sólo entorno/.env (no versionado); sin defaults para `SECRET`/password de base.
- **Integridad:** trigger sólo-agregado; opcionalmente (no pedido) rol de base sin permisos de UPDATE/DELETE como defensa en profundidad.

## Variables de entorno
| Variable | Descripción | Ejemplo | Sensible |
|----------|-------------|---------|----------|
| `POSTGRES_USER` | Usuario de base | `taller` | N |
| `POSTGRES_PASSWORD` | Contraseña de base (sin default) | — | **Y** |
| `POSTGRES_DB` | Nombre de base | `taller` | N |
| `POSTGRES_HOST` | Host | `localhost` | N |
| `POSTGRES_PORT` | Puerto | `5432` | N |
| `SECRET_KEY` (nombre sugerido) | Clave de firma JWT (sin default) | generada con `secrets.token_urlsafe` | **Y** |
| `ACCESS_TOKEN_EXPIRE_*` (sugerido) | Duración del token (la consigna muestra 1800 s) | `1800` | N |
| `BCRYPT_COST` (sugerido) | Costo de bcrypt | `12` | N |
| `BCRYPT_MAX_CONCURRENCY` (sugerido) | Tamaño del semáforo | `4` | N |
| `POOL_SIZE` / `MAX_OVERFLOW` (sugeridos) | Pool del motor | `5` / `10` | N |
| `COOKIE_SECURE` (sugerido) | Flag Secure de la cookie | `false` en dev | N |
| `SQL_ECHO` | Mostrar consultas en consola | `true` | N |

> Los nombres marcados "sugerido" no están fijados por la consigna; sólo `POSTGRES_*` y `SQL_ECHO` son nombrados explícitamente.
