# CHANGES — Secuencia de Implementación

> Índice canónico de todos los changes del proyecto **Taller Mecánico API** (TP integrador Programación III, caps. 1-6: FastAPI + SQLModel/SQLAlchemy async + PostgreSQL + Alembic).
> Cada change es atómico: un agente puede implementarlo en una sesión (~4-6 horas).
> **Leer este archivo antes de ejecutar cualquier `/opsx:propose`.**
>
> Nota de nomenclatura: los `C-NN` de este documento son IDs de *changes de implementación*. Los casos de prueba de la consigna (`C-01…C-19` en `knowledge-base/06_funcionalidades.md`) se citan aquí como **"caso PDF Cxx"** para no confundirlos.
> Fuera de alcance (no generan changes): concurrencia (cap. 7), colas Redis (cap. 8), frontend, pytest (la verificación es con `.http` en `test/` y `test/solo_agregado.sql`).

---

## Cómo usar este documento

1. Identificá el próximo change cuyo `Estado` sea `[ ]` y cuyas **Dependencias** estén todas en `[x]`.
2. Leé los archivos listados en **Leer antes** (rutas bajo `knowledge-base/`) antes de proponer nada.
3. Ejecutá `/opsx:propose C-NN-<nombre>` y luego `/opsx:apply` (respetá el nivel de **Governance**: CRITICO/ALTO = proponer y esperar revisión antes de escribir).
4. Al terminar, `/opsx:archive C-NN-<nombre>`.
5. Marcá el checkbox del change (`[ ]` → `[x]`) en este archivo.

Prioridad por peso de evaluación (`01_vision_y_objetivos.md`): Repos/UoW 20 %, Autenticación 16 %, Modelos/migraciones 14 %, Autorización 14 %. Condición bloqueante: el proyecto debe levantar y `alembic upgrade head` debe crear el esquema sobre base vacía, sin credenciales reales en el repo.

---

## Árbol de dependencias

```
C-01 foundation-setup
 ├── C-02 core-repository-uow
 │    └── C-03 domain-models-migration
 │         ├── C-04 append-only-trigger-migration ──┐
 │         └── C-07 auth-registro-login (también C-05, C-02)
 └── C-05 security-core ──────────────────────────────┤
                                                      └── C-06 seed-script (C-04 + C-05)

C-07 auth-registro-login
 └── C-08 auth-session-guards
      ├── C-09 roles-personal-eventos
      ├── C-10 clientes-vehiculos ─────────┐
      └── C-11 repuestos-catalogo          │
           └── C-12 repuestos-stock-precios│
                                           ▼
              C-13 ordenes-alta-estados  (C-10 + C-11)
               ├── C-14 ordenes-transiciones   (C-13 + C-12)
               └── C-15 ordenes-lecturas-sin-n-plus-1

C-16 verificacion-http-readme  (C-06 + C-09 + C-14 + C-15)
```

### Paralelismo por fase

```
GATE 0: C-01 ✓
  → C-02 core-repository-uow            [hecho]
  → C-05 security-core                  [hecho]

GATE 1: C-02 ✓
  → C-03 domain-models-migration        [hecho]

GATE 2: C-03 ✓                          ← FORK
  → C-04 append-only-trigger-migration  [hecho]
  → C-07 auth-registro-login            [hecho]
  → C-06 seed-script                    [propuesto — si C-04 ✓ y C-05 ✓]
  → C-16 (sólo casos .http por adelantado, desde la matriz de 03_actores_y_roles.md)

GATE 3: C-07 ✓
  → C-08 auth-session-guards            [hecho]

GATE 4: C-08 ✓                          ← FORK
  → C-09 roles-personal-eventos         [hecho]
  → C-10 clientes-vehiculos
  → C-11 repuestos-catalogo            [hecho]

GATE 5: C-11 ✓
  → C-12 repuestos-stock-precios        [hecho]
  → C-13 ordenes-alta-estados           [si C-10 ✓ además]

GATE 6: C-13 ✓ (y C-12 ✓)
  → C-14 ordenes-transiciones
  → C-15 ordenes-lecturas-sin-n-plus-1

GATE 7: C-06, C-09, C-14, C-15 ✓
  → C-16 verificacion-http-readme
```

