# Proposal — C-03 domain-models-migration

## Why

C-02 dejó el cimiento genérico (repositorios, Unit of Work, traducción de errores) pero la base sigue sin tablas: `migrations/versions/` está vacío y `migrations/env.py` tiene el comentario «C-03: importar aquí app.modules.*.models». Todo lo que sigue en el camino crítico (C-04 trigger, C-06 seed, C-07 auth, C-10…C-14 módulos) referencia estos modelos, y la consigna los evalúa directamente: Ej.2 «Modelos, relaciones y migraciones» pesa 14 % (restricciones, índices únicos parciales, catálogo con clave foránea, navegación, migración autogenerada). Además, la traducción específica de errores de C-02 (`restriccion_violada(exc) == "uq_usuario_email"`) depende de que C-03 fije **nombres estables de restricciones**. Es el GATE 2 del roadmap (habilita el fork C-04 / C-06 / C-07), con governance CRITICO.

## What Changes

- **Modelos SQLModel de las 13 tablas** con los nombres de tablas y columnas obligatorios de la consigna, uno por dominio en `app/modules/<m>/models.py`:
  - `usuarios`: `usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`.
  - `clientes`: `cliente`, `vehiculo`.
  - `repuestos`: `repuesto`, `movimiento_stock`, `historial_precio_repuesto`.
  - `ordenes`: `estado_orden` (catálogo, PK `codigo`), `orden_trabajo`, `item_orden`, `historial_estado_orden`.
- **Restricciones en la base**: `UNIQUE` (`usuario.email`, `cliente.usuario_id`, `cliente.documento`, `estado_orden.posicion`, `item_orden(orden_id, repuesto_id)`); los tres **índices únicos parciales** con `postgresql_where` (`asignacion_rol(usuario_id, rol) WHERE revocada_en IS NULL`, `vehiculo(patente) WHERE borrado_en IS NULL`, `repuesto(codigo) WHERE borrado_en IS NULL`); todos los `CHECK` de la consigna; claves foráneas (incluidas `orden_trabajo.estado`, `historial_estado_orden.desde_estado`/`hasta_estado` → `estado_orden.codigo`, sin `CHECK` con la lista de estados); índice en cada clave foránea; índice `intento_acceso(email, ip, cuando)`.
- **Tipos**: fechas `timestamptz` (Python `datetime` con zona); dinero `NUMERIC(10,2)` / `NUMERIC(12,2)` ↔ `Decimal`, nunca `float`.
- **Nombres de restricción estables** (convención de nombres en la metadata) para que los servicios traduzcan una violación concreta a su mensaje (RN01, RN03, RN18).
- **Relaciones navegables en ambos extremos** de cada relación que se lee: asociación, composición `orden_trabajo` ◆ `item_orden` (el ítem no existe sin su orden), uno a uno opcional `Usuario.cliente` (objeto, no lista) y catálogo de estados; ninguna relación se carga de forma perezosa (la precarga la declara el repositorio, C-15).
- **Enums de dominio en código**: `EstadoOrden…` (PENDIENTE, EN_REPARACION, TERMINADA, CANCELADA), coherente con las filas que cargará `seed.py` (C-06), y `Rol` (ADMIN, RECEPCION, MECANICO, CLIENTE), coherente con el `CHECK` de `asignacion_rol`.
- **Registro de modelos para Alembic y para la aplicación**: un único punto que importa los cuatro `models.py`, usado por `migrations/env.py` (autogenerate ve las 13 tablas) y por la aplicación (las relaciones entre módulos se resuelven siempre).
- **Migración 1** generada con `alembic revision --autogenerate`: crea las 13 tablas con índices, CHECKs y FKs, deja el catálogo `estado_orden` **vacío**, y lleva el comentario «leída antes de aplicar» tras la revisión manual. Se verifica `alembic upgrade head` sobre base vacía, `alembic check` sin diferencias y el ciclo `downgrade base` → `upgrade head`.
- Sin endpoints, servicios, repositorios de módulo ni datos (seed es C-06; trigger de sólo agregado es C-04).

## Capabilities

### New Capabilities
- `domain-data-model`: esquema relacional del dominio del taller: tablas y columnas obligatorias, tipos (fechas con zona, dinero exacto), unicidad (común y parcial entre vigentes), CHECKs, catálogo de estados por clave foránea, índices de FK, nombres estables de restricciones, navegación entre entidades sin carga perezosa y coherencia de los enums de código con el catálogo y el CHECK de roles.

### Modified Capabilities
- `schema-migrations`: el requisito «Upgrade sobre base vacía» deja de decir «ninguna revisión de dominio todavía»: ahora `upgrade head` crea el esquema completo del dominio con el catálogo vacío. Se agregan requisitos de migración inicial autogenerada y revisada (comentario «leída antes de aplicar»), de modelos y migraciones sincronizados, y de ciclo `upgrade head` → `downgrade base` → `upgrade head`.

## Impact

- **Código nuevo**: `app/modules/usuarios/models.py`, `app/modules/clientes/models.py`, `app/modules/repuestos/models.py`, `app/modules/ordenes/models.py`; un módulo compartido de tipos/convenciones del modelo en `app/core/` y un registro de modelos (ubicación y nombres a confirmar, ver design — Open Questions); `migrations/versions/<rev>_esquema_inicial.py` (autogenerado + revisado).
- **Código modificado**: `migrations/env.py` (importar el registro de modelos; reemplaza el comentario de C-01); `main.py` (una línea de import del registro, para que las relaciones entre módulos se configuren al arrancar).
- **Base de datos**: primera migración de dominio. La verificación de restricciones usa una base descartable propia (no la de desarrollo).
- **Downstream**: C-04 (trigger sobre `historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`; migración 2 encadenada a esta), C-06 (seed: catálogo con los valores del enum; vaciar con reinicio de secuencias), C-07 (registro: `usuario` + `asignacion_rol` + `cliente`; mensajes de 409 por nombre de restricción), C-08 (roles vigentes desde `asignacion_rol`), C-10/C-11/C-13 (repos y UoW por módulo sobre estos modelos; `SoftDeleteRepository` exige `borrado_en`), C-15 (precarga explícita: las relaciones fallan si se leen sin precargar).
- **Equipo** (docs/REPARTO_DE_TAREAS.md): sólo el integrante A crea migraciones; B y C consumen los modelos. No depende de C-05 (rama sin mergear).
- **Nombre del change**: el CLI exige minúsculas → `c-03-domain-models-migration` (= `C-03 domain-models-migration` de CHANGES.md).
