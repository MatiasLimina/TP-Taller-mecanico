# Spec Delta — schema-migrations

## MODIFIED Requirements

### Requirement: Upgrade sobre base vacía
`alembic upgrade head` SHALL ejecutarse sin error sobre una base vacía y dejarla en la última revisión disponible, con el esquema completo del dominio creado y el catálogo `estado_orden` sin filas (sus filas las carga el seed, no las migraciones).

#### Scenario: Upgrade sin revisiones
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía
- **THEN** el comando termina con código 0

#### Scenario: Esquema del dominio creado
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía y luego `alembic current`
- **THEN** `alembic current` muestra la última revisión como `(head)` y existen las 13 tablas del dominio

#### Scenario: Catálogo vacío tras migrar
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía y se cuenta `estado_orden`
- **THEN** la tabla existe y tiene 0 filas

## ADDED Requirements

### Requirement: Migración inicial autogenerada y revisada
La primera revisión SHALL generarse por comparación automática contra los modelos (`--autogenerate`), crear todas las tablas del dominio con sus índices (incluidos los únicos parciales), CHECKs y claves foráneas, y llevar un comentario que diga que se leyó antes de aplicarla. Una migración MUST NOT aplicarse sin esa revisión.

#### Scenario: Comentario de revisión
- **WHEN** se abre el archivo de la primera revisión en `migrations/versions/`
- **THEN** contiene un comentario «leída antes de aplicar» con lo revisado

#### Scenario: Índices parciales en la migración
- **WHEN** se inspecciona el archivo de la primera revisión
- **THEN** crea los tres índices únicos parciales con su condición (`revocada_en IS NULL`, `borrado_en IS NULL` dos veces)

### Requirement: Modelos y migraciones sincronizados
Tras aplicar todas las revisiones, la comparación automática entre los modelos y la base SHALL no detectar diferencias; un cambio de modelo sin su migración MUST quedar en evidencia por esa comparación.

#### Scenario: Sin diferencias pendientes
- **WHEN** se ejecuta `alembic upgrade head` y luego `alembic check`
- **THEN** `alembic check` informa que no hay operaciones de actualización detectadas y termina con código 0

### Requirement: Ciclo de upgrade y downgrade
`alembic downgrade base` SHALL deshacer todas las revisiones y dejar la base sin tablas del dominio; un `alembic upgrade head` posterior MUST volver a crear el esquema completo sin error.

#### Scenario: Ida, vuelta e ida
- **WHEN** sobre una base vacía se ejecuta `alembic upgrade head`, luego `alembic downgrade base` y luego `alembic upgrade head`
- **THEN** los tres comandos terminan con código 0, tras el downgrade no queda ninguna de las 13 tablas y tras el segundo upgrade están todas
