# api-contracts Specification

## Purpose

Reglas comunes a todos los contratos de entrada y salida de la API: qué campos se aceptan, qué datos nunca salen y qué identificadores de ruta son válidos, separados de los modelos de tabla.

## Requirements

### Requirement: Entradas rechazan campos no declarados
Todo cuerpo de entrada SHALL rechazar con 422 cualquier campo que su contrato no declare, sin ejecutar la operación, de modo que nadie pueda fijar campos reservados (rol, stock, precio, estado, fechas) por el cuerpo.

#### Scenario: Campo extra en el cuerpo
- **WHEN** se envía un cuerpo válido con un campo adicional no declarado
- **THEN** la respuesta es 422 que nombra el campo sobrante y no se escribe nada

#### Scenario: Cuerpo válido
- **WHEN** se envía un cuerpo con sólo campos declarados y valores válidos
- **THEN** el contrato lo acepta

### Requirement: Contratos separados de las tablas
Las respuestas SHALL construirse con contratos de salida que enumeran sus campos; un modelo de tabla MUST NOT devolverse directamente como respuesta.

#### Scenario: Esquema publicado
- **WHEN** se consulta `/openapi.json`
- **THEN** ningún esquema de respuesta corresponde a un modelo de tabla

### Requirement: password_hash nunca en una respuesta
Ningún contrato de salida SHALL exponer `password_hash` en ninguna profundidad (campo propio, modelo anidado, o dentro de `Optional`, `list`, `dict`, `tuple`, uniones y `Annotated`), ni incluir un modelo de tabla (`table=True`); un contrato de salida que lo haga MUST fallar al definirse, antes de atender peticiones. La misma regla MUST aplicarse al envoltorio de listados `Pagina[X]`. Una referencia adelantada que no se pueda resolver MUST rechazarse (no se puede verificar).

#### Scenario: Contrato de salida con password_hash
- **WHEN** se define un contrato de salida con un campo `password_hash`
- **THEN** la importación del módulo falla con un error que nombra el campo

#### Scenario: password_hash anidado
- **WHEN** un contrato de salida declara un campo cuyo tipo (a cualquier profundidad, dentro de contenedores o uniones) es un modelo que expone `password_hash`
- **THEN** la definición falla con un error que indica la ruta hasta el campo

#### Scenario: Modelo de tabla en una salida
- **WHEN** un contrato de salida, o `Pagina[X]`, referencia un modelo de tabla (`table=True`) en cualquier posición de la anotación
- **THEN** la definición falla con un error que lo nombra

#### Scenario: Pagina parametrizada con un tipo inseguro
- **WHEN** se escribe `Pagina[X]` y `X` es un modelo de tabla o expone `password_hash` a cualquier profundidad
- **THEN** se lanza `TypeError` al parametrizarla

#### Scenario: Esquema sin password_hash
- **WHEN** se consulta `/openapi.json`
- **THEN** el texto `password_hash` no aparece en ningún esquema de respuesta

### Requirement: Ids de ruta válidos
Todo id en la ruta SHALL ser un entero entre 1 y 2147483647; cualquier otro valor (no entero, cero, negativo o mayor que el máximo de la columna) MUST dar 422 sin ejecutar el handler.

#### Scenario: Id no entero
- **WHEN** se pide un recurso con id `abc`
- **THEN** la respuesta es 422 y el handler no se ejecuta (C-01 de la consigna)

#### Scenario: Id gigante
- **WHEN** se pide un recurso con id `99999999999`
- **THEN** la respuesta es 422, no 500

#### Scenario: Id cero
- **WHEN** se pide un recurso con id `0`
- **THEN** la respuesta es 422
