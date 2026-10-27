# Design — C-03 domain-models-migration

## Context

Motivación en proposal.md (Why); requisitos en `specs/domain-data-model` y `specs/schema-migrations`. Estado actual y restricciones que moldean el diseño:

- **Código existente** (se respeta): `migrations/env.py` es la plantilla async de Alembic, toma la URL de `Settings` (nunca de `alembic.ini`), usa `target_metadata = SQLModel.metadata` y `compare_type=True`, y tiene el comentario «C-03: importar aquí app.modules.*.models». `migrations/script.py.mako` ya importa `sqlmodel` (los tipos que renderiza autogenerate lo necesitan). `migrations/versions/` está vacío. `app/modules/{usuarios,clientes,repuestos,ordenes}/` sólo tienen `__init__.py`.
- **Contratos de C-02 que C-03 alimenta**: `SoftDeleteRepository` exige un campo `borrado_en` y asigna `datetime.now(UTC)`; `IdRuta` acota los ids al rango de `INTEGER`; `restriccion_violada(exc)` lee el nombre de la restricción para mensajes específicos (ejemplo documentado: `uq_usuario_email`); C-02 D2 prohíbe `server_onupdate` (atributo expirado → carga perezosa → `MissingGreenlet`) y recomienda `lazy="raise"` en las relaciones.
- **Versiones en `.venv`**: SQLModel 0.0.48, SQLAlchemy 2.0.55, Alembic 1.20.1, Pydantic 2.14.1. Hallazgos en el código de SQLModel 0.0.48 (`sqlmodel/main.py`, `get_sqlalchemy_type`):
  - un campo `datetime` se mapea a `UTCDateTime()` (`TIMESTAMP WITH TIME ZONE`, rechaza en el bind un `datetime` sin zona y devuelve UTC) → las fechas con zona salen sin `sa_type` explícito;
  - un campo `Decimal` con `max_digits`/`decimal_places` se mapea a `Numeric(p, s)`;
  - un campo anotado con una subclase de `Enum` se mapea a `sa.Enum` → **crearía un tipo `ENUM` nativo de PostgreSQL**, que no es ni el `CHECK` de roles ni la FK al catálogo que pide la consigna;
  - `Relationship(cascade_delete=True)` → `cascade="all, delete-orphan"`; `passive_deletes` y `sa_relationship_kwargs` se pasan tal cual; `uselist` lo infiere SQLAlchemy por la dirección (del lado «uno» de una FK sería lista) → `Usuario.cliente` necesita `uselist=False` explícito.
- **Consigna Ej.2** (14 %) y reglas duras de CLAUDE.md: nombres obligatorios; `timestamptz`; `NUMERIC`/`Decimal`; tres índices únicos parciales con `postgresql_where`; estados por FK al catálogo (no `CHECK`); navegación en ambos extremos de cada relación que se lee; `Usuario.cliente` objeto; sólo Alembic (nunca `create_all`); migración 1 con `--autogenerate`, comentario «leída antes de aplicar», catálogo vacío; ninguna lectura perezosa.
- **Sin pytest**: la verificación es por comandos (`alembic`, `psql`) y un script descartable en el scratchpad contra una base descartable, como C-02 D10.
- **C-05** vive en una rama sin mergear y no define enums de roles: C-03 no depende de ella; el enum `Rol` nace acá.

## Goals / Non-Goals

**Goals:**
- Que todo lo que la consigna exige del esquema lo garantice la **base** (unicidad, CHECKs, FKs), no una consulta previa del servicio.
- Que cada violación tenga un **nombre estable** traducible a un mensaje propio (RN01/RN03/RN18) sin depender de nombres autogenerados por PostgreSQL.
- Que una lectura perezosa sea **imposible por accidente**: error explícito inmediato en vez de una consulta oculta o un `MissingGreenlet` intermitente.
- Que `alembic check` sea la prueba de que modelos y migración coinciden.

