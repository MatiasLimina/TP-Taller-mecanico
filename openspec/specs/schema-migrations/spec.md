# schema-migrations Specification

## Purpose

Establece que el esquema de la base se crea y evoluciona únicamente mediante migraciones versionadas de Alembic, configuradas desde el mismo entorno que la aplicación y sin credenciales en el repositorio.

## Requirements

### Requirement: Esquema gestionado sólo por migraciones
El esquema de la base SHALL crearse y modificarse exclusivamente mediante migraciones de Alembic; la aplicación MUST NOT crear tablas por sí misma al arrancar.

#### Scenario: Arranque sobre base vacía
- **WHEN** la aplicación arranca contra una base vacía
- **THEN** la base sigue sin tablas de dominio después del arranque

### Requirement: Migraciones configuradas desde el entorno
Las migraciones SHALL tomar la conexión de la misma configuración que la aplicación (`POSTGRES_*` del entorno o `.env`); el archivo de configuración de Alembic versionado MUST NOT contener usuario, contraseña ni URL de conexión.

#### Scenario: alembic.ini sin credenciales
- **WHEN** se inspecciona `alembic.ini`
- **THEN** no contiene URL de conexión, usuario ni contraseña

#### Scenario: Conexión desde .env
- **WHEN** `.env` tiene credenciales válidas y se ejecuta `alembic current`
- **THEN** el comando se conecta a la base configurada y termina sin error

#### Scenario: Faltan credenciales
- **WHEN** se ejecuta un comando de Alembic sin `POSTGRES_PASSWORD` configurado
- **THEN** el comando falla con un error que nombra la variable faltante

### Requirement: Upgrade sobre base vacía
`alembic upgrade head` SHALL ejecutarse sin error sobre una base vacía y dejarla en la última revisión disponible, con el esquema completo del dominio creado, la protección de sólo agregado instalada sobre `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`, y el catálogo `estado_orden` sin filas (sus filas las carga el seed, no las migraciones).

#### Scenario: Upgrade sin revisiones
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía
- **THEN** el comando termina con código 0

#### Scenario: Esquema del dominio creado
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía y luego `alembic current`
- **THEN** `alembic current` muestra la última revisión como `(head)` y existen las 13 tablas del dominio

#### Scenario: Catálogo vacío tras migrar
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía y se cuenta `estado_orden`
- **THEN** la tabla existe y tiene 0 filas

#### Scenario: Sólo agregado instalado tras migrar
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía y se listan los disparadores de usuario del esquema público
- **THEN** cada una de las tres tablas de sólo agregado tiene su disparador de rechazo de `UPDATE` y `DELETE`, y ninguna otra tabla tiene disparadores

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
`alembic downgrade base` SHALL deshacer todas las revisiones y dejar la base sin tablas del dominio ni funciones o disparadores de sólo agregado; un `alembic upgrade head` posterior MUST volver a crear el esquema completo y la protección de sólo agregado sin error.

#### Scenario: Ida, vuelta e ida
- **WHEN** sobre una base vacía se ejecuta `alembic upgrade head`, luego `alembic downgrade base` y luego `alembic upgrade head`
- **THEN** los tres comandos terminan con código 0, tras el downgrade no queda ninguna de las 13 tablas ni la función de sólo agregado, y tras el segundo upgrade están todas las tablas, la función y los tres disparadores

#### Scenario: Protección activa tras el segundo upgrade
- **WHEN** tras el ciclo completo se intenta un `DELETE` sobre `historial_precio_repuesto` con una fila existente
- **THEN** la base rechaza la sentencia

### Requirement: Migración manual para lo que la comparación no ve
Las funciones y disparadores de la base SHALL crearse en una revisión escrita a mano (no generada por comparación), encadenada a la anterior y con un comentario «leída antes de aplicar» que diga lo revisado. Su `downgrade` MUST eliminar sólo esos objetos, dejando tablas y datos como los dejó la revisión anterior.

#### Scenario: Segunda revisión encadenada
- **WHEN** se ejecuta `alembic history`
- **THEN** hay exactamente dos revisiones y la segunda (la de sólo agregado) tiene como anterior a la migración inicial autogenerada

#### Scenario: Comentario de revisión en la migración manual
- **WHEN** se abre el archivo de la segunda revisión en `migrations/versions/`
- **THEN** contiene un comentario «leída antes de aplicar» con lo revisado y declara que fue escrita a mano

#### Scenario: Bajar sólo la segunda revisión
- **WHEN** desde la última revisión, con filas en las tres tablas de sólo agregado, se ejecuta `alembic downgrade -1`
- **THEN** el comando termina con código 0, ya no existe ningún disparador ni función de sólo agregado, las 13 tablas siguen existiendo con sus filas y un `UPDATE` sobre `movimiento_stock` ya no es rechazado

#### Scenario: Invisible para la comparación automática
- **WHEN** se ejecuta `alembic upgrade head` y luego `alembic check`
- **THEN** `alembic check` no detecta operaciones pendientes: la función y los disparadores no generan diferencias con los modelos