### Camino crítico (9 changes — mínimo irreducible)

`C-01 → C-02 → C-03 → C-07 → C-08 → C-10 → C-13 → C-14 → C-16`

(C-05 corre en paralelo a C-02/C-03 y no alarga el camino; C-14 además requiere C-12, que se completa en paralelo a C-10/C-13. C-16 es el último indispensable; C-09, C-15 y C-06 son requisitos previos de C-16 fuera de la cadena.)

### Reparto del equipo

Quién hace qué (integrantes, herramientas, pasos, revisión cruzada y entregables de C-16) vive **sólo** en [docs/REPARTO_DE_TAREAS.md](docs/REPARTO_DE_TAREAS.md). Acá cada change tiene un campo **Responsable** que tiene que coincidir con la tabla §3 de ese documento; si el reparto cambia, se editan los dos en el mismo commit.

> **Convención para los `tasks.md`:** los changes que implementa Lauti (C-06, C-10, C-15, C-16) los hacen modelos más chicos, así que cada tarea indica el archivo exacto, la firma de la función o del endpoint, la regla dura que aplica y el caso `.http` que tiene que pasar. Una tarea ambigua se reescribe antes de asignarla, no se deja a criterio del modelo. Se mantiene la misma convención en todos los changes, para que cualquiera pueda tomar cualquiera.

---

## FASE 1 — Fundación del proyecto (Ej.1, 8 %)

### [C-01] `foundation-setup`
- **Estado**: `[x]` completado
- **Scope**:
  - Estructura de directorios obligatoria: `main.py`, `app/core/`, `app/modules/{health,usuarios,clientes,repuestos,ordenes}/`, `migrations/`, `test/`
  - `requirements.txt` (fastapi, uvicorn, sqlmodel, sqlalchemy[asyncio], asyncpg, alembic, bcrypt>=4.0, PyJWT, pydantic-settings), `.gitignore` (excluye `.env`), `env.example` completo sin secretos
  - `app/core/config.py`: `Settings` pydantic-settings; `DATABASE_URL` con `@computed_field` desde `POSTGRES_*` (driver `postgresql+asyncpg://`); `POSTGRES_PASSWORD` y `SECRET_KEY` sin default (la app no arranca si faltan); `BCRYPT_COST`, `BCRYPT_MAX_CONCURRENCY`, `POOL_SIZE`, `MAX_OVERFLOW`, `COOKIE_SECURE`, `ACCESS_TOKEN_EXPIRE_SECONDS=1800`, `SQL_ECHO`
  - `app/core/database.py`: motor + `async_sessionmaker(expire_on_commit=False)`; `get_session`
  - `main.py` con lifespan: motor/fábrica en `app.state`, `dispose()` al apagar (hash ficticio se agrega en C-05)
  - `app/modules/health/router.py`: `GET /health/live` (sin tocar la base), `GET /health/ready` (`SELECT 1`, 503 si falla)
  - Alembic inicializado con plantilla async (`alembic init -t async`), `alembic.ini` sin credenciales, `env.py` leyendo `Settings`
  - Verificación: la app levanta con `uvicorn main:app` y `/health/*` responde
- **Dependencias**: ninguna
- **Governance**: MEDIO (maneja secretos/configuración; condición bloqueante de la corrección)
- **Responsable**: `propose` Mati · `apply` Mati
- **Leer antes**:
  - `knowledge-base/01_vision_y_objetivos.md` §Métricas de éxito
  - `knowledge-base/06_funcionalidades.md` §Épica 1 (US-001, US-002)
  - `knowledge-base/08_arquitectura_propuesta.md` §Estructura de directorios, §Variables de entorno, §Seguridad (Secrets)
  - `knowledge-base/09_decisiones_y_supuestos.md`

---

## FASE 2 — Capas base, modelo de datos y migraciones (Ej.2 y Ej.6 base, 14 % + 20 %)

> Nota: C-05 (security-core, Fase 3) puede arrancar en paralelo apenas cierre C-01.