**Non-Goals:**
- Trigger de sólo agregado y `test/solo_agregado.sql` (C-04); filas del catálogo y datos de ejemplo (C-06).
- Repositorios, UoW y DTOs de cada módulo (C-07, C-10, C-11, C-13); `EstadoOrdenRepository` (C-13); precarga concreta del detalle de orden (C-15).
- Validaciones de contrato (longitudes, formato de email/patente, 72 bytes) — viven en los DTOs.
- Concurrencia sobre `stock` (DD-11, cap. 7).

## Decisions

### D1 — Un `models.py` por módulo, nombres de clase únicos, referencias por texto
- `app/modules/usuarios/models.py`: `Rol` (enum), `Usuario`, `AsignacionRol`, `IntentoAcceso`, `EventoSeguridad`.
- `app/modules/clientes/models.py`: `Cliente`, `Vehiculo`.
- `app/modules/repuestos/models.py`: `Repuesto`, `MovimientoStock`, `HistorialPrecioRepuesto`.
- `app/modules/ordenes/models.py`: enum de estados (D8), `EstadoOrden` (tabla catálogo), `OrdenTrabajo`, `ItemOrden`, `HistorialEstadoOrden`.
- `__tablename__` explícito en cada clase (no se confía en el nombre derivado de la clase).
- Las relaciones entre módulos se declaran con el nombre de la clase como **texto** (`"Cliente"`, `"OrdenTrabajo"`) y los imports para tipado van bajo `TYPE_CHECKING` → sin imports circulares (`usuarios` ↔ `clientes` ↔ `ordenes`). SQLAlchemy resuelve los nombres en el registro al configurar los mappers; por eso D3.
- Sin `from __future__ import annotations` en los `models.py` (SQLModel necesita las anotaciones evaluadas para construir columnas y relaciones).
- *Alternativa*: un único `app/models.py` con las 13 clases — descartada: rompe la estructura obligatoria por módulo (KB 08) y el reparto de dueños (B y C extienden sus módulos).

### D2 — Base compartida del modelo en `app/core/` (convención de nombres + utilidades)
Un módulo nuevo en `app/core/` (nombre propuesto `modelo_base.py`, Q3) que **todos** los `models.py` importan y que, al importarse:
- fija `SQLModel.metadata.naming_convention`:
```
pk: "pk_%(table_name)s"
fk: "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
uq: "uq_%(table_name)s_%(column_0_N_name)s"
ck: "ck_%(table_name)s_%(constraint_name)s"
ix: "ix_%(column_0_label)s"
```
- expone `ahora_utc() -> datetime` (`datetime.now(UTC)`, el mismo criterio que `soft_delete` de C-02) y la constante de relación sin carga perezosa (D6).

Como cada `models.py` la importa antes de declarar tablas, la convención está fijada antes de crear cualquier restricción (SQLAlchemy nombra al adjuntar la restricción a la tabla). Resultado: `uq_usuario_email` (el ejemplo de C-02 queda exacto), `uq_cliente_documento`, `uq_cliente_usuario_id`, `uq_estado_orden_posicion`, `uq_item_orden_orden_id_repuesto_id`, `fk_orden_trabajo_estado_estado_orden`, `ix_vehiculo_cliente_id`… Con `%(constraint_name)s` en `ck`, un `CHECK` sin nombre **falla al generar el DDL** → imposible olvidar nombrarlo. Los tres índices únicos parciales y el índice compuesto de `intento_acceso` llevan nombre explícito (D4). Todos los nombres caben en 63 caracteres (el más largo, `fk_historial_estado_orden_desde_estado_estado_orden`, tiene 51).
- *Alternativas*: `name=` explícito en cada restricción (verboso y fácil de omitir en una FK o un `unique=True`); dejar que PostgreSQL nombre (`usuario_email_key`) — descartado: los nombres dependen del motor y no son los que C-02 documentó.

### D3 — Registro único de modelos, usado por Alembic y por la aplicación
Un módulo agregador (nombre propuesto `app/modules/modelos.py`, Q3) que sólo importa los cuatro `models.py` y re-exporta las clases. Lo importan:
- `migrations/env.py` (reemplaza el comentario de C-01) → `SQLModel.metadata` tiene las 13 tablas cuando autogenerate compara;
- `main.py` (una línea) → al arrancar están todas las clases en el registro, y la primera consulta no falla con «expression 'Cliente' failed to locate a name» aunque un router sólo importe su propio módulo;
- `seed.py` (C-06) y cualquier script que use los modelos.
- *Alternativas*: importar los cuatro módulos en `app/modules/__init__.py` (efecto lateral implícito en cualquier `import app.modules.x`; difícil de ver en la corrección); repetir los cuatro imports en `env.py` y `main.py` (dos listas que se desincronizan al agregar un módulo).

