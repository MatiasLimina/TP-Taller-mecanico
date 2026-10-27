# Proposal — C-04 append-only-trigger-migration

## Why

C-03 dejó las 13 tablas creadas por la migración 1 (`1c921a1fe62f`, cabeza actual), pero nada impide hoy que alguien corrija o borre una fila de `historial_estado_orden`, `movimiento_stock` o `historial_precio_repuesto`. RN15 exige que esas tres tablas sean de **sólo agregado** y que lo garantice la base («venga de donde venga», Ej.7 de la consigna, 10 %), no la disciplina del servicio. La comparación automática de Alembic no ve funciones ni disparadores, por eso la consigna pide una **segunda migración escrita a mano** (Ej.2) y la evidencia en psql del caso C-14 (`test/solo_agregado.sql`). Es el siguiente paso después del GATE 2 y es prerequisito de C-06 (el seed tiene que vaciar estas tablas sabiendo cómo se comporta el disparador).

## What Changes

- **Migración 2, escrita a mano** (no `--autogenerate`), encadenada a `1c921a1fe62f`:
  - una función PL/pgSQL compartida que rechaza la operación con un error propio que nombra la tabla y la operación;
  - un disparador sobre cada una de las tres tablas que la invoca ante `UPDATE` y `DELETE`, sea quien sea el que lo intente (aplicación, psql, dueño de la tabla);
  - comentario «leída antes de aplicar» con lo revisado, como la migración 1;
  - `downgrade` que elimina los tres disparadores y luego la función, dejando el esquema exactamente como lo dejó la migración 1.
- **`test/solo_agregado.sql`** (evidencia del caso C-14, corrida con `psql`): seis intentos rechazados por el disparador (UPDATE y DELETE × 3 tablas) y un séptimo rechazado por la clave foránea (orden con un estado que no está en el catálogo). El script no deja filas en la base.
- **Verificación del ciclo** `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` con las dos revisiones, más `alembic check` sin diferencias (los disparadores no son parte de la metadata).
- Sin cambios en modelos, servicios ni endpoints. `INSERT` sobre las tres tablas sigue permitido.

## Capabilities

### New Capabilities
- `append-only-history`: garantía en la base de que los registros históricos (`historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`) sólo admiten altas: qué operaciones se rechazan, cómo se reporta el rechazo, qué sigue permitido y la evidencia reproducible del caso C-14.

### Modified Capabilities
- `schema-migrations`: «Upgrade sobre base vacía» y «Ciclo de upgrade y downgrade» pasan a incluir la segunda revisión (disparadores instalados tras `upgrade head`, eliminados tras `downgrade base`). Se agrega el requisito de una migración manual y revisada para los objetos que la comparación automática no ve (función y disparadores), con `downgrade` que los elimina.

## Impact

- **Código nuevo**: `migrations/versions/<rev>_solo_agregado.py` (revisión creada con `alembic revision -m`, `down_revision = "1c921a1fe62f"`); `test/solo_agregado.sql`.
- **Código modificado**: ninguno (C-03 ya dejó documentado en `app/modules/repuestos/models.py` que el trigger lo impone C-04).
- **Base de datos**: una función y tres disparadores. La verificación usa una base descartable; aplicar a la base de desarrollo sólo con permiso explícito.
- **Comportamiento de la API**: ninguno visible hoy (ningún servicio actualiza ni borra estas tablas). Si un defecto futuro lo intentara, la base lo rechaza y la API responde 500 genérico (no 4xx), porque es un defecto del servidor, no una entrada inválida (ver design).
- **Downstream**: C-06 (`seed.py` debe vaciar estas tablas con `TRUNCATE … RESTART IDENTITY CASCADE`: `DELETE` queda rechazado); C-12/C-13/C-14 (los servicios sólo insertan en historiales y movimientos; nunca «corrigen» una fila); C-16 (evidencia psql de C-14 en el README y ciclo de migraciones).
- **Equipo** (docs/REPARTO_DE_TAREAS.md): sólo el integrante A crea migraciones; esta es la última revisión prevista del TP.
- **Nombre del change**: el CLI exige minúsculas → `c-04-append-only-trigger-migration` (= `C-04 append-only-trigger-migration` de CHANGES.md).