### [C-02] `core-repository-uow`
- **Estado**: `[x]` completado
- **Scope**:
  - `app/core/repository.py`: `BaseRepository[T]` (sesión + clase del modelo en el constructor; `get_by_id`, `get_all`, `count`, `add`, `update`, `delete`; `add`/`update` hacen `flush()`, nunca `commit()`) y `SoftDeleteRepository[T]` (filtra `borrado_en`; `get_by_id_including_deleted`, `soft_delete`)
  - `app/core/unit_of_work.py`: `UnitOfWork` base (async context manager: commit al salir, rollback ante excepción, no cierra la sesión; una sesión compartida por todos los repos del UoW)
  - `app/core/paginacion.py`: envoltorio `{items, total, page, size, pages}`; `page>=1`, `size` 1-100 (def. 20); página más allá de la última → 422; 0 resultados → página vacía
  - Manejadores globales: `IntegrityError` → 409/422 con mensaje propio, sin texto interno de la base (RN18); ninguna entrada inválida termina en 500
  - Contrato de DTOs: base con `extra="forbid"`, ninguna respuesta incluye `password_hash`
- **Dependencias**: `C-01`
- **Governance**: ALTO (cimiento que todos los módulos heredan; pesa 20 % de la nota)
- **Responsable**: `propose` Mati · `apply` Mati
- **Leer antes**:
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones aplicados
  - `knowledge-base/05_reglas_de_negocio.md` §Reglas globales de contrato, RN18
  - `knowledge-base/06_funcionalidades.md` §Épica 1
  - `knowledge-base/09_decisiones_y_supuestos.md`

### [C-03] `domain-models-migration`
- **Estado**: `[x]` completado
- **Scope**:
  - Modelos SQLModel de las 13 tablas: dominio usuarios (`usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`), clientes (`cliente`, `vehiculo`), repuestos (`repuesto`, `movimiento_stock`, `historial_precio_repuesto`), ordenes (`estado_orden`, `orden_trabajo`, `item_orden`, `historial_estado_orden`); nombres de tablas/columnas obligatorios
  - Relaciones: asociación, composición (`item_orden` ◆ `orden_trabajo`), uno a uno opcional `Usuario.cliente` (objeto, no lista; `uselist=False`), catálogo traducido; navegación declarada en ambos extremos; toda FK con índice
  - CHECKs, UNIQUEs e índices únicos parciales con `postgresql_where` (`asignacion_rol(usuario_id, rol)`, `vehiculo(patente)`, `repuesto(codigo)`); `timestamptz`; dinero `NUMERIC` / `Decimal`
  - Enum `EstadoOrden` en código coherente con las filas del catálogo
  - Migración 1 generada con `alembic revision --autogenerate` (catálogo `estado_orden` vacío), con comentario "leída antes de aplicar"
  - Verificación: `alembic upgrade head` sobre base vacía crea el esquema