### D4 — Restricciones e índices (mapa completo)
| Tabla | Restricción / índice | Nombre |
|---|---|---|
| usuario | `email` UNIQUE | `uq_usuario_email` |
| asignacion_rol | CHECK `rol IN (...)` (texto generado desde `Rol`, D8) | `ck_asignacion_rol_rol_valido` |
| asignacion_rol | UNIQUE parcial `(usuario_id, rol) WHERE revocada_en IS NULL` | `uq_asignacion_rol_usuario_id_rol` |
| intento_acceso | índice `(email, ip, cuando)` | `ix_intento_acceso_email_ip_cuando` |
| cliente | `usuario_id` UNIQUE (nulo permitido); `documento` UNIQUE | `uq_cliente_usuario_id`, `uq_cliente_documento` |
| vehiculo | UNIQUE parcial `(patente) WHERE borrado_en IS NULL`; CHECK `anio BETWEEN 1950 AND 2100` | `uq_vehiculo_patente`, `ck_vehiculo_anio_rango` |
| repuesto | UNIQUE parcial `(codigo) WHERE borrado_en IS NULL`; CHECK `precio > 0`; CHECK `stock >= 0` | `uq_repuesto_codigo`, `ck_repuesto_precio_positivo`, `ck_repuesto_stock_no_negativo` |
| estado_orden | PK `codigo`; `posicion` UNIQUE | `pk_estado_orden`, `uq_estado_orden_posicion` |
| orden_trabajo | CHECK `total >= 0` | `ck_orden_trabajo_total_no_negativo` |
| item_orden | CHECK `cantidad > 0`; CHECK `precio_unitario > 0`; UNIQUE `(orden_id, repuesto_id)` | `ck_item_orden_cantidad_positiva`, `ck_item_orden_precio_unitario_positivo`, `uq_item_orden_orden_id_repuesto_id` |
| movimiento_stock | CHECK `cantidad <> 0` | `ck_movimiento_stock_cantidad_no_nula` |
| historial_precio_repuesto | CHECK `precio_nuevo > 0`; CHECK `precio_nuevo <> precio_anterior` | `ck_historial_precio_repuesto_precio_nuevo_positivo`, `ck_historial_precio_repuesto_precio_distinto` |

- Los índices únicos parciales llevan prefijo `uq_` (no `ix_`) a propósito: para el servicio son «unicidad violada» (sqlstate 23505, `constraint_name` = nombre del índice) y se traducen igual que un UNIQUE.
- Unicidad simple con `Field(unique=True)` (→ `UniqueConstraint` con nombre por convención); **nunca** `unique=True` + `index=True` juntos (eso crea un índice único en vez de una restricción y cambia el nombre).
- Las condiciones parciales se escriben con `text("revocada_en IS NULL")` / `text("borrado_en IS NULL")` en `postgresql_where` (texto constante del código, sin datos del usuario).
- **Índices de FK** (18 FKs): cada FK con `index=True` (`ix_<tabla>_<columna>`), **salvo** las dos que ya son la primera columna de un índice único no parcial: `cliente.usuario_id` (su UNIQUE) e `item_orden.orden_id` (prefijo de `uq_item_orden_orden_id_repuesto_id`) — un índice extra sería redundante (regla del skill: evitar índices cubiertos por el prefijo de un compuesto). `asignacion_rol.usuario_id` **sí** lleva índice propio: el único parcial no cubre las filas revocadas, y un `DELETE`/`UPDATE` de usuario las recorrería. Decisión a confirmar por la letra de la consigna («cada clave foránea lleva un índice»): **Q4**.
- Ningún índice no único supera 3 columnas.

