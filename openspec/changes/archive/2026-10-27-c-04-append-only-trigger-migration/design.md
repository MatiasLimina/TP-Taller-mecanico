# Design — C-04 append-only-trigger-migration

## Context

Motivación en proposal.md (Why); requisitos en `specs/append-only-history` y `specs/schema-migrations`. Estado actual y restricciones que moldean el diseño:

- **Cadena de Alembic**: una sola revisión, `1c921a1fe62f_esquema_inicial.py` (autogenerada, revisada, cabeza actual). `migrations/script.py.mako` importa `sqlalchemy as sa` y `sqlmodel` siempre; en una revisión manual que sólo usa `op.execute` esos imports quedan sin uso y `ruff check .` (F401) los marca. PostgreSQL tiene DDL transaccional y Alembic corre cada revisión dentro de una transacción: si algo falla a mitad de camino, la revisión entera se revierte.
- **FKs hacia las tablas de sólo agregado** (migración 1, C-03 D6): todas `NO ACTION`; `ON DELETE CASCADE` existe sólo en `item_orden.orden_id`. Borrar con SQL una orden, un repuesto o un usuario que tiene historial falla por la FK (23503) **antes** de tocar el historial: ningún borrado en cascada llega hoy a estas tablas.
- **ORM** (`app/modules/ordenes/models.py`): `OrdenTrabajo.historial` no declara `passive_deletes` (sí lo hace `items`). Un `session.delete(orden)` con historial intentaría poner `orden_id = NULL` en el historial (un `UPDATE`) o fallaría antes por `lazy="raise"`; en cualquier caso el borrado no prospera. Ningún endpoint borra órdenes: cancelar es un cambio de estado (C-14). `movimiento_stock` e `historial_precio_repuesto` no tienen relación ORM hacia sus FKs `usuario_id`/`orden_id`.
- **Traducción de errores** (`app/core/errores.py`, C-02): `IntegrityError` → 409 (23505/23503) o 422 (resto de clase 23); `DBAPIError` con SQLSTATE `22xxx` → 422; cualquier otro `DBAPIError` → 500 genérico con el SQLSTATE sólo en el log. Por lo tanto el SQLSTATE que elija el disparador decide si un intento de modificar el historial se ve como error del cliente (4xx) o como defecto del servidor (500).
- **Seed (C-06, posterior)**: «vacía las tablas y carga». C-03 dejó anotado para C-06 que el vaciado es con `TRUNCATE … RESTART IDENTITY CASCADE` (ids de órdenes #1/#2 y FKs `NO ACTION`) y que el disparador de C-04 es por fila y no se dispara con `TRUNCATE`.
- **Consigna**: Ej.7 «rechaza cualquier UPDATE o DELETE … venga de donde venga»; Ej.2 «la segunda [migración], escrita a mano, con el disparador… porque la comparación automática no ve funciones ni disparadores»; caso C-14 «los seis, rechazados por el disparador; el último, por la clave foránea» con captura de psql; «antes de cada archivo se corre `python seed.py`» (pero el seed todavía no existe).
- **Entorno**: PostgreSQL 18.6 local con `psql`/`createdb`/`dropdb` en el PATH (la consigna pide ≥ 16; nada de lo que sigue depende de funciones posteriores a la 11). Consola de Windows: los acentos en mensajes del servidor pueden verse mal en psql según la página de códigos.
- **Sin pytest**: verificación por comandos (`alembic`, `psql`) y un script descartable en el scratchpad contra una base descartable, como C-03 D9.

## Goals / Non-Goals

**Goals:**
- Que la garantía de sólo agregado viva **en la base** y alcance a cualquier sesión, incluido el rol dueño con el que se conecta la aplicación.
- Que el rechazo sea **inconfundible**: nombra tabla y operación, y no se disfraza de error del cliente en la API.
- Que la revisión sea **reversible y atómica**: `downgrade` deja el esquema byte a byte como la migración 1; un fallo a mitad de camino no deja objetos sueltos.
- Que la evidencia C-14 sea **reproducible** sobre cualquier base migrada, con o sin seed, y que no deje residuos (filas que, justamente, ya no se podrían borrar).

**Non-Goals:**
- Segundo mecanismo por permisos (rol de base sin `UPDATE`/`DELETE` sobre estas tablas, sección 6.9 / DD-08): la consigna no lo pide y el TP usa un solo rol.
- Cambios en modelos (p. ej. `passive_deletes` en `OrdenTrabajo.historial`), servicios o endpoints.
- `seed.py` (C-06) y la evidencia en el README (C-16).
- Bloquear operaciones de superusuario que desactivan disparadores (`session_replication_role = replica`) o el `ALTER TABLE … DISABLE TRIGGER` del dueño: son administración del esquema, no escrituras de datos.

## Decisions

> Governance **ALTO**: D2–D7 y D9 son **propuestas** que el usuario confirma en el grupo 0 de tasks antes de escribir la migración (Open Questions Q1–Q8). Si alguna cambia, se actualizan este design y los specs antes del apply.

### D1 — Revisión manual creada con `alembic revision -m`, SQL literal con `op.execute`
- Se crea con `alembic revision -m "solo agregado"` (sin `--autogenerate`), lo que fija un id aleatorio y `down_revision = "1c921a1fe62f"`. Se verifica con `alembic heads` (una sola cabeza) y `alembic history`.
- `upgrade()`/`downgrade()` usan `op.execute()` con DDL literal (sin datos del usuario: no aplica la regla de parámetros ligados). Sin `sa.DDL` ni `ReplaceableObject`: tres sentencias por lado no justifican la abstracción.
- Encabezado: docstring con el comentario **«Leída antes de aplicar»** (fecha, qué se revisó: función, tres disparadores, orden del downgrade, ninguna operación sobre tablas) y la mención de que es manual porque autogenerate no ve funciones ni disparadores. Se quitan los imports sin uso que deja la plantilla (`sa`, `sqlmodel`) para que `ruff check .` pase; a diferencia de la migración 1, aquí las operaciones son propias y se pueden editar.
- *Alternativa*: `alembic_utils` (entidades `PGFunction`/`PGTrigger` que autogenerate sí compara) — descartada: dependencia nueva y la consigna pide explícitamente una migración escrita a mano.

### D2 — Una función compartida para las tres tablas (Q5)
`CREATE FUNCTION rechazar_cambio_solo_agregado() RETURNS trigger LANGUAGE plpgsql` que **siempre** lanza la excepción usando `TG_TABLE_NAME` y `TG_OP`; nunca hace `RETURN NULL` (en un disparador BEFORE eso saltearía la fila en silencio: el intento «funcionaría» con 0 filas afectadas y no quedaría rastro). No es `SECURITY DEFINER` y no referencia ningún objeto, así que el `search_path` no la afecta.
- *Alternativa*: una función por tabla con mensaje a medida — triplica el código y el downgrade sin ganar información (el mensaje ya nombra la tabla).
- `CREATE FUNCTION` (no `CREATE OR REPLACE`): si la función ya existe, la base está en un estado que Alembic no conoce y conviene que el upgrade falle.

### D3 — `BEFORE UPDATE OR DELETE … FOR EACH ROW` (Q1, Q2)
Un disparador por tabla, mismo nombre en las tres: `trg_solo_agregado` (el nombre de un disparador es por tabla).
- **BEFORE vs AFTER**: BEFORE corta antes de modificar la fila, de actualizar índices y de evaluar restricciones, y no encola eventos; el mensaje que ve quien lo intenta es siempre el del disparador (no, por ejemplo, un NOT NULL de un `SET orden_id = NULL`). AFTER también revierte, pero después de haber hecho el trabajo. Ambos abortan la sentencia y dejan la transacción en error.
- **ROW vs STATEMENT**: por fila es la forma canónica del curso, permite que el mensaje sea por fila y no cuesta nada en el camino normal (sólo se dispara ante UPDATE/DELETE, que nunca ocurren; los INSERT no lo invocan). Consecuencia a conocer: un `UPDATE`/`DELETE` que no alcanza ninguna fila **no** da error (`UPDATE 0`). Un disparador por sentencia rechazaría incluso `DELETE … WHERE false`, pero ese caso no altera ningún dato, así que no cambia la garantía de RN15; sí obliga a que la evidencia C-14 actúe sobre filas existentes (D9).
- Cubre «venga de donde venga»: se dispara para cualquier rol (incluido el dueño) y también para las acciones referenciales de una FK (si alguien agregara en el futuro `ON DELETE CASCADE`/`SET NULL` hacia estas tablas, el borrado del padre quedaría rechazado por el disparador; ver D6).

### D4 — Error: SQLSTATE `P0001`, mensaje ASCII que nombra tabla y operación (Q4)
`RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = format('%s rechazado: %s es de solo agregado', TG_OP, TG_TABLE_NAME), HINT = 'Registrar una fila nueva en lugar de modificar o borrar una existente'` (texto final a ajustar en el apply; forma fija: operación + tabla).
- **Por qué no clase 23** (p. ej. `23001 restrict_violation`, que parecería natural): asyncpg lo levantaría como violación de integridad, SQLAlchemy como `IntegrityError` y `app/core/errores.py` lo respondería 422 «Los datos no cumplen las restricciones» — un defecto del servidor (un servicio que intenta corregir el historial) quedaría disfrazado de error del cliente y sin traza en el log. Con `P0001` cae en el `DBAPIError` genérico → 500 «Error interno del servidor» y `logger.exception` con el SQLSTATE, que es exactamente lo que pide error-translation para un defecto.
- **Por qué no `42501 insufficient_privilege`**: también daría 500, pero confunde la evidencia C-14 con un problema de permisos (la sección 6.9 es justamente el otro mecanismo).
- **ASCII** («solo», sin tilde) para que la captura de psql de C-14 se lea bien en la consola de Windows sin depender de `client_encoding`/página de códigos.

### D5 — `TRUNCATE` no se bloquea (Q3)
El disparador por fila no se dispara con `TRUNCATE`, y no se agrega un `BEFORE TRUNCATE … FOR EACH STATEMENT`.
- Razón: `seed.py` (C-06) necesita vaciar estas tablas para ser idempotente, y `DELETE` queda rechazado. `TRUNCATE … RESTART IDENTITY CASCADE` es la vía ya anotada por C-03 para C-06; la consigna habla de «UPDATE o DELETE», no de vaciado administrativo. La aplicación nunca ejecuta `TRUNCATE`.
- *Alternativa*: bloquear también `TRUNCATE` y que el seed haga `ALTER TABLE … DISABLE TRIGGER`/`ENABLE TRIGGER` (o recree la base) — más estricto, pero el seed pasaría a desactivar la protección que demuestra C-14, y un seed que falla a mitad podría dejarla desactivada. Si el usuario la prefiere, cambia el spec «Vaciado completo para recarga» y el scope de C-06.

### D6 — Postura sobre borrados en cascada y el ORM
- Las FKs hacia las tres tablas quedan `NO ACTION` (C-03 no cambia): borrar el padre con historial falla por FK (23503 → 409 si llegara a la API), antes de que el disparador intervenga. Spec: «Borrar la orden dueña del historial».
- **No se debe** agregar `ON DELETE CASCADE`/`SET NULL` hacia estas tablas: contradice RN15 y, con el disparador, el borrado del padre quedaría rechazado igual (por `P0001` en vez de 23503).
- `OrdenTrabajo.historial` sin `passive_deletes`: no se toca en C-04 (no hay borrado de órdenes; el cambio no altera el esquema ni `alembic check`). Si algún día se borrara una orden desde el ORM, conviene `passive_deletes="all"` para que responda la FK (409) y no el disparador (500) — Q10, diferible.

### D7 — Downgrade explícito, en orden inverso (Q6)
`downgrade()`: `DROP TRIGGER trg_solo_agregado ON <tabla>` para las tres tablas, en orden inverso al de creación, y después `DROP FUNCTION rechazar_cambio_solo_agregado()`.
- Sin `CASCADE` ni `IF EXISTS`: si el estado de la base no es el que dejó el upgrade, el downgrade falla dentro de su transacción y no borra nada a ciegas. Primero los disparadores porque la función no se puede eliminar sin `CASCADE` mientras algún disparador dependa de ella.
- *Alternativa*: `DROP FUNCTION … CASCADE` (una sola línea) — oculta qué se elimina y arrastraría cualquier otro objeto dependiente.
- `downgrade base` funciona con datos en las tablas: el `downgrade` de la migración 1 usa `DROP TABLE`, que no es `DELETE` y no dispara nada (además ya no hay disparador a esa altura).

### D8 — Nombres (Q9, diferible)
Función `rechazar_cambio_solo_agregado()`; disparador `trg_solo_agregado` en cada tabla. No forman parte de la metadata de SQLModel (la convención `pk_/fk_/uq_/ck_/ix_` no aplica) y no los ve `alembic check`.

### D9 — `test/solo_agregado.sql`: autosuficiente, dentro de una transacción que se revierte (Q8)
Estructura del script (psql):
1. Encabezado con uso (`psql -d <base> -f test/solo_agregado.sql`, conexión por las variables `PG*`/parámetros de psql, sin credenciales en el archivo) y qué demuestra (C-14, RN15).
2. `\set ON_ERROR_STOP off`, `\set ON_ERROR_ROLLBACK on` (cada sentencia en su propio savepoint implícito: un rechazo no aborta la transacción) y `\set VERBOSITY verbose` (la salida incluye el SQLSTATE: `P0001` seis veces y `23503` una).
3. `BEGIN;` y datos propios mínimos, capturando ids con `RETURNING … \gset`: estados del catálogo con `ON CONFLICT DO NOTHING` (convive con el seed), usuario/cliente/vehículo/repuesto con valores únicos propios del script (correo `@example.test`, patente y código que el seed no usa), una orden, y una fila en cada tabla de sólo agregado. Estas altas demuestran de paso que `INSERT` sigue permitido.
4. Los seis intentos (UPDATE y DELETE × 3 tablas) sobre las filas propias, cada uno precedido por `-- Esperado: ERROR P0001 … <OP> … <tabla>`.
5. El séptimo: `INSERT` de una orden con `estado = 'INEXISTENTE'`, precedido por `-- Esperado: ERROR 23503 … fk_orden_trabajo_estado_estado_orden`.
6. `ROLLBACK;` — nada queda en la base (importante: las filas de sólo agregado, una vez confirmadas, ya no se podrían borrar).
- *Alternativa*: apoyarse en las filas del seed — descartada: el seed es C-06 (posterior), y con disparador por fila un intento sobre una tabla vacía no muestra ningún rechazo. El script autosuficiente también funciona después del seed (spec «Con o sin datos de ejemplo»).
- Los valores concretos de los datos propios se toman de los CHECK y NOT NULL de la migración 1 al escribir el script.

### D10 — Verificación sin pytest (Q7)
Script descartable `verificar_c04.py` en el scratchpad (no se versiona), corrido con `.venv\Scripts\python -I` y `POSTGRES_DB=taller_verif_c04` como variable del proceso (no se edita `.env`), sobre la base descartable `taller_verif_c04`:
- consultas a `pg_trigger` (`NOT tgisinternal`, para excluir los disparadores internos de las FKs) y `pg_proc` para los escenarios de instalación y de ciclo;
- intentos de `UPDATE`/`DELETE`/`INSERT`/`TRUNCATE` con asyncpg dentro de transacciones revertidas, comprobando SQLSTATE, mensaje y que la fila sigue igual;
- un intento a través del motor de SQLAlchemy de la app para comprobar que la excepción es `DBAPIError` y no `IntegrityError`, que `sqlstate()` devuelve `P0001` y que el manejador de `app/core/errores.py` responde 500 con el cuerpo genérico;
- ejecución de `psql -f test/solo_agregado.sql` con conteo de filas de las 13 tablas antes y después.
RED: el script corre antes de crear la revisión y falla (no hay disparadores); GREEN tras la migración.

## Risks / Trade-offs

- [El dueño de la tabla puede `ALTER TABLE … DISABLE TRIGGER`; un superusuario puede usar `session_replication_role = replica`] → Es administración del esquema, fuera de RN15 tal como la evalúa la consigna. Defensa en profundidad por permisos (DD-08) queda documentada como no pedida.
- [`TRUNCATE` vacía las tablas sin pasar por el disparador] → Decisión deliberada (D5) para el seed; la aplicación nunca lo ejecuta. Se documenta en la migración y en el spec.
- [Un `UPDATE`/`DELETE` que no alcanza filas no da error] → No modifica datos; la evidencia C-14 actúa sobre filas existentes (D9).
- [Un servicio futuro intenta «corregir» un movimiento] → La base lo rechaza y la API responde 500 con log (D4): el defecto se ve en desarrollo en vez de quedar como 4xx silencioso.
- [`CREATE FUNCTION` falla si quedó una función homónima de pruebas manuales] → Verificación en base descartable; la revisión es atómica (DDL transaccional) y no deja objetos a medias.
- [Mojibake en la captura de psql en Windows] → Mensajes del disparador en ASCII (D4); los comentarios del script son UTF-8 pero psql no los imprime.
- [`ruff check .` sobre la revisión manual] → Se quitan los imports sin uso de la plantilla (D1); `git diff --check` limpio.

## Migration Plan

1. Checkpoints del grupo 0 de tasks resueltos (Q1–Q8).
2. Base descartable `taller_verif_c04` → `alembic upgrade head` (sólo la migración 1) → script de verificación en RED.
3. `alembic revision -m "solo agregado"` → escribir función, disparadores, downgrade y comentario de revisión → leerla → `upgrade head` → script en GREEN → `alembic check`.
4. `test/solo_agregado.sql` → ejecutarlo con psql sobre base vacía migrada y sobre base con datos; conteos iguales antes/después.
5. Ciclo `downgrade -1` → `upgrade head` → `downgrade base` → `upgrade head` con el script en cada paso.
6. Aplicar a la base de desarrollo (`upgrade head`) **sólo** con permiso explícito (Q7).
- **Rollback**: `alembic downgrade -1` elimina disparadores y función sin tocar tablas ni datos; revertir el archivo de la revisión y `test/solo_agregado.sql`. La base descartable se borra con `dropdb` al terminar.

## Open Questions

Las que cambian lo que se construye o los specs están como **checkpoints bloqueantes** en el grupo 0 de tasks (governance ALTO), con la propuesta del design como valor por defecto:
- **Q1** — Momento del disparador: **BEFORE** (propuesta, D3) vs AFTER.
- **Q2** — Granularidad: **FOR EACH ROW** (propuesta, D3) vs FOR EACH STATEMENT (rechazaría también sentencias que no alcanzan filas).
- **Q3** — `TRUNCATE`: **permitido** para el seed (propuesta, D5; coincide con la nota de C-03 para C-06) vs bloqueado con disparador por sentencia (cambia el spec «Vaciado completo para recarga» y el scope de C-06).
- **Q4** — Error: **SQLSTATE `P0001`** con mensaje ASCII «`<OP>` rechazado: `<tabla>` es de solo agregado» → 500 en la API (propuesta, D4) vs un código de clase 23 (→ 422) u otro.
- **Q5** — **Una función compartida** (propuesta, D2) vs una por tabla.
- **Q6** — Downgrade: **`DROP TRIGGER` ×3 y luego `DROP FUNCTION`, sin `CASCADE` ni `IF EXISTS`** (propuesta, D7) vs `DROP FUNCTION … CASCADE`.
- **Q7** — Permiso para crear y borrar la base descartable `taller_verif_c04`, y si al final se aplica `alembic upgrade head` a la base de desarrollo.
- **Q8** — `test/solo_agregado.sql` **autosuficiente con `ROLLBACK`** (propuesta, D9) vs dependiente de las filas del seed.

Diferibles sin cambiar specs, enfoque ni tasks:
- **Q9** — Nombres `rechazar_cambio_solo_agregado()` / `trg_solo_agregado` (D8).
- **Q10** — `passive_deletes="all"` en `OrdenTrabajo.historial` (D6): sin efecto hoy; se decide si alguna vez se borran órdenes.
- **Q11** — Segundo mecanismo por permisos de rol (DD-08): no pedido; queda como mejora opcional.
