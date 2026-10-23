# app-configuration Specification

## Purpose

Define cómo la aplicación obtiene su configuración desde el entorno o un archivo `.env` no versionado, qué valores son secretos obligatorios sin default y qué plantilla documenta todas las variables.

## Requirements

### Requirement: Configuración leída del entorno
La aplicación SHALL leer toda su configuración desde variables de entorno o desde un archivo `.env` local; las variables del entorno del proceso SHALL tener prioridad sobre las del `.env`. El archivo `.env` MUST NOT versionarse.

#### Scenario: Valor tomado del archivo .env
- **WHEN** `POSTGRES_DB=taller` está definido sólo en `.env` y la aplicación arranca
- **THEN** la configuración efectiva usa `taller` como nombre de base

#### Scenario: El entorno pisa al .env
- **WHEN** `.env` define `POOL_SIZE=5` y el proceso se lanza con la variable de entorno `POOL_SIZE=8`
- **THEN** la configuración efectiva usa `8`

#### Scenario: .env excluido del control de versiones
- **WHEN** se ejecuta `git check-ignore .env` en la raíz del repositorio
- **THEN** el comando informa que `.env` está ignorado

### Requirement: URL de la base derivada de POSTGRES_*
La dirección de la base SHALL derivarse de `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST` y `POSTGRES_PORT` con un driver asincrónico `postgresql+asyncpg`; no SHALL existir una variable que la reemplace entera. Caracteres especiales de la contraseña MUST quedar escapados.

#### Scenario: URL armada con las partes
- **WHEN** `POSTGRES_USER=taller`, `POSTGRES_PASSWORD=x`, `POSTGRES_DB=taller`, `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5432`
- **THEN** la URL efectiva es `postgresql+asyncpg://taller:x@localhost:5432/taller`

#### Scenario: Contraseña con caracteres reservados
- **WHEN** `POSTGRES_PASSWORD` contiene `@`, `/` o `%`
- **THEN** la aplicación se conecta igual con esa contraseña (la URL la lleva escapada)

### Requirement: Secretos obligatorios sin valor por defecto
`POSTGRES_PASSWORD` y `SECRET_KEY` MUST NOT tener valor por defecto en el código. Si cualquiera de los dos falta o está vacío, la aplicación SHALL negarse a arrancar con un error que nombre la variable faltante, sin generar una clave al vuelo.

#### Scenario: Falta SECRET_KEY
- **WHEN** se lanza `uvicorn main:app` sin `SECRET_KEY` en entorno ni `.env`
- **THEN** el arranque falla y el error menciona `secret_key` (pydantic imprime el nombre del campo en minúscula; equivale a la variable `SECRET_KEY`); el servidor no queda escuchando

#### Scenario: Falta POSTGRES_PASSWORD
- **WHEN** se lanza la aplicación sin `POSTGRES_PASSWORD`
- **THEN** el arranque falla y el error menciona `postgres_password` (nombre del campo en minúscula; equivale a `POSTGRES_PASSWORD`)

#### Scenario: Secreto vacío
- **WHEN** `SECRET_KEY=` está definido pero vacío
- **THEN** el arranque falla igual que si faltara

### Requirement: Secretos no expuestos
Los valores de `POSTGRES_PASSWORD` y `SECRET_KEY`, y la URL completa de la base, MUST NOT aparecer en la representación textual de la configuración ni en los mensajes de log de arranque.

#### Scenario: Imprimir la configuración
- **WHEN** se imprime o se registra el objeto de configuración
- **THEN** los secretos aparecen enmascarados y la URL con contraseña no se muestra

### Requirement: Parámetros operativos con defaults documentados
La configuración SHALL exponer, con estos valores por defecto y sobreescribibles por entorno: `ACCESS_TOKEN_EXPIRE_SECONDS=1800`, `BCRYPT_COST=12`, `BCRYPT_MAX_CONCURRENCY=4`, `POOL_SIZE=5`, `MAX_OVERFLOW=10`, `COOKIE_SECURE=false`, `SQL_ECHO=false`, `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5432`. Valores fuera de rango SHALL impedir el arranque.

#### Scenario: Defaults aplicados
- **WHEN** sólo se definen las variables obligatorias
- **THEN** la configuración efectiva usa 1800 s de token, costo bcrypt 12, semáforo 4, pool 5/10, cookie no segura y eco SQL apagado

#### Scenario: Valor inválido
- **WHEN** `BCRYPT_COST=3` o `POOL_SIZE=0` o `POSTGRES_PORT=abc`
- **THEN** el arranque falla con un error de validación que nombra el campo (en minúscula, p. ej. `bcrypt_cost`)

### Requirement: Plantilla env.example completa y sin secretos
El repositorio SHALL incluir `env.example` con todas las variables que lee la configuración, cada una comentada; las variables sensibles MUST quedar vacías y el archivo SHALL indicar cómo generar `SECRET_KEY`.

#### Scenario: Copiar la plantilla
- **WHEN** un integrante copia `env.example` a `.env` y completa sólo `POSTGRES_PASSWORD` y `SECRET_KEY`
- **THEN** la aplicación arranca con el resto de los valores de la plantilla

#### Scenario: Plantilla sin secretos
- **WHEN** se revisa `env.example`
- **THEN** `POSTGRES_PASSWORD` y `SECRET_KEY` no tienen valor asignado
