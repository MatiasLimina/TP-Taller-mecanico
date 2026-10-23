# Spec Delta — schema-migrations

## Purpose

Establece que el esquema de la base se crea y evoluciona únicamente mediante migraciones versionadas de Alembic, configuradas desde el mismo entorno que la aplicación y sin credenciales en el repositorio.

## ADDED Requirements

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
`alembic upgrade head` SHALL ejecutarse sin error sobre una base vacía y dejarla en la última revisión disponible (en este change, ninguna revisión de dominio todavía).

#### Scenario: Upgrade sin revisiones
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía
- **THEN** el comando termina con código 0