### D5 — Columnas: tipos, nulos y defaults
- **PK**: `id: int | None = Field(default=None, primary_key=True)` → `INTEGER` con secuencia (SERIAL), coherente con `IdRuta` de C-02 (tope de `INTEGER`). `estado_orden.codigo: str` PK de texto (la consigna: «se lea igual en psql que en la API»).
- **Texto**: `str` → `VARCHAR` sin largo (`AutoString`; en PostgreSQL equivale a `text`). Los límites de largo/formato van en los DTOs; poner largos en la base obligaría a migrar cada ajuste de validación.
- **Fechas**: `datetime` → `UTCDateTime` (timestamptz, microsegundos; RN07/DD-05 comparan `iat` con `password_cambiada_en` sin truncar). Defaults de alta (`asignacion_rol.desde`, `intento_acceso.cuando`, `evento_seguridad.cuando`, `orden_trabajo.creada_en`, `cuando` de historiales/movimientos): `default_factory=ahora_utc` (el valor está en memoria tras `flush`, sin `refresh` ni lectura perezosa) **y** `server_default=now()` (inserciones por SQL/psql/seed). Ninguna columna usa `onupdate`/`server_onupdate` (C-02 D2).
- **Dinero**: `Decimal` con `max_digits=10, decimal_places=2` (`precio`, `precio_unitario`, `precio_anterior`, `precio_nuevo`) y `12, 2` (`total`). `orden_trabajo.total` NOT NULL sin default (lo calcula siempre el servicio, RN10).
- **Booleanos**: `usuario.activo` default `true`, `usuario.debe_cambiar_password` default `false` (Python + servidor); `intento_acceso.exito`, `estado_orden.es_final` sin default.
- **Enteros**: `repuesto.stock` default `0`; `vehiculo.anio`, `item_orden.cantidad`, `movimiento_stock.cantidad` (con signo, SU-04), `estado_orden.posicion` sin default.
- **Nulos** (sólo los que la consigna marca): `usuario.password_cambiada_en`, `asignacion_rol.vence_en`/`revocada_en`/`otorgada_por`, `cliente.usuario_id`, `vehiculo.borrado_en`, `repuesto.borrado_en`, `orden_trabajo.mecanico_id`, `movimiento_stock.orden_id`, `historial_estado_orden.desde_estado`. Todo lo demás NOT NULL. `cliente.telefono` NOT NULL (supuesto SU-02; ver Q8 no bloqueante).
- **Columnas de código** (`asignacion_rol.rol`, `orden_trabajo.estado`, `historial_estado_orden.desde_estado`/`hasta_estado`) se anotan como `str`, **no** con el enum: por el hallazgo de Context, anotar con el enum crearía un `ENUM` nativo de PostgreSQL. El enum se usa en servicios y DTOs; la base guarda el texto.
- `intento_acceso.ip`: `str` (no `INET`): la consigna no lo pide y evita convertir tipos en C-07.
- `usuario.email`: UNIQUE simple, sensible a mayúsculas; la normalización a minúsculas la hace el DTO de C-07 (ver Q9 no bloqueante).

### D6 — Relaciones: ambos extremos, sin carga perezosa
Todas con `sa_relationship_kwargs={"lazy": "raise", ...}`: leer una relación no precargada lanza `InvalidRequestError` **sin emitir SQL**; la precarga (`selectinload`/`joinedload`) la declara el método del repositorio y anula el `raise` para esa consulta (spec «Sin carga perezosa»).

