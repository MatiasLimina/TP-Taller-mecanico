# Proposal — C-06 seed-script

## Why

Una base recién migrada no sirve para probar nada: el catálogo `estado_orden` nace vacío (sin él crear una orden responde 409, RN19), no hay ningún ADMIN (hoy los `.http` lo fabrican con `psql`) y no hay clientes, repuestos ni órdenes. La consigna pide un `seed.py` que **vacíe la base y cargue un estado inicial conocido** antes de cada archivo de pruebas (Flujo 9, US-070), y los changes que siguen (C-10…C-16) escriben sus casos `.http` contra ese estado. Es el último requisito de la fase 3 que C-16 necesita fuera del camino crítico, y ya están sus dependencias: la protección de sólo agregado (C-04, que deja pasar `TRUNCATE` a propósito para el seed) y `hash_password` (C-05).

## What Changes

- **`seed.py` nuevo, en la raíz** (`python seed.py`, después de `alembic upgrade head`): en **una sola transacción** vacía las 13 tablas del dominio con `TRUNCATE … RESTART IDENTITY CASCADE` (el disparador de sólo agregado es por fila y no lo bloquea; `alembic_version` no se toca) y carga el estado inicial. Correrlo dos veces deja el mismo estado, con los mismos ids; si algo falla, la base queda como estaba.
- **Estado inicial** (KB 04 §Seed data inicial):
  - catálogo `estado_orden` primero: PENDIENTE 1, EN_REPARACION 2, TERMINADA 3 (final), CANCELADA 4 (final), cada uno con descripción;
  - 7 usuarios `@example.com`: `admin@` y `admin2@` (ADMIN, **sin `vence_en`**, heredado de C-09 S-09), `recepcion@` (RECEPCION), `mecanico@` y `mecanico2@` (MECANICO), `cliente@` (CLIENTE) y `nuevo@` (MECANICO, con `debe_cambiar_password`); contraseñas de mentira sólo en `seed.py`, hasheadas con `app/core/security.py` **antes** de abrir la transacción;
  - clientes Laura (con el usuario `cliente@`, dos vehículos) y Jorge (sin usuario, un vehículo);
  - cuatro repuestos, cada stock cargado como movimiento `Stock inicial`; historial de precio del filtro de aceite 8000 → 8500;
  - orden #1 PENDIENTE (primer vehículo de Laura) y orden #2 EN_REPARACION (vehículo de Jorge, asignada a `mecanico@`, **4 bujías con 2 en stock, a propósito**: IN-04), con sus ítems, totales e historial de estados;
  - una línea de `evento_seguridad` con actor `SISTEMA`: `Carga de los datos iniciales`.
- **Correos verificados antes de tocar la base**: cada correo del seed se valida con el mismo tipo que usa la API (`CorreoNormalizado`); si tiene mayúsculas, espacios o un dominio que `EmailStr` rechaza (`.local`, `.test`, `.localhost`), el seed **falla** sin conectarse (no normaliza en silencio).
- **Verificación sin pytest**: `test/seed.sql` (consultas de sólo lectura con el resultado esperado en comentario, para psql) y `test/seed.http` (login de cada usuario del seed, roles vigentes, cambio obligatorio de `nuevo@`, evento `SISTEMA` en `GET /eventos`).
- **Encabezados de `test/auth.http` y `test/personal.http`**: instrucciones para correrlos después del seed (la limpieza `LIKE '%@example.com'` de `auth.http` chocaría con los usuarios del seed; el caso 62 de `personal.http` exige que no haya otro ADMIN sin vencimiento). Sólo comentarios del encabezado; ningún caso cambia.

Fuera de alcance: README con los pasos de puesta en marcha (C-16); endpoints de clientes, repuestos y órdenes (C-10…C-15); cualquier migración nueva o cambio de modelos; un modo "sin vaciar" o parcial del seed.

## Capabilities

### New Capabilities
- `seed-data`: recarga del estado inicial conocido de la base (`seed.py`): vaciado completo, idempotencia y atomicidad, el contenido exacto que carga (catálogo, usuarios y roles, clientes y vehículos, repuestos con su stock y precio, órdenes de ejemplo, evento `SISTEMA`), la verificación de correos y el manejo de las contraseñas de prueba.

### Modified Capabilities
- `security-events`: «Operaciones que dejan evento» y «Actor y acción del evento» pasan a contemplar la línea de la carga de datos iniciales, cuyo actor es el texto `SISTEMA` (no un correo).

## Impact

- **Código nuevo**: `seed.py` (raíz), `test/seed.sql`, `test/seed.http`.
- **Código modificado**: sólo los comentarios de encabezado de `test/auth.http` y `test/personal.http`.
- **Sin cambios**: `app/**` (el seed usa `get_settings`, `create_engine`/`create_session_factory`, `UnitOfWork`, `BaseRepository`, `hash_password`, `CorreoNormalizado` y los modelos tal como están), `migrations/`, `test/solo_agregado.sql`, `env.example`.
- **Dependencias**: ninguna nueva.
- **Base de datos**: `seed.py` borra **todos** los datos del dominio de la base configurada en `.env`. Es una herramienta de desarrollo y pruebas; nunca se corre contra datos reales.
- **Downstream**: C-10…C-15 y C-16 escriben sus `.http` contra este estado (ids deterministas, contraseñas de `seed.py`); C-12 repone bujías para que la orden #2 pueda terminarse (IN-04).
- **Governance**: MEDIO (datos de prueba; credenciales ficticias, nunca reales). Se implementa con checkpoints; los supuestos de `design.md` (S-01…S-10) se confirman antes del apply.