- **Dependencias**: `C-02`
- **Governance**: CRITICO (modelos core que todo lo demás referencia)
- **Responsable**: `propose` Mati · `apply` Mati
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` (completo: ERD, entidades, decisiones de modelado)
  - `knowledge-base/05_reglas_de_negocio.md` §Identidad y unicidad, RN16, RN19
  - `knowledge-base/08_arquitectura_propuesta.md` §Migraciones
  - `knowledge-base/09_decisiones_y_supuestos.md`

### [C-04] `append-only-trigger-migration`
- **Estado**: `[x]` completado
- **Scope**:
  - Migración 2 escrita a mano: función PL/pgSQL + trigger "sólo agregado" (rechaza UPDATE/DELETE) sobre `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`; comentario de revisión; `downgrade` elimina trigger y función
  - `test/solo_agregado.sql`: seis rechazos (UPDATE y DELETE × 3 tablas) + FK por estado inexistente (caso PDF C14)
  - Verificación del ciclo `upgrade head` → `downgrade base` → `upgrade head`
- **Dependencias**: `C-03`
- **Governance**: ALTO (integridad en base; RN15)
- **Responsable**: `propose` Mati · `apply` Mati
- **Leer antes**:
  - `knowledge-base/05_reglas_de_negocio.md` RN15
  - `knowledge-base/06_funcionalidades.md` §Épica 7 (US-060)
  - `knowledge-base/08_arquitectura_propuesta.md` §Migraciones, §Seguridad (Integridad)
  - `knowledge-base/04_modelo_de_datos.md` §historial_estado_orden, §movimiento_stock, §historial_precio_repuesto

---

## FASE 3 — Autenticación y autorización (Ej.4 y Ej.5, 16 % + 14 %)

### [C-05] `security-core`
- **Estado**: `[x]` completado
- **Scope**:
  - `app/core/security.py`: hash/verificación bcrypt en `asyncio.to_thread` bajo semáforo (`BCRYPT_MAX_CONCURRENCY`), costo desde Settings; validación ≤ 72 bytes (bytes, no caracteres)
  - Emisión/verificación JWT (PyJWT): claims `sub`, `iat` con fracción, `exp`, roles vigentes (informativos); cookie `access_token` HttpOnly, SameSite=Lax, Max-Age, `Secure` configurable; no se acepta `Authorization: Bearer`
  - Hash ficticio calculado una sola vez en el lifespan → `app.state` (anti-enumeración, RN09)
- **Dependencias**: `C-01`
- **Governance**: CRITICO (auth)
- **Responsable**: `propose` Lauti · `apply` Lauti
- **Leer antes**:
  - `knowledge-base/08_arquitectura_propuesta.md` §Seguridad
  - `knowledge-base/05_reglas_de_negocio.md` RN07, RN09
  - `knowledge-base/07_flujos_principales.md` §Flujo 1, §Flujo 2
  - `knowledge-base/10_preguntas_abiertas.md` IN-03

### [C-06] `seed-script`
- **Estado**: `[ ]` pendiente
- **Scope**:
  - `seed.py` idempotente: vacía las tablas y carga el estado inicial, el catálogo `estado_orden` primero (PENDIENTE 1, EN_REPARACION 2, TERMINADA 3 final, CANCELADA 4 final)
  - Usuarios: `admin@`, `admin2@` (ADMIN), `recepcion@`, `mecanico@`, `mecanico2@`, `cliente@`, `nuevo@` (MECANICO con `debe_cambiar_password`), contraseñas de mentira sólo en `seed.py`
  - Clientes: Laura (con usuario, 2 vehículos), Jorge (sin usuario, 1 vehículo); repuestos con movimiento "Stock inicial"; órdenes #1 PENDIENTE y #2 EN_REPARACION (4 bujías con stock 2, a propósito); historial de precio 8000 → 8500; evento de seguridad actor `SISTEMA`
  - Hashes generados con `security.py`
  - Correos cargados en minúsculas: `seed.py` verifica al cargar y falla (o los normaliza) si alguno tiene mayúsculas o espacios; la API los normaliza y la base no lo impone, porque la consigna admite sólo dos migraciones (S-01 de C-07)
  - Correos con dominio válido para `EmailStr` (p. ej. `@taller.com` o `@example.com`): el login los valida y rechaza dominios de uso especial como `.local`, `.test` o `.localhost` con 422, así que un usuario del seed con esos dominios nunca podría iniciar sesión (revisión de C-07)
  - **Heredado de C-09** (S-09): el primer ADMIN del seed se crea **sin `vence_en`**; RN05 sólo cuenta ADMIN vigentes sin vencimiento, así que un ADMIN con vencimiento no protege al sistema de quedar sin administradores
- **Dependencias**: `C-04, C-05`
- **Governance**: MEDIO (datos de prueba; credenciales ficticias, nunca reales)
- **Responsable**: `propose` Mati · `apply` Lauti
- **Leer antes**:
  - `knowledge-base/04_modelo_de_datos.md` §Seed data inicial
  - `knowledge-base/10_preguntas_abiertas.md` IN-04
  - `knowledge-base/07_flujos_principales.md` §Flujo 9
  - `knowledge-base/06_funcionalidades.md` §Épica 8 (US-070)

### [C-07] `auth-registro-login`
- **Estado**: `[x]` completado
- **Scope**:
  - Módulo `usuarios` (models/schemas/repository/unit_of_work/service/router) con `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad`
  - `POST /auth/registro`: hash antes de abrir la transacción; un UoW crea `usuario` + `asignacion_rol(CLIENTE)` + `cliente` + `evento_seguridad`; correo/documento repetido → 409 sin filas sueltas; documento de cliente existente → 409 (RN02). Casos PDF C02
  - `POST /auth/login`: conteo de fallos (email+IP, 60 s, desde el último éxito) → 429 + `Retry-After` sin calcular hash (≥ 5, RN08); verificación contra hash real o ficticio; mismo mensaje 401; cada intento en `intento_acceso` con sesión y transacción propias; cookie `access_token`, cuerpo `{mensaje, debe_cambiar_password, expira_en_segundos}`. Casos PDF C03-C05
  - `POST /auth/logout` (borra cookie)
- **Dependencias**: `C-02, C-03, C-05`
- **Governance**: CRITICO (auth)
- **Responsable**: `propose` Mati · `apply` Mati
- **Leer antes**:
  - `knowledge-base/07_flujos_principales.md` §Flujo 1 (Login), §Flujo 3 (Registro)
  - `knowledge-base/05_reglas_de_negocio.md` RN01-RN03, RN08, RN09
  - `knowledge-base/06_funcionalidades.md` §Épica 2 (US-010, US-011)
  - `knowledge-base/03_actores_y_roles.md` §Matriz RBAC (rutas /auth)

### [C-08] `auth-session-guards`
- **Estado**: `[x]` completado
- **Scope**:
  - `app/core/dependencies.py`: `get_usuario_actual` (401: sin cookie, token inválido/vencido, usuario inexistente/inactivo, `iat` < `password_cambiada_en` comparado sin truncar), control de cambio obligatorio (403 si `debe_cambiar_password`), `requiere_rol(...)` consultando `asignacion_rol` vigente en base por petición (RN04)
  - `main.py`: dos grupos de rutas (abierto: `/auth/*` y salud; protegido: resto con control de cambio montado una vez, RN06)
  - `GET /auth/yo` (usuario, roles vigentes y roles del token); `POST /auth/cambiar-password` (hash antes de la transacción, actualiza `password_cambiada_en`, baja la bandera, emite cookie nueva válida; la anterior da 401). Casos PDF C06-C09
  - Completar el caso PDF C03: 401 sin cookie y con `Authorization: Bearer` (diferido de C-07, S-06)
- **Dependencias**: `C-07`
- **Governance**: CRITICO (autorización 401 vs 403)
- **Responsable**: `propose` Mati · `apply` Mati
- **Leer antes**:
  - `knowledge-base/07_flujos_principales.md` §Flujo 2, §Flujo 8
  - `knowledge-base/05_reglas_de_negocio.md` RN04, RN06, RN07, RN17
  - `knowledge-base/03_actores_y_roles.md` §Roles, §Rutas públicas
  - `knowledge-base/06_funcionalidades.md` §Épica 2 (US-012), §Épica 3 (US-022)

### [C-09] `roles-personal-eventos`
- **Estado**: `[x]` completado
- **Scope**:
  - `POST /usuarios` (ADMIN): alta de personal con contraseña provisoria y `debe_cambiar_password=true`; correo repetido → 409
  - `POST /usuarios/{id}/roles` (vencimiento opcional tz-aware y futuro, si no 422; duplicado vigente → 409; reasignar rol vencido cierra la fila previa y abre otra), `GET /usuarios/{id}/roles`, `DELETE /usuarios/{id}/roles/{rol}` (revoca sin borrar; ADMIN no se auto-revoca; nunca 0 admins → 409, RN05)
  - `GET /eventos?page&size` (ADMIN, paginado); `evento_seguridad` registra altas y cambios de rol (el de contraseña ya lo escribe C-08)
  - Revocar un rol hace que la siguiente petición con la misma cookie dé 403
  - No existe `GET /usuarios` (IN-02)
  - **Heredado de C-08** (S-05, S-06):
    - Montar los routers de `/usuarios` y `/eventos` en `rutas_protegidas` **antes** de `app.include_router(rutas_protegidas)` en `main.py` y con `requiere_rol(Rol.ADMIN)`. Un router incluido después no hereda el control de cambio pendiente; `requiere_rol` igual lo exige.
    - El grupo protegido estaba vacío en C-08: agregar al `.http` la evidencia del 403 por cambio pendiente y del 403 por rol sobre una ruta protegida real (caso PDF C09), y los casos PDF C07 (revocar o vencer un rol → 403 con la misma cookie; vencimientos inválidos → 422) y C08 (autoprotección del ADMIN).
    - El evento de cambio de contraseña ya lo escribe C-08 en el mismo UoW; acá sólo quedan las altas y los cambios de rol.
- **Dependencias**: `C-08`
- **Governance**: CRITICO (gestión de roles / auditoría)
- **Responsable**: `propose` Mati · `apply` Mati
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 3 (US-020, US-021)
  - `knowledge-base/05_reglas_de_negocio.md` RN03, RN05
  - `knowledge-base/03_actores_y_roles.md` §RBAC (rutas /usuarios, /eventos)
  - `knowledge-base/10_preguntas_abiertas.md` IN-02

---

## FASE 4 — Dominio: clientes y repuestos

> C-10 y C-11 (y luego C-12) son independientes entre sí; corren en paralelo tras C-08.

### [C-10] `clientes-vehiculos`
- **Estado**: `[ ]` pendiente
- **Scope**:
  - Módulo `clientes` (+ `Vehiculo`, `SoftDeleteRepository`): `POST /clientes` (RECEPCION, ADMIN; documento repetido → 409), `GET /clientes/{id}` con vehículos (eager loading), `POST /clientes/{id}/vehiculos` (patente vigente repetida → 409; `anio` 1950-2100)
  - `DELETE /vehiculos/{id}` → 204 baja lógica; 409 si tiene órdenes abiertas (estado no final según `es_final`, RN16); patente reutilizable tras la baja
  - `GET /mis-vehiculos` (autenticado, sólo los propios, RN17)
  - Tests `.http` del módulo (casos PDF C-xx de clientes/vehículos)
- **Dependencias**: `C-08`
- **Governance**: MEDIO
- **Responsable**: `propose` Nico · `apply` Lauti
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 4 (US-030, US-031)
  - `knowledge-base/04_modelo_de_datos.md` §cliente, §vehiculo
  - `knowledge-base/05_reglas_de_negocio.md` RN01, RN16, RN17
  - `knowledge-base/03_actores_y_roles.md` §RBAC (rutas /clientes, /vehiculos)

### [C-11] `repuestos-catalogo`
- **Estado**: `[x]` completado
- **Scope**:
  - Módulo `repuestos` (+ `SoftDeleteRepository`): `GET /repuestos?q&page&size` (ADMIN, RECEPCION, MECANICO; búsqueda con parámetros ligados, `' OR '1'='1` → lista vacía; paginado), `GET /repuestos/{id}`
  - `POST /repuestos` (ADMIN) con `stock_inicial` que genera `movimiento_stock` "Stock inicial" (cantidad positiva) en el mismo UoW; código vigente repetido → 409
  - `PATCH /repuestos/{id}` (ADMIN, `exclude_unset`, sólo descripción y precio; `stock` en el cuerpo → 422); `DELETE /repuestos/{id}` → 204 baja lógica
  - Punto único de escritura de stock (RN14) definido en el servicio/repo de repuestos
- **Dependencias**: `C-08`
- **Governance**: MEDIO
- **Responsable**: `propose` Nico · `apply` Mati
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 5 (US-040)
  - `knowledge-base/05_reglas_de_negocio.md` RN01, RN14, RN16, §Reglas globales de contrato
  - `knowledge-base/04_modelo_de_datos.md` §repuesto, §movimiento_stock
  - `knowledge-base/03_actores_y_roles.md` §RBAC (rutas /repuestos)

### [C-12] `repuestos-stock-precios`
- **Estado**: `[x]` completado
- **Scope**:
  - `POST /repuestos/{id}/reponer` (ADMIN): suma stock y registra `movimiento_stock` (cantidad positiva, motivo) en una transacción; cantidad inválida → 422
  - `GET /repuestos/{id}/movimientos` (ADMIN), `GET /repuestos/{id}/precios` (ADMIN, historial)
  - Caso PDF C18: sólo la lectura de `/precios`. El historial en el `PATCH` (RN20) ya lo escribe C-11 (S-03): C-12 **no** toca `editar()`
  - `reponer` usa el punto único `aplicar_movimientos_stock` de C-11 (ver «Notas para otros changes» en su design)
  - `movimiento_stock.cantidad` con signo: entradas positivas, salidas negativas
- **Dependencias**: `C-11`
- **Governance**: ALTO (stock y precios; historiales de sólo agregado)
- **Responsable**: `propose` Nico · `apply` Mati
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 5 (US-041, US-042)
  - `knowledge-base/07_flujos_principales.md` §Flujo 7
  - `knowledge-base/05_reglas_de_negocio.md` RN14, RN15, RN20
  - `knowledge-base/04_modelo_de_datos.md` §historial_precio_repuesto, §movimiento_stock

---

## FASE 5 — Órdenes de trabajo

### [C-13] `ordenes-alta-estados`
- **Estado**: `[ ]` pendiente
- **Scope**:
  - Módulo `ordenes` (+ `EstadoOrden`, `ItemOrden`, `HistorialEstadoOrden`); `EstadoOrdenRepository` de sólo lectura (no hereda de `BaseRepository`, PK `codigo`)
  - `POST /ordenes` (RECEPCION, ADMIN): cuerpo `{vehiculo_id, falla, items[{repuesto_id, cantidad}]}` sin precio/total/estado/fecha (DTO `extra="forbid"`); ≥ 1 ítem y sin repuestos repetidos; UoW: verifica catálogo no vacío (409 propio), vehículo vigente, repuestos vigentes; copia `precio_unitario`; calcula `total` en servidor; orden PENDIENTE + ítems + historial `null → PENDIENTE`; repuesto inexistente/baja → 409 y no queda orden (RN10, RN19). Caso PDF C10
  - `GET /estados-orden` (autenticado, por `posicion`)
- **Dependencias**: `C-10, C-11`
- **Governance**: ALTO (transacción multi-tabla, núcleo del dominio)
- **Responsable**: `propose` Nico · `apply` Nico (Mati revisa propose y apply)
- **Leer antes**:
  - `knowledge-base/07_flujos_principales.md` §Flujo 4
  - `knowledge-base/05_reglas_de_negocio.md` RN10, RN16, RN19
  - `knowledge-base/06_funcionalidades.md` §Épica 6 (US-050)
  - `knowledge-base/04_modelo_de_datos.md` §estado_orden, §orden_trabajo, §item_orden

### [C-14] `ordenes-transiciones`
- **Estado**: `[ ]` pendiente
- **Scope**:
  - `POST /ordenes/{id}/iniciar` (MECANICO): PENDIENTE → EN_REPARACION, el mecánico queda asignado; otro estado → 409. Caso PDF C11 (orden #2 requiere reponer antes de terminar)
  - `POST /ordenes/{id}/terminar` (mecánico asignado o ADMIN): un UoW valida permiso (403) y estado (409), descuenta stock de cada ítem por el punto único de escritura, crea `movimiento_stock` (cantidad negativa, `orden_id`), cambia a TERMINADA + `historial_estado_orden`; falta de stock → 409 con rollback total (RN13); `BackgroundTasks` (aviso simulado `sleep(0.5)` + log) agendado sólo tras el commit. Caso PDF C12
  - `POST /ordenes/{id}/cancelar` (RECEPCION, ADMIN o dueño del vehículo, sin `requiere_rol`): identificar actor y relación → 403 primero, luego estado PENDIENTE → CANCELADA, otro → 409 (RN12); historial. Caso PDF C13
  - Servicio de transiciones guiado por `es_final` del catálogo
- **Dependencias**: `C-13, C-12`
- **Governance**: CRITICO (stock + permisos por dueño + atomicidad; núcleo del 20 % de Repos/UoW)
- **Responsable**: `propose` Nico · `apply` Nico (Mati revisa propose y apply)
- **Leer antes**:
  - `knowledge-base/07_flujos_principales.md` §Flujo 5, §Flujo 6
  - `knowledge-base/05_reglas_de_negocio.md` RN11, RN12, RN13, RN14, RN15
  - `knowledge-base/06_funcionalidades.md` §Épica 6 (US-051)
  - `knowledge-base/03_actores_y_roles.md` §RBAC (rutas /ordenes), nota "Cancelar no lleva requiere_rol"
  - `knowledge-base/10_preguntas_abiertas.md` IN-04

### [C-15] `ordenes-lecturas-sin-n-plus-1`
- **Estado**: `[ ]` pendiente
- **Scope**:
  - `GET /ordenes?estado&page&size` (personal; estado inválido → 422; `total` con los mismos filtros)
  - `GET /ordenes/{id}` (personal o dueño del vehículo; 403/404): vehículo, cliente, ítems, repuesto e historial con `selectinload`/`joinedload` dentro del repositorio; número fijo de consultas (2 vs 4 ítems → mismas consultas). Evidencia caso PDF C15 (log con `SQL_ECHO=true`)
  - `GET /mis-ordenes?page&size` (autenticado, sólo órdenes de sus vehículos, RN17). Caso PDF C17
  - Sin carga perezosa ni llamadas bloqueantes en handlers (Ej.8)
- **Dependencias**: `C-13`
- **Governance**: MEDIO
- **Responsable**: `propose` Nico · `apply` Lauti
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 6 (US-052)
  - `knowledge-base/08_arquitectura_propuesta.md` §Patrones (Eager loading)
  - `knowledge-base/05_reglas_de_negocio.md` RN17
  - `knowledge-base/04_modelo_de_datos.md` §Decisiones de modelado (navegación en ambos extremos)

---

## FASE 6 — Verificación y entregables (Ej.1-Ej.8, cierre)

### [C-16] `verificacion-http-readme`
- **Estado**: `[ ]` pendiente
- **Scope**:
  - Archivos `.http` en `test/` para los casos PDF C01…C19, con respuesta esperada en comentario; evidencia de C14 (`solo_agregado.sql`) y C15 (consultas fijas)
  - Verificación end-to-end de la matriz RBAC (401 vs 403, 404, 409, 422, 429) contra el seed
  - `README.md`: pasos desde cero (venv, `pip install`, `.env` con clave generada con `secrets.token_urlsafe`, `alembic upgrade head`, `python seed.py`, `uvicorn main:app`); integrantes
  - Chequeo de condición bloqueante: `alembic upgrade head` sobre base vacía, ciclo `upgrade/downgrade/upgrade`, sin credenciales reales en el repo (revisar `.gitignore`, `env.example`, `alembic.ini`)
- **Dependencias**: `C-06, C-09, C-14, C-15`
- **Governance**: BAJO
- **Responsable**: `propose` Nico · `apply` Lauti (cierre); cada uno los `.http` de su módulo (ver REPARTO §6)
- **Leer antes**:
  - `knowledge-base/06_funcionalidades.md` §Épica 8 (US-070)
  - `knowledge-base/03_actores_y_roles.md` §Matriz de permisos
  - `knowledge-base/07_flujos_principales.md` §Flujo 9
  - `knowledge-base/01_vision_y_objetivos.md` §Métricas de éxito

---

## Resumen

| Fase | Changes | Governance máx. |
|------|---------|-----------------|
| 1 Fundación | C-01 | MEDIO |
| 2 Capas, modelo, migraciones | C-02, C-03, C-04 | CRITICO |
| 3 Auth y autorización | C-05, C-06, C-07, C-08, C-09 | CRITICO |
| 4 Clientes y repuestos | C-10, C-11, C-12 | ALTO |
| 5 Órdenes | C-13, C-14, C-15 | CRITICO |
| 6 Verificación | C-16 | BAJO |

**Total**: 16 changes · 6 fases · camino crítico de 9 changes · 8 gates (GATE 0-7).
**Estado (2026-10-30)**: C-01…C-05, C-07…C-09, C-11 y C-12 completados; C-06 propuesto; C-10 implementado sin archivar; C-13 propuesto (en otra rama); próximo: C-13.