| Lado «uno» | atributo | Lado «muchos»/«uno» | atributo | Notas |
|---|---|---|---|---|
| `Usuario` | `asignaciones: list[AsignacionRol]` | `AsignacionRol` | `usuario: Usuario` | `foreign_keys` explícito (hay dos FKs a `usuario`) |
| `Usuario` | `cliente: Cliente \| None` | `Cliente` | `usuario: Usuario \| None` | `uselist=False` (uno a uno opcional) |
| `Usuario` | `ordenes_asignadas: list[OrdenTrabajo]` | `OrdenTrabajo` | `mecanico: Usuario \| None` | por `mecanico_id` |
| `Cliente` | `vehiculos: list[Vehiculo]` | `Vehiculo` | `cliente: Cliente` | |
| `Vehiculo` | `ordenes: list[OrdenTrabajo]` | `OrdenTrabajo` | `vehiculo: Vehiculo` | |
| `EstadoOrden` | `ordenes: list[OrdenTrabajo]` | `OrdenTrabajo` | `estado_catalogo: EstadoOrden` | `estado` es la columna; el atributo de relación no puede llamarse igual |
| `OrdenTrabajo` | `items: list[ItemOrden]` | `ItemOrden` | `orden: OrdenTrabajo` | composición: `cascade_delete=True`, `passive_deletes=True`, `order_by=ItemOrden.id` |
| `Repuesto` | `items: list[ItemOrden]` | `ItemOrden` | `repuesto: Repuesto` | |
| `OrdenTrabajo` | `historial: list[HistorialEstadoOrden]` | `HistorialEstadoOrden` | `orden: OrdenTrabajo` | `order_by=HistorialEstadoOrden.id` (cronológico) |
| `Repuesto` | `movimientos: list[MovimientoStock]` | `MovimientoStock` | `repuesto: Repuesto` | |
| `Repuesto` | `historial_precios: list[HistorialPrecioRepuesto]` | `HistorialPrecioRepuesto` | `repuesto: Repuesto` | |

- **FK sin relación ORM** (se leen como id; ninguna respuesta navega por ellas): `asignacion_rol.otorgada_por`, `historial_estado_orden.usuario_id`/`desde_estado`/`hasta_estado`, `movimiento_stock.orden_id`/`usuario_id`, `historial_precio_repuesto.usuario_id`. Declararlas agregaría seis colecciones a `Usuario` sin lector y más ambigüedades de `foreign_keys`. Si un endpoint posterior las lee, se agregan con su contraparte (sin migración: no cambia el esquema). **Q5**.
- **Composición** en dos niveles: en la base `item_orden.orden_id` FK `ON DELETE CASCADE`; en el ORM `cascade="all, delete-orphan"` + `passive_deletes=True` (al borrar una orden no se cargan los ítems —que con `lazy="raise"` fallaría— y la base los borra). Quitar un ítem de `orden.items` precargado lo elimina (delete-orphan). Las demás FKs quedan con la acción por defecto (`NO ACTION`): borrar algo referenciado falla, lo que protege historiales y movimientos. **Q6**.
- *Alternativa*: `lazy="raise_on_sql"` — permite resolver un muchos-a-uno desde el mapa de identidad sin SQL, pero entonces el mismo código funciona o falla según qué haya cargado antes la sesión; `raise` es determinista. **Q7** (no bloqueante si se acepta `raise`).

### D7 — Migración 1: autogenerada, revisada y comentada
1. Base descartable vacía (`taller_verif_c03`, Q2) → `alembic revision --autogenerate -m "esquema inicial"`.
2. **Lectura manual** del archivo contra el mapa de D4/D5: 13 `create_table`; tipos (`UTCDateTime`/timestamptz, `Numeric(10,2)`/`(12,2)`, `AutoString`); `server_default` de fechas y booleanos; 18 FKs con su `ondelete` (sólo `item_orden.orden_id` CASCADE); los 3 `create_index(..., unique=True, postgresql_where=sa.text(...))`; CHECKs con `op.f('ck_...')`; índices de FK; ningún `INSERT` en `estado_orden`; `downgrade()` con los `drop_index`/`drop_table` en orden inverso; ningún tipo `ENUM` nativo.
3. Se agrega en el docstring el comentario «Leída antes de aplicar: …» con la lista de lo verificado y quién/cuándo. Es el **único** cambio manual permitido sobre lo autogenerado (si hiciera falta otro, se corrige el modelo y se regenera, para que `alembic check` siga sin diferencias).
4. `alembic upgrade head` → `alembic check` (sin operaciones) → `alembic downgrade base` → `alembic upgrade head`.
- Reglas del skill para tablas vivas (`CREATE INDEX CONCURRENTLY`, FKs `NOT VALID` + `VALIDATE`, cambios de columna en varios pasos) **no aplican**: la migración 1 crea tablas nuevas sobre una base vacía, en una sola transacción DDL de PostgreSQL; no hay filas que bloquear ni validar. `CONCURRENTLY` además no puede correr dentro de la transacción de Alembic.
- C-04 encadena su migración manual (trigger) con `down_revision` = esta revisión.

