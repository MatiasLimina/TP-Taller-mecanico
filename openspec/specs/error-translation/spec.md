# error-translation Specification

## Purpose

Define la forma y los códigos de las respuestas de error de la API y garantiza que ninguna entrada inválida termine en 500 ni que una respuesta exponga texto interno de la base o una traza (RN18).

## Requirements

### Requirement: Forma única de las respuestas de error
Toda respuesta de error SHALL ser JSON con una clave `detail`: un mensaje propio en español para 401, 404, 409, 429, 500 y 422 de negocio, o la lista de errores por campo para 422 de validación del contrato.

#### Scenario: Error de negocio
- **WHEN** una operación responde 401, 404, 409, 429 o 422 por una regla de negocio
- **THEN** el cuerpo es `{"detail": "<mensaje propio>"}`

#### Scenario: Error de validación
- **WHEN** el cuerpo o los parámetros no cumplen el contrato
- **THEN** el cuerpo es `{"detail": [...]}` con, por cada error, su ubicación, mensaje y tipo

### Requirement: Errores de aplicación con su código
Las operaciones SHALL poder señalar "no autenticado", "no encontrado", "conflicto con lo guardado", "entrada inválida para la regla" y "demasiados intentos" con un mensaje propio, y la API MUST responderlos como 401, 404, 409, 422 y 429 respectivamente. "Demasiados intentos" MUST llevar el encabezado `Retry-After` con los segundos de espera que indique la operación.

#### Scenario: Recurso inexistente
- **WHEN** una operación señala que el recurso de la ruta no existe
- **THEN** la respuesta es 404 con el mensaje de la operación

#### Scenario: Conflicto de estado
- **WHEN** una operación señala un conflicto con lo guardado
- **THEN** la respuesta es 409 con el mensaje de la operación

#### Scenario: No autenticado
- **WHEN** una operación señala que las credenciales o la sesión no son válidas
- **THEN** la respuesta es 401 con el mensaje de la operación

#### Scenario: Demasiados intentos
- **WHEN** una operación señala que se superó un límite de intentos con una espera de N segundos
- **THEN** la respuesta es 429 con el mensaje de la operación y el encabezado `Retry-After: N`

### Requirement: Violaciones de integridad traducidas
Una violación de integridad de la base que llegue a la respuesta SHALL traducirse a un mensaje propio: unicidad o clave foránea → 409; CHECK o NOT NULL → 422. La operación MUST poder asociar una restricción concreta a un mensaje específico; sin asociación se usa un mensaje genérico propio.

#### Scenario: Unicidad sin mensaje específico
- **WHEN** una escritura viola una restricción de unicidad que la operación no tradujo
- **THEN** la respuesta es 409 con un mensaje genérico propio y sin el nombre de la restricción ni texto de PostgreSQL

#### Scenario: Unicidad con mensaje específico
- **WHEN** una escritura viola una restricción a la que la operación asoció el mensaje «El correo ya está registrado»
- **THEN** la respuesta es 409 con ese mensaje

#### Scenario: CHECK violado
- **WHEN** una escritura viola un CHECK
- **THEN** la respuesta es 422 con un mensaje propio

### Requirement: Valores que la base no acepta
Un valor que la base rechaza por tipo o rango (por ejemplo, un entero fuera del rango de la columna) SHALL responder 422 con un mensaje propio, nunca 500.

#### Scenario: Entero fuera de rango
- **WHEN** un valor numérico supera el rango de su columna al consultarse o escribirse
- **THEN** la respuesta es 422 con un mensaje propio

### Requirement: Validación sin eco del valor enviado
Las respuestas 422 de validación SHALL omitir el valor recibido y el contexto interno del validador, para no reflejar contraseñas ni datos enviados.

#### Scenario: Contraseña inválida
- **WHEN** un cuerpo falla la validación en un campo de contraseña
- **THEN** el 422 nombra el campo y el motivo pero no contiene el valor enviado

### Requirement: Sin texto interno ni traza
Ninguna respuesta de error SHALL contener texto de PostgreSQL o del driver, nombres de tablas o restricciones, SQL, ni trazas; un error inesperado MUST responder 500 con un mensaje genérico propio y registrarse sólo en el log del servidor.

#### Scenario: Error inesperado
- **WHEN** una operación falla por un error no previsto
- **THEN** la respuesta es 500 `{"detail": "Error interno del servidor"}` y el detalle queda sólo en el log

#### Scenario: Inspección del cuerpo
- **WHEN** se provoca cada tipo de error de base (unicidad, clave foránea, CHECK, dato fuera de rango)
- **THEN** ningún cuerpo contiene `duplicate key`, `violates`, `asyncpg`, `sqlalchemy`, el nombre de la restricción ni `Traceback`

### Requirement: Ninguna entrada inválida termina en 500
Toda entrada que no cumple el contrato o que la base rechaza por integridad o por dato SHALL responder 4xx; un 500 MUST quedar reservado a defectos del servidor.

#### Scenario: JSON mal formado
- **WHEN** se envía un cuerpo que no es JSON válido
- **THEN** la respuesta es 422
