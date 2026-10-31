# API de Gestión de Taller Mecánico — Programación III

API web asincrónica para la gestión integral de un taller mecánico (Programación III — Capítulos 1 a 6): registro y autenticación de usuarios con JWT en cookie `HttpOnly`, control de acceso por rol vigente en base de datos y por relación de pertenencia («lo propio»), administración de clientes y vehículos con baja lógica e índices únicos parciales, catálogo de repuestos con control de stock e historial de precios, órdenes de trabajo con máquina de estados transaccional (`SELECT … FOR UPDATE`), tablas de auditoría de sólo agregado protegidas por disparador en PostgreSQL y lecturas con carga anticipada sin problema N+1.

## 1. Integrantes del equipo

**Nombre del grupo:** GordosProgramacion

| Integrante | Usuario de GitHub |
|------------|-------------------|
| **Matías Limina** | [@MatiasLimina](https://github.com/MatiasLimina) |
| **Nicolás Lionel Monjelardi** | [@nicolasmonjelardi](https://github.com/nicolasmonjelardi) |
| **Lautaro Agustín Agüero** | [@LautaroAguero01](https://github.com/LautaroAguero01) |

---

## 2. Stack tecnológico y arquitectura

### Tecnologías y versiones

| Componente | Tecnología / Paquete | Versión |
|------------|----------------------|---------|
| Lenguaje | Python | `3.12+` |
| Framework HTTP | FastAPI + Uvicorn | `>=0.111` / `>=0.30` |
| ORM y esquemas | SQLModel + SQLAlchemy (`asyncio`) + Pydantic v2 | `>=0.0.45` / `>=2.0` |
| Driver asincrónico PostgreSQL | `asyncpg` | `>=0.30` |
| Base de datos | PostgreSQL | `16+` |
| Migraciones de esquema | Alembic | `>=1.13` |
| Configuración tipada | `pydantic-settings` | `>=2.0` |
| Seguridad | `bcrypt` (en `asyncio.to_thread` con semáforo) + `PyJWT` (`HS256`) | `>=4.0` / `>=2.8` |
| Linter y formateador | Ruff (`requirements-dev.txt`, configurado en `ruff.toml`) | `0.15.10` |

### Arquitectura en capas

Cada módulo de negocio en `app/modules/<modulo>/` respeta la separación de responsabilidades en 5 capas:

```text
Router (HTTP / FastAPI Depends)
  └── Service (reglas de negocio y permisos por relación; sin Request/Response/HTTPException)
        └── UnitOfWork (transacción atómica única por operación; commit al salir sin excepción)
              └── Repository (consultas SQLModel/SQLAlchemy parametrizadas y precarga explícita)
                    └── Model (tablas SQLModel con lazy="raise" en todas las relaciones)
```

### Estructura de directorios

```text
TP-Taller-mecanico/
├── main.py                      # Punto de entrada FastAPI, lifespan y montaje de rutas_abiertas / rutas_protegidas
├── seed.py                      # Recarga determinista del estado inicial de desarrollo y pruebas (TRUNCATE + INSERT)
├── alembic.ini                  # Configuración de Alembic (sin URL cableada; migrations/env.py usa get_settings())
├── env.example                  # Plantilla de variables de entorno (sin secretos reales)
├── requirements.txt             # Dependencias de ejecución con cotas inferiores (>=)
├── requirements-dev.txt         # Herramientas de desarrollo y verificación (ruff, httpx)
├── ruff.toml                    # Reglas de estilo y análisis estático
├── app/
│   ├── core/
│   │   ├── config.py            # Settings tipados (pydantic-settings), validación de secretos y URL asyncpg
│   │   ├── database.py          # Creación de AsyncEngine y async_sessionmaker (expire_on_commit=False)
│   │   ├── dependencies.py      # Dependencias de sesión, autenticar, exigir_password_al_dia y requiere_rol
│   │   ├── errores.py           # Excepciones de dominio (NoEncontrado, Conflicto, SinPermiso, etc.) y handlers HTTP
│   │   ├── paginacion.py        # PaginacionDep (page>=1, 1<=size<=100), Pagina[T] y validación de página fuera de rango
│   │   ├── repository.py        # BaseRepository genérico
│   │   ├── schemas.py           # EntradaBase (extra="forbid"), SalidaBase y tipos comunes (IdRuta, TextoNoVacio)
│   │   ├── security.py          # bcrypt con semáforo en hilo aparte, JWT HS256 con jti y crear_hash_ficticio
│   │   └── unit_of_work.py      # UnitOfWork transaccional base
│   └── modules/
│       ├── modelos.py           # Importador central de las 13 tablas para SQLModel.metadata y Alembic
│       ├── health/              # GET /health/live y GET /health/ready (SELECT 1)
│       ├── usuarios/            # Auth (/auth/*), personal (/usuarios/*), roles en vivo y auditoría (/eventos)
│       ├── clientes/            # Fichas de cliente (/clientes), vehículos (/vehiculos) y /mis-vehiculos
│       ├── repuestos/           # Catálogo (/repuestos), reposición (/reponer), movimientos y precios históricos
│       └── ordenes/             # Órdenes (/ordenes), transiciones (iniciar/terminar/cancelar), /estados-orden y /mis-ordenes
├── migrations/
│   ├── env.py                   # Ejecución asincrónica de Alembic conectada a SQLModel.metadata y get_settings()
│   └── versions/
│       ├── 1c921a1fe62f_esquema_inicial.py   # Revisión 1 (autogenerada y revisada): 13 tablas, CHECKs, FKs e índices parciales
│       └── 9141e6428bad_solo_agregado.py     # Revisión 2 (escrita a mano): función y disparadores trg_solo_agregado
└── test/
    ├── casos_pdf.http           # Recorrido integrador C-01..C-19 + matriz RBAC (corre directo tras python seed.py)
    ├── solo_agregado.sql        # Evidencia SQL del caso C-14 (6 rechazos P0001 y 1 rechazo 23503 con ROLLBACK)
    ├── evidencia_c14.txt        # Salida capturada de psql -f test/solo_agregado.sql
    ├── evidencia_c15.txt        # Salida capturada con SQL_ECHO=true en GET /ordenes/1 (2 ítems) y GET /ordenes/3 (4 ítems)
    ├── seed.http                # Verificación HTTP del estado inicial del seed (19 casos)
    ├── seed.sql                 # Consultas SQL de sólo lectura sobre las 13 tablas sembradas
    ├── health.http              # Casos de /health/live y /health/ready
    ├── auth.http                # Suite exhaustiva de registro, login y límite de intentos (C-07)
    ├── sesion.http              # Suite exhaustiva de guardas de sesión, /auth/yo y cambio de contraseña (C-08)
    ├── personal.http            # Suite exhaustiva de alta de personal, roles con vencimiento/revocación y /eventos (C-09)
    ├── clientes.http            # Suite exhaustiva de clientes, vehículos y baja lógica con reutilización de patente (C-10)
    ├── repuestos.http           # Suite exhaustiva de catálogo de repuestos, filtros y baja lógica (C-11)
    ├── stock.http               # Suite exhaustiva de reposición de stock e historial de precios (C-12)
    ├── ordenes.http             # Suite exhaustiva de alta de órdenes y catálogo de estados (C-13)
    ├── transiciones.http        # Suite exhaustiva de iniciar, terminar con bloqueo pesimista y cancelar orden (C-14)
    ├── lecturas_ordenes.http    # Suite exhaustiva de GET /ordenes, GET /ordenes/{id} y GET /mis-ordenes (C-15)
    └── verificar_security_core.py # Verificación autónoma de primitivas de seguridad (bcrypt, JWT, semáforo)
```

---

## 3. Puesta en marcha paso a paso desde cero (Flujo 9, US-070)

### Prerrequisitos

- **Python 3.12** o superior.
- **PostgreSQL 16** (o 14+) en ejecución y una base de datos vacía creada (por ejemplo `taller` para el usuario `taller`):
  ```sql
  CREATE USER taller WITH PASSWORD '<tu_password_local>';
  CREATE DATABASE taller OWNER taller;
  ```
- Extensión **REST Client** de VS Code (`humao.rest-client`) o el cliente HTTP de JetBrains para ejecutar los archivos `.http` de `test/`.

### Paso 1 — Crear el entorno virtual e instalar dependencias

Desde la raíz del proyecto en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Paso 2 — Configurar el archivo `.env` y generar `SECRET_KEY`

Copiar la plantilla `env.example` a `.env` usando `Copy-Item`:

> [!IMPORTANT]
> En PowerShell **no usar redirección `>`** (`cat env.example > .env`), porque escribe en codificación UTF-16 y rompe la lectura de `.env`. Usar siempre `Copy-Item`. El archivo `.env` está excluido en `.gitignore` y **nunca** debe subirse al repositorio.

```powershell
Copy-Item env.example .env
```

Generar una clave aleatoria criptográficamente segura para `SECRET_KEY` (mínimo 32 caracteres):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Abrir `.env` y completar los dos secretos obligatorios que vienen vacíos en `env.example`:

- `POSTGRES_PASSWORD=<contraseña de tu usuario de PostgreSQL>`
- `SECRET_KEY=<cadena impresa por secrets.token_urlsafe(64)>`

#### Variables de entorno definidas en `env.example`

| Variable | Valor en `env.example` | Descripción |
|----------|------------------------|-------------|
| `POSTGRES_USER` | `taller` | Usuario de conexión a PostgreSQL |
| `POSTGRES_PASSWORD` | *(vacío — obligatorio)* | Contraseña del usuario de PostgreSQL (falla al arrancar si falta o está en blanco) |
| `POSTGRES_DB` | `taller` | Nombre de la base de datos |
| `POSTGRES_HOST` | `localhost` | Host del servidor PostgreSQL |
| `POSTGRES_PORT` | `5432` | Puerto del servidor PostgreSQL (`1..65535`) |
| `SECRET_KEY` | *(vacío — obligatorio)* | Clave secreta para firmar JWT HS256 (mínimo 32 caracteres no blancos) |
| `ACCESS_TOKEN_EXPIRE_SECONDS` | `1800` | Vigencia del token de sesión y `Max-Age` de la cookie `access_token` (30 min) |
| `BCRYPT_COST` | `12` | Costo logarítmico de `bcrypt` (`4..31`) |
| `BCRYPT_MAX_CONCURRENCY` | `4` | Máximo de cálculos `bcrypt` concurrentes en el semáforo del proceso |
| `COOKIE_SECURE` | `false` | Atributo `Secure` de la cookie (`true` detrás de HTTPS) |
| `POOL_SIZE` | `5` | Tamaño base del pool de conexiones de SQLAlchemy |
| `MAX_OVERFLOW` | `10` | Conexiones adicionales permitidas sobre `POOL_SIZE` |
| `SQL_ECHO` | `false` | Imprime en consola las sentencias SQL ejecutadas (útil para verificar el caso C-15). `env.example` lo trae en `true`; ponelo en `false` si no necesitás ver el SQL |

### Paso 3 — Aplicar las migraciones de Alembic

La aplicación no usa `SQLModel.metadata.create_all()` en ningún archivo: todo el esquema y los disparadores se gestionan exclusivamente con Alembic:

```powershell
alembic upgrade head
```

Esto aplica en orden las dos revisiones de `migrations/versions/`:

1. `1c921a1fe62f_esquema_inicial.py` (generada con `alembic revision --autogenerate` y revisada antes de aplicar): crea las 13 tablas del dominio, claves foráneas, restricciones `CHECK` y los 3 índices únicos parciales (`ix_asignacion_rol_usuario_rol_activa`, `ix_vehiculo_patente_activo`, `ix_repuesto_codigo_activo`). Deja el catálogo `estado_orden` vacío (0 filas).
2. `9141e6428bad_solo_agregado.py` (escrita a mano y revisada antes de aplicar): crea la función `rechazar_cambio_solo_agregado()` y el disparador `trg_solo_agregado` (`BEFORE UPDATE OR DELETE FOR EACH ROW`) sobre las tres tablas de auditoría: `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`.

Para comprobar en cualquier momento la reversibilidad completa de las migraciones y la sincronización entre modelos y esquema:

```powershell
alembic downgrade base
alembic upgrade head
alembic check
```

### Paso 4 — Cargar los datos iniciales de prueba (`python seed.py`)

```powershell
python seed.py
```

> [!WARNING]
> **ADVERTENCIA — `python seed.py` borra todos los datos del dominio:**
> Este script ejecuta `TRUNCATE TABLE … RESTART IDENTITY CASCADE` sobre las **13 tablas del dominio** de la base configurada en `.env` y recarga desde cero el estado inicial reproducible con IDs deterministas (`1, 2, …`). **No debe ejecutarse nunca contra una base con datos reales.** Es una herramienta exclusiva de desarrollo y pruebas y se corre antes de ejecutar cada archivo `.http`.

Salida esperada:

```text
Se reemplazaron todos los datos del dominio de la base configurada.
Seed cargado: estado_orden=4 evento_seguridad=1 intento_acceso=0 repuesto=4 usuario=7 asignacion_rol=7 cliente=2 historial_precio_repuesto=1 vehiculo=3 orden_trabajo=2 historial_estado_orden=3 item_orden=3 movimiento_stock=4
```

### Paso 5 — Levantar el servidor

```powershell
uvicorn main:app --port 8000
```

Para asegurarse de ver en la consola las sentencias SQL emitidas por SQLAlchemy (por ejemplo al verificar el caso **C-15**):

```powershell
$env:SQL_ECHO="true"
uvicorn main:app --port 8000
```

Con el servidor en marcha:

- Liveness check: `http://localhost:8000/health/live` → `200 {"estado": "vivo"}`
- Readiness check (verifica la base con `SELECT 1`): `http://localhost:8000/health/ready` → `200 {"estado": "listo"}`
- Documentación interactiva OpenAPI: `http://localhost:8000/docs`

---

## 4. Estado inicial cargado por `python seed.py`

### 4.1 Catálogo `estado_orden` (4 filas)

| `codigo` | `descripcion` | `posicion` | `es_final` |
|----------|---------------|------------|------------|
| `PENDIENTE` | Orden registrada, a la espera de un mecánico | `1` | `false` |
| `EN_REPARACION` | Un mecánico está trabajando en el vehículo | `2` | `false` |
| `TERMINADA` | Reparación terminada; repuestos descontados del stock | `3` | `true` |
| `CANCELADA` | Orden cancelada sin reparación | `4` | `true` |

### 4.2 Usuarios y roles iniciales (`usuario` + `asignacion_rol`, 7 filas cada una)

| `id` | `email` | `nombre` | Rol vigente | Contraseña de prueba | `debe_cambiar_password` |
|------|---------|----------|-------------|----------------------|-------------------------|
| `1` | `admin@example.com` | Adriana Admin | `ADMIN` | `ClaveSegura1` | `false` |
| `2` | `admin2@example.com` | Alberto Admin | `ADMIN` | `ClaveSegura1` | `false` |
| `3` | `recepcion@example.com` | Rita Recepción | `RECEPCION` | `ClaveSegura1` | `false` |
| `4` | `mecanico@example.com` | Mario Mecánico | `MECANICO` | `ClaveSegura1` | `false` |
| `5` | `mecanico2@example.com` | Marta Mecánica | `MECANICO` | `ClaveSegura1` | `false` |
| `6` | `cliente@example.com` | Laura Martínez | `CLIENTE` | `ClaveSegura1` | `false` |
| `7` | `nuevo@example.com` | Nicolás Nuevo | `MECANICO` | `Provisoria1` | `true` |

### 4.3 Fichas de cliente (`cliente`, 2 filas) y vehículos (`vehiculo`, 3 filas)

| `cliente.id` | `usuario_id` | `nombre` | `documento` | `telefono` | Vehículos (`id` — `patente` — marca/modelo/año) |
|--------------|--------------|----------|-------------|------------|-------------------------------------------------|
| `1` | `6` (`cliente@example.com`) | Laura Martínez | `28111222` | `1144440001` | `1` — `AB123CD` (Toyota Corolla 2019)<br>`2` — `AC456EF` (Volkswagen Gol 2015, **sin órdenes**) |
| `2` | `null` *(ficha presencial sin cuenta web)* | Jorge Pérez | `25111333` | `1144440002` | `3` — `AD789GH` (Ford Fiesta 2012) |

### 4.4 Repuestos (`repuesto`, 4 filas), `movimiento_stock` (4 filas) e `historial_precio_repuesto` (1 fila)

| `id` | `codigo` | `descripcion` | `precio` | `stock` | Movimiento inicial (`motivo="Stock inicial"`) | Historial de precios inicial |
|------|----------|---------------|----------|---------|-----------------------------------------------|------------------------------|
| `1` | `FIL-ACE-01` | Filtro de aceite | `8500.00` | `10` | `+10` (`usuario_id=1`) | `8000.00 -> 8500.00` (`usuario_id=1`) |
| `2` | `PAS-FRE-DEL` | Pastillas de freno delanteras | `32000.00` | `4` | `+4` (`usuario_id=1`) | *(sin cambios previos)* |
| `3` | `BUJ-01` | Bujía | `4500.00` | `2` | `+2` (`usuario_id=1`) | *(sin cambios previos)* |
| `4` | `ACE-5W30-1L` | Aceite 5W30 por litro | `12000.00` | `20` | `+20` (`usuario_id=1`) | *(sin cambios previos)* |

### 4.5 Órdenes de trabajo iniciales (`orden_trabajo`, 2 filas; `item_orden`, 3 filas; `historial_estado_orden`, 3 filas)

| `id` | `vehiculo_id` | Cliente / Patente | `mecanico_id` | `estado` | `total` | Ítems (`item_orden`) | Historial (`historial_estado_orden`) |
|------|---------------|-------------------|---------------|----------|---------|----------------------|--------------------------------------|
| `1` | `1` | Laura Martínez / `AB123CD` | `null` | `PENDIENTE` | `56500.00` | `FIL-ACE-01` × 1 (`8500.00`)<br>`ACE-5W30-1L` × 4 (`12000.00`) | `null -> PENDIENTE` (`usuario_id=3`) |
| `2` | `3` | Jorge Pérez / `AD789GH` | `4` (`mecanico@`) | `EN_REPARACION` | `18000.00` | `BUJ-01` × 4 (`4500.00`) *(stock actual = 2, listo para probar **C-11** y **C-12**)* | `null -> PENDIENTE` (`usuario_id=3`),<br>`PENDIENTE -> EN_REPARACION` (`usuario_id=4`) |

Además se registra 1 fila en `evento_seguridad` (`actor="SISTEMA"`, `accion="Carga de los datos iniciales"`).

---

## 5. Matriz de endpoints y permisos (RBAC)

La aplicación monta sus **28 endpoints** en dos grupos en [`main.py`](main.py):

- **Grupo abierto (`rutas_abiertas`)**: `/health/*` y `/auth/*`. No aplica la guarda `exigir_password_al_dia`, lo que permite que un usuario con `debe_cambiar_password=true` consulte `/auth/yo`, cierre sesión en `/auth/logout` o actualice su clave en `/auth/cambiar-password`.
- **Grupo protegido (`rutas_protegidas`)**: lleva montada una única vez la dependencia `Depends(exigir_password_al_dia)`. Toda petición sin cookie válida recibe `401` y toda sesión con `debe_cambiar_password=true` recibe `403 {"detail": "Debe cambiar la contraseña antes de continuar"}` antes de evaluar permisos de ruta o parámetros.
- **Roles consultados en vivo (RN04)**: `requiere_rol(...)` consulta en cada petición las filas de `asignacion_rol` con `revocada_en IS NULL` y `(vence_en IS NULL OR vence_en > now())`. El reclamo `roles` del JWT es meramente informativo.

| # | Método y ruta | Grupo | Quién puede acceder | Respuestas principales |
|---|---------------|-------|---------------------|------------------------|
| 1 | `GET /health/live` | Abierto | Público (sin sesión) | `200` |
| 2 | `GET /health/ready` | Abierto | Público (ejecuta `SELECT 1`) | `200`, `503` |
| 3 | `POST /auth/registro` | Abierto | Público (crea `usuario` + rol `CLIENTE` + `cliente`) | `201`, `409`, `422` |
| 4 | `POST /auth/login` | Abierto | Público (emite cookie `HttpOnly` `access_token`; ventana de 5 fallos / 60 s) | `200`, `401`, `422`, `429` (`Retry-After`) |
| 5 | `POST /auth/logout` | Abierto | Cualquier sesión válida (incluso con cambio de clave pendiente) | `200` (borra cookie) |
| 6 | `GET /auth/yo` | Abierto | Cualquier sesión válida (muestra `roles_vigentes` vs `roles_token`) | `200`, `401` |
| 7 | `POST /auth/cambiar-password` | Abierto | Cualquier sesión válida (invalida tokens previos y emite cookie nueva) | `200`, `400`, `401`, `422` |
| 8 | `POST /usuarios` | Protegido | Sólo `ADMIN` (crea personal con `debe_cambiar_password=true`) | `201`, `401`, `403`, `409`, `422` |
| 9 | `GET /usuarios/{usuario_id}/roles` | Protegido | Sólo `ADMIN` | `200`, `401`, `403`, `404`, `422` |
| 10 | `POST /usuarios/{usuario_id}/roles` | Protegido | Sólo `ADMIN` (`vence_en` opcional futuro con TZ) | `201`, `401`, `403`, `404`, `409`, `422` |
| 11 | `DELETE /usuarios/{usuario_id}/roles/{rol}` | Protegido | Sólo `ADMIN` (prohíbe autorrevocación de `ADMIN` y dejar al sistema sin `ADMIN` permanente) | `200`, `401`, `403`, `404`, `409`, `422` |
| 12 | `GET /eventos` | Protegido | Sólo `ADMIN` (paginado) | `200`, `401`, `403`, `422` |
| 13 | `POST /clientes` | Protegido | `RECEPCION` o `ADMIN` (ficha presencial sin usuario) | `201`, `401`, `403`, `409`, `422` |
| 14 | `GET /clientes` | Protegido | `RECEPCION` o `ADMIN` (paginado + búsqueda `?q=`) | `200`, `401`, `403`, `422` |
| 15 | `GET /clientes/{cliente_id}` | Protegido | `RECEPCION` o `ADMIN` (incluye vehículos activos) | `200`, `401`, `403`, `404`, `422` |
| 16 | `POST /clientes/{cliente_id}/vehiculos` | Protegido | `RECEPCION` o `ADMIN` | `201`, `401`, `403`, `404`, `409`, `422` |
| 17 | `DELETE /vehiculos/{vehiculo_id}` | Protegido | `RECEPCION` o `ADMIN` (baja lógica; `409` si tiene órdenes) | `204`, `401`, `403`, `404`, `409`, `422` |
| 18 | `GET /mis-vehiculos` | Protegido | Cualquier usuario con contraseña al día (filtra por `actual.id`) | `200`, `401`, `403` |
| 19 | `POST /repuestos` | Protegido | Sólo `ADMIN` (crea repuesto y movimiento inicial si `stock > 0`) | `201`, `401`, `403`, `409`, `422` |
| 20 | `GET /repuestos` | Protegido | `ADMIN`, `RECEPCION` o `MECANICO` (paginado + `?q=`) | `200`, `401`, `403`, `422` |
| 21 | `GET /repuestos/{repuesto_id}` | Protegido | `ADMIN`, `RECEPCION` o `MECANICO` | `200`, `401`, `403`, `404`, `422` |
| 22 | `PATCH /repuestos/{repuesto_id}` | Protegido | Sólo `ADMIN` (no admite `stock`; si cambia `precio`, inserta en `historial_precio_repuesto`) | `200`, `401`, `403`, `404`, `422` |
| 23 | `DELETE /repuestos/{repuesto_id}` | Protegido | Sólo `ADMIN` (baja lógica; `409` si tiene `stock > 0`) | `204`, `401`, `403`, `404`, `409`, `422` |
| 24 | `POST /repuestos/{repuesto_id}/reponer` | Protegido | Sólo `ADMIN` (`FOR UPDATE` + inserta en `movimiento_stock`) | `200`, `401`, `403`, `404`, `422` |
| 25 | `GET /repuestos/{repuesto_id}/movimientos` | Protegido | Sólo `ADMIN` (paginado) | `200`, `401`, `403`, `404`, `422` |
| 26 | `GET /repuestos/{repuesto_id}/precios` | Protegido | Sólo `ADMIN` (paginado) | `200`, `401`, `403`, `404`, `422` |
| 27 | `GET /estados-orden` | Protegido | Cualquier usuario con contraseña al día (4 estados ordenados por `posicion`) | `200`, `401`, `403` |
| 28 | `POST /ordenes` | Protegido | `RECEPCION` o `ADMIN` (copia `precio_unitario` de cada repuesto; inicia en `PENDIENTE`) | `201`, `401`, `403`, `404`, `409`, `422` |
| 29 | `POST /ordenes/{orden_id}/iniciar` | Protegido | **Sólo `MECANICO`** (`ADMIN` sin `MECANICO` recibe `403`; `PENDIENTE -> EN_REPARACION`) | `200`, `401`, `403`, `404`, `409`, `422` |
| 30 | `POST /ordenes/{orden_id}/terminar` | Protegido | **Sólo el `MECANICO` asignado** a la orden (`EN_REPARACION -> TERMINADA`, descuenta stock con `FOR UPDATE` en orden de `repuesto_id` y agenda aviso en `BackgroundTasks`) | `200`, `401`, `403`, `404`, `409`, `422` |
| 31 | `POST /ordenes/{orden_id}/cancelar` | Protegido | `RECEPCION`, `ADMIN` o el **cliente dueño del vehículo** (`PENDIENTE` o `EN_REPARACION -> CANCELADA`, sin tocar stock) | `200`, `401`, `403`, `404`, `409`, `422` |
| 32 | `GET /ordenes` | Protegido | `RECEPCION`, `ADMIN` o `MECANICO` (paginado + filtro opcional `?estado=`) | `200`, `401`, `403`, `422` |
| 33 | `GET /ordenes/{orden_id}` | Protegido | Personal (`RECEPCION`, `ADMIN`, `MECANICO`) o **cliente dueño del vehículo** (RN17; 5 `SELECT` fijos sin N+1) | `200`, `401`, `403`, `404`, `422` |
| 34 | `GET /mis-ordenes` | Protegido | Cualquier usuario con contraseña al día (filtra siempre por `actual.id`, RN17) | `200`, `401`, `403`, `422` |

*(Nota: la tabla desglosa por método HTTP + ruta las 34 operaciones expuestas sobre las 28 rutas montadas).*

---

## 6. Casos de prueba (`.http` y `.sql` en `test/`)

### Cómo ejecutar el recorrido integrador sobre `python seed.py`

El archivo [`test/casos_pdf.http`](test/casos_pdf.http) fue diseñado para cumplir de forma directa la instrucción del PDF de consigna (*«Antes de cada archivo se corre `python seed.py`»*):

1. Asegurar que el servidor esté corriendo (`uvicorn main:app --port 8000`).
2. Ejecutar en la terminal:
   ```powershell
   python seed.py
   ```
3. Abrir [`test/casos_pdf.http`](test/casos_pdf.http) en VS Code (con la extensión **REST Client**) y ejecutar las **72 peticiones** en orden de arriba abajo (`Send Request` en cada `### N.`).
   - Todas las peticiones llevan `# @no-cookie-jar` (la sesión nunca depende del jar implícito del cliente sino del encabezado explícito `Cookie: {{<login>.response.headers.Set-Cookie}}`).
   - No requiere ejecutar ningún comando `psql` entre peticiones.
   - Para volver a ejecutar el archivo desde el principio, basta con correr nuevamente `python seed.py`.

**Archivos que corren directamente después de `python seed.py` (sin `psql` intermedio):**

- [`test/casos_pdf.http`](test/casos_pdf.http) — 72 peticiones: logins del seed, matriz RBAC completa y casos **C-01 a C-19** (salvo C-14 que es SQL directo).
- [`test/seed.http`](test/seed.http) — 19 peticiones de verificación del estado inicial sembrado por `seed.py`.
- [`test/lecturas_ordenes.http`](test/lecturas_ordenes.http) — 70 peticiones de `GET /ordenes`, `GET /ordenes/{id}` y `GET /mis-ordenes`.
- [`test/health.http`](test/health.http) — 2 peticiones de `/health/live` y `/health/ready`.
- [`test/solo_agregado.sql`](test/solo_agregado.sql) — prueba SQL del caso **C-14** en transacción con `ROLLBACK`.
- [`test/seed.sql`](test/seed.sql) — 14 consultas SQL de sólo lectura sobre las 13 tablas tras `python seed.py`.

**Suites exhaustivas por módulo (`C-07` a `C-14`):**

Los archivos [`test/auth.http`](test/auth.http), [`test/sesion.http`](test/sesion.http), [`test/personal.http`](test/personal.http), [`test/clientes.http`](test/clientes.http), [`test/repuestos.http`](test/repuestos.http), [`test/stock.http`](test/stock.http), [`test/ordenes.http`](test/ordenes.http) y [`test/transiciones.http`](test/transiciones.http) contienen las baterías exhaustivas de cada módulo (43 a 97 casos por archivo) y documentan en sus propios comentarios los comandos `psql` puntuales que utilizan para forzar escenarios de borde adicionales (como vencimientos en segundos o vaciados aislados).

### Índice de los 19 casos de prueba mínimos del PDF (`C-01` a `C-19`)

| Caso PDF | Qué demuestra | Resultado esperado | Casos en [`test/casos_pdf.http`](test/casos_pdf.http) | Suite específica en `test/` |
|----------|---------------|--------------------|-------------------------------------------------------|-----------------------------|
| **C-01** | Parámetro de ruta que no es entero (`GET /ordenes/abc`, `GET /repuestos/abc`) | `422` en la validación de entrada (`int_parsing`) sin ejecutar el servicio | Casos **8–9** | [`test/lecturas_ordenes.http`](test/lecturas_ordenes.http), [`test/repuestos.http`](test/repuestos.http) |
| **C-02** | Registro de cliente nuevo; reintento con correo repetido y con documento repetido (incluyendo ficha presencial sin usuario, RN02) | `201` la primera vez (`usuario` + rol `CLIENTE` + `cliente`); `409` en las repetidas sin dejar filas sueltas | Casos **10–14** | [`test/auth.http`](test/auth.http) |
| **C-03** | Login exitoso; ruta protegida sin cookie, con `Authorization: Bearer` y con la cookie `HttpOnly` | Login devuelve `Set-Cookie: access_token=…; HttpOnly` y cuerpo sin el JWT; ruta protegida da `401` sin cookie o con `Bearer` y `200` con la cookie | Casos **1, 15–17** | [`test/sesion.http`](test/sesion.http) |
| **C-04** | Login con contraseña incorrecta para correo registrado y para correo NO registrado | `401` con el mismo mensaje (`"Correo o contraseña incorrectos"`) y tiempo parejo (hash ficticio, RN09) | Casos **18–19** | [`test/auth.http`](test/auth.http) |
| **C-05** | 6 intentos de login fallidos seguidos desde el mismo origen dentro del minuto | Los primeros 5 responden `401`; el 6.º responde `429` con cabecera `Retry-After` sin calcular `bcrypt` | Casos **67–72** | [`test/auth.http`](test/auth.http) |
| **C-06** | `GET /ordenes/1` como el cliente dueño (Laura) y `GET /ordenes/2` como cliente ajeno ( más matriz RBAC `401`/`403`) | `200` para la dueña; `403` para otro cliente (`"Sólo el personal del taller o el dueño del vehículo puede ver la orden"`) | Casos **20–25** | [`test/lecturas_ordenes.http`](test/lecturas_ordenes.http), [`test/sesion.http`](test/sesion.http) |
| **C-07** | Revocar un rol a un usuario que ya tiene sesión abierta y repetir petición con la misma cookie; validaciones de `vence_en` | `403` inmediato en la ruta que exigía el rol revocado (RN04); `GET /auth/yo` muestra `roles_vigentes: []` y `roles_token: ["ADMIN"]`; la fila sigue en `asignacion_rol` con `revocada_en` | Casos **26–31** | [`test/personal.http`](test/personal.http) |
| **C-08** | Un administrador intenta revocarse su propio rol `ADMIN` (`DELETE /usuarios/1/roles/ADMIN`) | `409` `"Un administrador no puede revocarse su propio rol ADMIN"` (RN05) | Caso **32** | [`test/personal.http`](test/personal.http) |
| **C-09** | Login de usuario con `debe_cambiar_password=true`, cambio de contraseña enseguida y uso de la cookie anterior | Antes del cambio `/ordenes` da `403` (caso 21); `/auth/cambiar-password` da `200` con cookie nueva que ya funciona (caso 35) y la cookie anterior recibe `401` (caso 36, RN07) | Casos **21, 33–36** | [`test/sesion.http`](test/sesion.http) |
| **C-10** | Crear una orden con dos ítems válidos y otra con un repuesto inexistente (`9999`) | La válida responde `201` en `PENDIENTE` con precios copiados, `total` e historial inicial; la inválida responde `409` sin crear la orden ni sus ítems | Casos **50–51** | [`test/ordenes.http`](test/ordenes.http) |
| **C-11** | Terminar la orden #2 cuando `BUJ-01` tiene stock `2` y el ítem pide `4` | `409` por stock insuficiente; el stock sigue en `2`, la orden sigue `EN_REPARACION` y no se agrega fila a `movimiento_stock` ni a `historial_estado_orden` | Casos **52–54** | [`test/transiciones.http`](test/transiciones.http) |
| **C-12** | Reponer `2` unidades de `BUJ-01` y volver a terminar la orden #2 con el mecánico asignado | `200` en `TERMINADA`, stock de `BUJ-01` descontado a `0`, movimiento `-4` con `orden_id=2` y aviso simulado en consola tras ~0,5 s | Casos **55–57** | [`test/transiciones.http`](test/transiciones.http) |
| **C-13** | Cancelar una orden `PENDIENTE` (por cliente ajeno vs dueña) e intentar cancelar una `TERMINADA` | `403` para cliente ajeno; `200` (`CANCELADA`) para la dueña sin tocar stock; `409` sobre la orden `TERMINADA` (estado final) | Casos **58–60** | [`test/transiciones.http`](test/transiciones.http) |
| **C-14** | En `psql`, intentar `UPDATE` y `DELETE` sobre las 3 tablas de historial e insertar una orden con estado fuera del catálogo | 6 rechazos `P0001` del disparador `trg_solo_agregado` y 1 rechazo `23503` de `fk_orden_trabajo_estado_estado_orden`; las filas válidas siguen intactas (`1 \| 1 \| 1`) | SQL directo ([`test/solo_agregado.sql`](test/solo_agregado.sql)) | [`test/solo_agregado.sql`](test/solo_agregado.sql), [`test/evidencia_c14.txt`](test/evidencia_c14.txt) |
| **C-15** | Consultar con `SQL_ECHO=true` el detalle de una orden con 2 ítems (`GET /ordenes/1`) y otra con 4 ítems (`GET /ordenes/4`, creada por el caso 61; en `evidencia_c15.txt` y en `lecturas_ordenes.http` la orden de 4 ítems es la `/ordenes/3`) | Ambas peticiones emiten exactamente la **misma cantidad de sentencias `SELECT` (5)** en consola (sin N+1) | Casos **61–63** | [`test/lecturas_ordenes.http`](test/lecturas_ordenes.http), [`test/evidencia_c15.txt`](test/evidencia_c15.txt) |
| **C-16** | `GET /repuestos` con comillas/SQL (`' OR '1'='1`), página fuera de rango, `size=500`; `PATCH` sólo de descripción y `PATCH` intentando mandar `stock` | La búsqueda literal devuelve `200` (`items: []`); página inexistente y `size=500` dan `422`; el primer `PATCH` sólo cambia `descripcion` (`200`) y el que incluye `stock` da `422` (`extra_forbidden`) | Casos **37–42** | [`test/repuestos.http`](test/repuestos.http) |
| **C-17** | `GET /estados-orden` y filtro `GET /ordenes?estado=REABIERTA` | `GET /estados-orden` devuelve los 4 estados ordenados por `posicion` (`TERMINADA` y `CANCELADA` con `es_final: true`); el filtro por un estado no declarado responde `422` | Casos **47–49** | [`test/ordenes.http`](test/ordenes.http), [`test/lecturas_ordenes.http`](test/lecturas_ordenes.http) |
| **C-18** | Cambiar el precio de un repuesto con `PATCH`, editar después sólo la descripción y consultar `GET /repuestos/{id}/precios` como `ADMIN` y como `RECEPCION` | El historial (con el línea inicial del seed para `FIL-ACE-01` y la nueva línea `32000.00 -> 35000.00` en `PAS-FRE-DEL`) sólo agrega fila cuando cambia el precio; `RECEPCION` recibe `403` | Casos **43–46** | [`test/stock.http`](test/stock.http) |
| **C-19** | Dar de baja un vehículo sin órdenes (`DELETE /vehiculos/2`, patente `AC456EF`), crear otro con la misma patente e intentar un segundo vigente con la misma patente | La baja responde `204` (`borrado_en` no nulo); el nuevo vehículo con patente `AC456EF` responde `201`; el segundo vigente con la misma patente responde `409` | Casos **64–66** | [`test/clientes.http`](test/clientes.http) |

---

## 7. Evidencia del caso C-14 (sólo agregado y clave foránea de `estado_orden`)

El script [`test/solo_agregado.sql`](test/solo_agregado.sql) ejecuta dentro de una transacción terminada en `ROLLBACK` las pruebas de `UPDATE` y `DELETE` sobre las tres tablas protegidas por `trg_solo_agregado` (`historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`) y un `INSERT` en `orden_trabajo` con un estado inexistente (`'INEXISTENTE'`).

Comando para reproducirlo sobre la base migrada:

```powershell
psql -h localhost -p 5432 -U taller -d taller -f test/solo_agregado.sql
```

La salida completa está versionada en [`test/evidencia_c14.txt`](test/evidencia_c14.txt). Fragmento de los 6 rechazos `P0001`, el rechazo `23503`, la comprobación de filas intactas y el `ROLLBACK`:

```text
-- --- 1. historial_estado_orden ---
-- Esperado: ERROR P0001 -- "UPDATE rechazado: historial_estado_orden es de solo agregado"
UPDATE historial_estado_orden SET hasta_estado = 'SA_DESTINO' WHERE id = :historial_estado_id;
psql:test/solo_agregado.sql:66: ERROR:  P0001: UPDATE rechazado: historial_estado_orden es de solo agregado
HINT:  Registrar una fila nueva en lugar de modificar o borrar una existente
CONTEXT:  PL/pgSQL function rechazar_cambio_solo_agregado() line 3 at RAISE
-- Esperado: ERROR P0001 -- "DELETE rechazado: historial_estado_orden es de solo agregado"
DELETE FROM historial_estado_orden WHERE id = :historial_estado_id;
psql:test/solo_agregado.sql:69: ERROR:  P0001: DELETE rechazado: historial_estado_orden es de solo agregado
HINT:  Registrar una fila nueva en lugar de modificar o borrar una existente
CONTEXT:  PL/pgSQL function rechazar_cambio_solo_agregado() line 3 at RAISE
-- --- 2. movimiento_stock ---
-- Esperado: ERROR P0001 -- "UPDATE rechazado: movimiento_stock es de solo agregado"
UPDATE movimiento_stock SET cantidad = 99 WHERE id = :movimiento_id;
psql:test/solo_agregado.sql:73: ERROR:  P0001: UPDATE rechazado: movimiento_stock es de solo agregado
HINT:  Registrar una fila nueva en lugar de modificar o borrar una existente
CONTEXT:  PL/pgSQL function rechazar_cambio_solo_agregado() line 3 at RAISE
-- Esperado: ERROR P0001 -- "DELETE rechazado: movimiento_stock es de solo agregado"
DELETE FROM movimiento_stock WHERE id = :movimiento_id;
psql:test/solo_agregado.sql:76: ERROR:  P0001: DELETE rechazado: movimiento_stock es de solo agregado
HINT:  Registrar una fila nueva en lugar de modificar o borrar una existente
CONTEXT:  PL/pgSQL function rechazar_cambio_solo_agregado() line 3 at RAISE
-- --- 3. historial_precio_repuesto ---
-- Esperado: ERROR P0001 -- "UPDATE rechazado: historial_precio_repuesto es de solo agregado"
UPDATE historial_precio_repuesto SET precio_nuevo = 130.00 WHERE id = :historial_precio_id;
psql:test/solo_agregado.sql:80: ERROR:  P0001: UPDATE rechazado: historial_precio_repuesto es de solo agregado
HINT:  Registrar una fila nueva en lugar de modificar o borrar una existente
CONTEXT:  PL/pgSQL function rechazar_cambio_solo_agregado() line 3 at RAISE
-- Esperado: ERROR P0001 -- "DELETE rechazado: historial_precio_repuesto es de solo agregado"
DELETE FROM historial_precio_repuesto WHERE id = :historial_precio_id;
psql:test/solo_agregado.sql:83: ERROR:  P0001: DELETE rechazado: historial_precio_repuesto es de solo agregado
HINT:  Registrar una fila nueva en lugar de modificar o borrar una existente
CONTEXT:  PL/pgSQL function rechazar_cambio_solo_agregado() line 3 at RAISE
-- --- 4. Clave foranea: orden con un estado que no esta en el catalogo ---
-- Esperado: ERROR 23503 -- violacion de fk_orden_trabajo_estado_estado_orden
INSERT INTO orden_trabajo (vehiculo_id, estado, falla, total)
VALUES (:vehiculo_id, 'INEXISTENTE', 'Estado fuera del catalogo', 0);
psql:test/solo_agregado.sql:88: ERROR:  23503: insert or update on table "orden_trabajo" violates foreign key constraint "fk_orden_trabajo_estado_estado_orden"
DETAIL:  Key (estado)=(INEXISTENTE) is not present in table "estado_orden".
CONSTRAINT NAME:  fk_orden_trabajo_estado_estado_orden
-- Las tres filas siguen intactas despues de los rechazos (cada conteo debe ser 1):
 historial_estado_orden | movimiento_stock | historial_precio_repuesto
------------------------+------------------+---------------------------
                      1 |                1 |                         1
(1 row)

ROLLBACK;
ROLLBACK
```

---

## 8. Evidencia del caso C-15 (detalle de una orden con 2 y con 4 ítems sin N+1)

`OrdenTrabajoRepository.get_detalle` carga la orden con `joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente)`, `selectinload(OrdenTrabajo.items).joinedload(ItemOrden.repuesto)` y `selectinload(OrdenTrabajo.historial)`. Por eso, al consultar `GET /ordenes/{orden_id}` con `SQL_ECHO=true`, SQLAlchemy ejecuta siempre **exactamente 5 sentencias `SELECT`** sin importar cuántos ítems ni cuántas transiciones tenga la orden:

1. `SELECT usuario … WHERE usuario.id = $1` (guarda `autenticar` / `exigir_password_al_dia`).
2. `SELECT orden_trabajo … LEFT OUTER JOIN vehiculo … LEFT OUTER JOIN cliente … WHERE orden_trabajo.id = $1` (orden + vehículo + cliente en un único `SELECT`).
3. `SELECT historial_estado_orden … WHERE historial_estado_orden.orden_id IN ($1) ORDER BY historial_estado_orden.id` (todo el historial en un único `SELECT`).
4. `SELECT item_orden … LEFT OUTER JOIN repuesto … WHERE item_orden.orden_id IN ($1) ORDER BY item_orden.id` (todos los ítems con sus repuestos en un único `SELECT`).
5. `SELECT asignacion_rol.rol … WHERE asignacion_rol.usuario_id = $1 …` (verificación de roles vigentes del solicitante en `_roles_vigentes`).

La salida completa está versionada en [`test/evidencia_c15.txt`](test/evidencia_c15.txt):

```text
=== GET /ordenes/1 (orden con 2 ítems): 5 sentencias SQL ===
2026-10-31 01:08:49,295 INFO sqlalchemy.engine.Engine BEGIN (implicit)
2026-10-31 01:08:49,295 INFO sqlalchemy.engine.Engine SELECT usuario.id, usuario.email, usuario.nombre, usuario.password_hash, usuario.activo, usuario.debe_cambiar_password, usuario.password_cambiada_en
FROM usuario
WHERE usuario.id = $1::INTEGER
2026-10-31 01:08:49,297 INFO sqlalchemy.engine.Engine COMMIT
2026-10-31 01:08:49,299 INFO sqlalchemy.engine.Engine BEGIN (implicit)
2026-10-31 01:08:49,299 INFO sqlalchemy.engine.Engine SELECT orden_trabajo.id, orden_trabajo.vehiculo_id, orden_trabajo.mecanico_id, orden_trabajo.estado, orden_trabajo.falla, orden_trabajo.creada_en, orden_trabajo.total, cliente_1.id AS id_1, cliente_1.usuario_id, cliente_1.nombre, cliente_1.documento, cliente_1.telefono, vehiculo_1.id AS id_2, vehiculo_1.cliente_id, vehiculo_1.patente, vehiculo_1.marca, vehiculo_1.modelo, vehiculo_1.anio, vehiculo_1.borrado_en
FROM orden_trabajo LEFT OUTER JOIN vehiculo AS vehiculo_1 ON vehiculo_1.id = orden_trabajo.vehiculo_id LEFT OUTER JOIN cliente AS cliente_1 ON cliente_1.id = vehiculo_1.cliente_id
WHERE orden_trabajo.id = $1::INTEGER
2026-10-31 01:08:49,301 INFO sqlalchemy.engine.Engine SELECT historial_estado_orden.orden_id AS historial_estado_orden_orden_id, historial_estado_orden.id AS historial_estado_orden_id, historial_estado_orden.desde_estado AS historial_estado_orden_desde_estado, historial_estado_orden.hasta_estado AS historial_estado_orden_hasta_estado, historial_estado_orden.usuario_id AS historial_estado_orden_usuario_id, historial_estado_orden.cuando AS historial_estado_orden_cuando
FROM historial_estado_orden
WHERE historial_estado_orden.orden_id IN ($1::INTEGER) ORDER BY historial_estado_orden.id
2026-10-31 01:08:49,303 INFO sqlalchemy.engine.Engine SELECT item_orden.orden_id AS item_orden_orden_id, item_orden.id AS item_orden_id, item_orden.repuesto_id AS item_orden_repuesto_id, item_orden.cantidad AS item_orden_cantidad, item_orden.precio_unitario AS item_orden_precio_unitario, repuesto_1.id AS repuesto_1_id, repuesto_1.codigo AS repuesto_1_codigo, repuesto_1.descripcion AS repuesto_1_descripcion, repuesto_1.precio AS repuesto_1_precio, repuesto_1.stock AS repuesto_1_stock, repuesto_1.borrado_en AS repuesto_1_borrado_en
FROM item_orden LEFT OUTER JOIN repuesto AS repuesto_1 ON repuesto_1.id = item_orden.repuesto_id
WHERE item_orden.orden_id IN ($1::INTEGER) ORDER BY item_orden.id
2026-10-31 01:08:49,304 INFO sqlalchemy.engine.Engine SELECT asignacion_rol.rol
FROM asignacion_rol
WHERE asignacion_rol.usuario_id = $1::INTEGER AND asignacion_rol.revocada_en IS NULL AND (asignacion_rol.vence_en IS NULL OR asignacion_rol.vence_en > $2::TIMESTAMP WITH TIME ZONE) ORDER BY asignacion_rol.rol
2026-10-31 01:08:49,305 INFO sqlalchemy.engine.Engine COMMIT

=== GET /ordenes/3 (orden con 4 ítems): 5 sentencias SQL ===
2026-10-31 01:08:49,310 INFO sqlalchemy.engine.Engine BEGIN (implicit)
2026-10-31 01:08:49,310 INFO sqlalchemy.engine.Engine SELECT usuario.id, usuario.email, usuario.nombre, usuario.password_hash, usuario.activo, usuario.debe_cambiar_password, usuario.password_cambiada_en
FROM usuario
WHERE usuario.id = $1::INTEGER
2026-10-31 01:08:49,311 INFO sqlalchemy.engine.Engine COMMIT
2026-10-31 01:08:49,313 INFO sqlalchemy.engine.Engine BEGIN (implicit)
2026-10-31 01:08:49,313 INFO sqlalchemy.engine.Engine SELECT orden_trabajo.id, orden_trabajo.vehiculo_id, orden_trabajo.mecanico_id, orden_trabajo.estado, orden_trabajo.falla, orden_trabajo.creada_en, orden_trabajo.total, cliente_1.id AS id_1, cliente_1.usuario_id, cliente_1.nombre, cliente_1.documento, cliente_1.telefono, vehiculo_1.id AS id_2, vehiculo_1.cliente_id, vehiculo_1.patente, vehiculo_1.marca, vehiculo_1.modelo, vehiculo_1.anio, vehiculo_1.borrado_en
FROM orden_trabajo LEFT OUTER JOIN vehiculo AS vehiculo_1 ON vehiculo_1.id = orden_trabajo.vehiculo_id LEFT OUTER JOIN cliente AS cliente_1 ON cliente_1.id = vehiculo_1.cliente_id
WHERE orden_trabajo.id = $1::INTEGER
2026-10-31 01:08:49,315 INFO sqlalchemy.engine.Engine SELECT historial_estado_orden.orden_id AS historial_estado_orden_orden_id, historial_estado_orden.id AS historial_estado_orden_id, historial_estado_orden.desde_estado AS historial_estado_orden_desde_estado, historial_estado_orden.hasta_estado AS historial_estado_orden_hasta_estado, historial_estado_orden.usuario_id AS historial_estado_orden_usuario_id, historial_estado_orden.cuando AS historial_estado_orden_cuando
FROM historial_estado_orden
WHERE historial_estado_orden.orden_id IN ($1::INTEGER) ORDER BY historial_estado_orden.id
2026-10-31 01:08:49,317 INFO sqlalchemy.engine.Engine SELECT item_orden.orden_id AS item_orden_orden_id, item_orden.id AS item_orden_id, item_orden.repuesto_id AS item_orden_repuesto_id, item_orden.cantidad AS item_orden_cantidad, item_orden.precio_unitario AS item_orden_precio_unitario, repuesto_1.id AS repuesto_1_id, repuesto_1.codigo AS repuesto_1_codigo, repuesto_1.descripcion AS repuesto_1_descripcion, repuesto_1.precio AS repuesto_1_precio, repuesto_1.stock AS repuesto_1_stock, repuesto_1.borrado_en AS repuesto_1_borrado_en
FROM item_orden LEFT OUTER JOIN repuesto AS repuesto_1 ON repuesto_1.id = item_orden.repuesto_id
WHERE item_orden.orden_id IN ($1::INTEGER) ORDER BY item_orden.id
2026-10-31 01:08:49,318 INFO sqlalchemy.engine.Engine SELECT asignacion_rol.rol
FROM asignacion_rol
WHERE asignacion_rol.usuario_id = $1::INTEGER AND asignacion_rol.revocada_en IS NULL AND (asignacion_rol.vence_en IS NULL OR asignacion_rol.vence_en > $2::TIMESTAMP WITH TIME ZONE) ORDER BY asignacion_rol.rol
2026-10-31 01:08:49,319 INFO sqlalchemy.engine.Engine COMMIT
```

---

## 9. Evidencia del caso C-12 (aviso en segundo plano con `BackgroundTasks`)

Cuando `POST /ordenes/2/terminar` confirma su transacción (`UnitOfWork.commit()`), el router encola `service.avisar_orden_terminada(orden_id=salida.id, patente=salida.patente)` en `BackgroundTasks` de FastAPI. La tarea espera `0.5 s` con `await asyncio.sleep(0.5)` fuera de la transacción de base de datos y registra el aviso en el logger `uvicorn.error.avisos`:

```text
INFO:     127.0.0.1:54321 - "POST /ordenes/2/terminar HTTP/1.1" 200 OK
INFO:     Aviso simulado al cliente: la orden #2 del vehículo AD789GH está terminada
```

---

## 10. Verificación rápida de calidad y seguridad

```powershell
# 1. Linter y formato de git
.\.venv\Scripts\ruff.exe check .
git diff --check

# 2. Primitivas de seguridad (bcrypt en hilo con semáforo, JWT HS256, hash ficticio)
.\.venv\Scripts\python.exe test\verificar_security_core.py

# 3. Recarga del estado inicial conocido antes de correr cualquier archivo .http
.\.venv\Scripts\python.exe seed.py
```