### D8 — Enums de dominio
- `Rol(StrEnum)`: `ADMIN`, `RECEPCION`, `MECANICO`, `CLIENTE`, en `usuarios/models.py`. El texto del CHECK se **genera** desde el enum (`"rol IN ('ADMIN', 'RECEPCION', 'MECANICO', 'CLIENTE')"` construido de `Rol`) → coherentes por construcción; son constantes del código, no datos del usuario. Cambiar el enum cambia el CHECK y `alembic check` **no** lo detecta (autogenerate no compara CHECKs) → regla documentada en el docstring: tocar `Rol` exige migración manual.
- Enum de estados `StrEnum`: `PENDIENTE`, `EN_REPARACION`, `TERMINADA`, `CANCELADA`, en `ordenes/models.py`. El catálogo es dato (filas), así que la coherencia no la impone la base: C-06 debe cargar el catálogo **iterando este enum** (descripción/posición/`es_final` en el seed). La FK rechaza cualquier código fuera del catálogo.
- **Conflicto de nombres**: CHANGES.md llama `EstadoOrden` tanto al enum («Enum `EstadoOrden` en código») como a la clase del catálogo (C-13: «`EstadoOrden`… `EstadoOrdenRepository` de sólo lectura, PK `codigo`»). En Python no pueden convivir. Propuesta: tabla `EstadoOrden` (coincide con el diagrama de clases y con C-13) y enum `CodigoEstado`. **Q1** (bloqueante: el nombre lo heredan C-06, C-12, C-13, C-14).
- *Alternativa*: dejar los enums en `schemas.py` de cada módulo — descartada: el servicio y el seed también los usan y `Rol` alimenta el CHECK del modelo.

### D9 — Verificación sin pytest
- Script descartable `verificar_c03.py` en el **scratchpad** (no se versiona; `test/` sólo admite `.http` y `solo_agregado.sql`), ejecutado con `.venv\Scripts\python -I`, con `POSTGRES_DB=taller_verif_c03` como variable del proceso (no se edita `.env`).
- Grupos que verifica (uno por requirement de las specs): catálogo del esquema por `information_schema`/`pg_catalog` (13 tablas, columnas, tipos timestamptz/numeric, sin columna `rol` en `usuario`, sin tipos `ENUM`, nombres de restricciones e índices, cada FK primera columna de un índice no parcial); comportamiento con inserciones dentro de transacciones revertidas (unicidad común y parcial, CHECKs con límites, FK al catálogo vacío y cargado en la transacción, composición por SQL, borrado bloqueado por FK, `Decimal` exacto, microsegundos); ORM con `configure_mappers()` y un contador de sentencias (`before_cursor_execute`) para probar que una relación no precargada falla **sin SQL** y que la precargada no emite consultas extra; `Usuario.cliente` objeto/`None`; `CodigoEstado`/`Rol` vs CHECK.
- Igual que C-02: cada grupo del script se escribe **antes** del código que verifica (debe fallar: no hay modelos o la tabla no existe) y se corre hasta pasar; la salida va al resumen del apply. Strict TDD global no aplica tal cual (sin runner, decisión del TP).
- «Mismo nombre en otra base»: se aplica `upgrade head` en una segunda base descartable (`taller_verif_c03b`) y se comparan las listas de nombres.

## Risks / Trade-offs

