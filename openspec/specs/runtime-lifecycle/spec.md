# runtime-lifecycle Specification

## Purpose

Define cuándo se crean y se liberan los recursos de base de datos del proceso (al arrancar y al apagar, nunca al importar) y cómo cada petición obtiene y libera su propia sesión.

## Requirements

### Requirement: Recursos de base creados al arrancar, no al importar
El motor asincrónico y la fábrica de sesiones SHALL crearse durante el arranque de la aplicación y quedar asociados a la instancia de la aplicación; importar cualquier módulo del proyecto MUST NOT abrir conexiones ni construir el motor.

#### Scenario: Importar sin base disponible
- **WHEN** se importa el módulo principal de la aplicación con PostgreSQL apagado
- **THEN** la importación termina sin error y sin intentar conectarse

#### Scenario: Arranque crea los recursos
- **WHEN** la aplicación arranca con configuración válida
- **THEN** el motor y la fábrica de sesiones quedan disponibles para las peticiones

### Requirement: Pool dimensionado por configuración
El pool de conexiones SHALL usar `POOL_SIZE` y `MAX_OVERFLOW` de la configuración, y el eco de consultas SHALL seguir `SQL_ECHO`.

#### Scenario: Eco de SQL activado
- **WHEN** la aplicación corre con `SQL_ECHO=true` y se llama a `GET /health/ready`
- **THEN** la consola muestra la consulta `SELECT 1`

### Requirement: Una sesión por petición, cerrada al terminar
Cada petición que necesite la base SHALL recibir una sesión propia tomada de la fábrica del arranque; la sesión MUST cerrarse al terminar la petición, incluso si la petición falla, y los objetos MUST NOT expirar al confirmar.

#### Scenario: Peticiones sucesivas no comparten sesión
- **WHEN** se hacen dos peticiones a `GET /health/ready`
- **THEN** cada una usa una sesión distinta y ambas devuelven la conexión al pool al terminar

#### Scenario: Petición que falla
- **WHEN** una petición que usa sesión termina con error
- **THEN** la sesión se cierra igual y la conexión vuelve al pool

### Requirement: Liberación del motor al apagar
Al apagarse, la aplicación SHALL liberar el motor y cerrar todas las conexiones del pool.

#### Scenario: Apagado ordenado
- **WHEN** se detiene `uvicorn` con Ctrl+C
- **THEN** el proceso termina sin advertencias de conexiones abiertas