- [Autogenerate no compara CHECKs ni la condición de índices parciales de forma fiable] → la lectura manual (D7.2) es la garantía para eso; el script verifica cada CHECK y cada `WHERE` contra la base real.
- [`alembic check` podría reportar diferencias espurias (p. ej. `UTCDateTime` vs `TIMESTAMP WITH TIME ZONE`, o índices parciales)] → si pasa, se analiza la causa; se corrige el modelo o, si es un falso positivo conocido de Alembic, se documenta en el resumen con la salida exacta. Nunca se edita la migración para «tapar» la diferencia.
- [`lazy="raise"` hace fallar código que hoy «andaría» (p. ej. `orden.items.append(...)` sobre una orden cargada sin ítems)] → buscado a propósito (Ej.8: ninguna lectura perezosa); los repos de C-10…C-15 precargan lo que el servicio va a tocar. Documentado en el docstring de cada `models.py`.
- [Una clase de otro módulo no importada al configurar los mappers → error en la primera consulta] → registro único (D3) importado por `main.py`, `env.py` y `seed.py`; el script llama `configure_mappers()` importando sólo el registro.
- [Cambiar la convención de nombres después de aplicar la migración desincroniza nombres] → la convención se fija en C-03 y no se toca; un cambio exigiría migración de renombre.
- [Dos personas creando migraciones → dos cabezas] → sólo el integrante A crea migraciones (REPARTO); C-04 encadena a esta revisión.
- [`ON DELETE CASCADE` de ítems + trigger de sólo agregado de C-04] → no interactúan: el trigger protege historiales/movimientos, no `item_orden`; borrar una orden con historial sigue fallando por la FK de `historial_estado_orden` (correcto: las órdenes no se borran).
- [Nota para C-06] → «vaciar y cargar» necesita `TRUNCATE … RESTART IDENTITY CASCADE` para que las órdenes del seed sean #1 y #2 (SERIAL) y para no chocar con las FKs `NO ACTION`; el trigger de C-04 es por fila (UPDATE/DELETE) y no se dispara con `TRUNCATE`.
- [Email sensible a mayúsculas en la base] → mitigado en el DTO (C-07); un índice único sobre `lower(email)` cambiaría el nombre/forma exigidos (Q9).

## Migration Plan

1. Checkpoints del grupo 0 de tasks resueltos (Q1–Q4 bloqueantes).
2. Modelos + registro + `env.py`/`main.py` (sin migración todavía); `configure_mappers()` limpio.
3. Base descartable vacía → autogenerate → lectura y comentario → `upgrade head` → `alembic check` → verificación del script → `downgrade base` → `upgrade head`.
4. Aplicar a la base de desarrollo (`upgrade head`) **sólo** con permiso explícito (Q2).
- **Rollback**: `alembic downgrade base` elimina las 13 tablas (no hay datos de dominio todavía: el seed es C-06); revertir los archivos nuevos y las líneas de `env.py`/`main.py`. Las bases descartables se borran con `dropdb` al terminar.

## Open Questions

Las que cambian lo que se construye están como **checkpoints bloqueantes** en el grupo 0 de tasks (decisiones CRITICO que revisa el humano antes de escribir código):
- **Q1** — Nombres: tabla catálogo `EstadoOrden` + enum `CodigoEstado` (D8) — conflicto de nombres en CHANGES.md.
- **Q2** — Bases descartables `taller_verif_c03` / `taller_verif_c03b` (crear/borrar) y si al final se aplica `upgrade head` a la base de desarrollo.
- **Q3** — Archivos nuevos y nombres: `app/core/modelo_base.py` (convención + `ahora_utc`), `app/modules/modelos.py` (registro) y la línea en `main.py` (D2/D3).
- **Q4** — Índices de FK cubiertos por un UNIQUE (`cliente.usuario_id`, `item_orden.orden_id`): sin índice redundante (propuesta) vs. índice propio para cumplir la letra «cada FK lleva un índice» (D4).
- **Q5** — Relaciones declaradas (D6): sólo las 11 que se leen, FKs de auditoría sin relación ORM.
- **Q6** — `ON DELETE CASCADE` sólo en `item_orden.orden_id`; resto `NO ACTION` (D6).

Diferibles sin cambiar specs, enfoque ni tasks (se anotan en el resumen del apply si se deciden):
- **Q7** — `lazy="raise"` vs `"raise_on_sql"` (se implementa `raise`).
- **Q8** — `cliente.telefono` NOT NULL (supuesto SU-02, «releer el PDF»); pasarlo a nulo es una migración trivial posterior.
- **Q9** — Unicidad de email sin distinguir mayúsculas: hoy en el DTO; en la base exigiría índice sobre `lower(email)` y otro nombre.
