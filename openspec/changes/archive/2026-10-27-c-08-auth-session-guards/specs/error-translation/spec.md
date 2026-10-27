# Spec Delta — error-translation

## MODIFIED Requirements

### Requirement: Forma única de las respuestas de error
Toda respuesta de error SHALL ser JSON con una clave `detail`: un mensaje propio en español para 401, 403, 404, 409, 429, 500 y 422 de negocio, o la lista de errores por campo para 422 de validación del contrato.

#### Scenario: Error de negocio
- **WHEN** una operación responde 401, 403, 404, 409, 429 o 422 por una regla de negocio
- **THEN** el cuerpo es `{"detail": "<mensaje propio>"}`

#### Scenario: Error de validación
- **WHEN** el cuerpo o los parámetros no cumplen el contrato
- **THEN** el cuerpo es `{"detail": [...]}` con, por cada error, su ubicación, mensaje y tipo

### Requirement: Errores de aplicación con su código
Las operaciones SHALL poder señalar "no autenticado", "sin permiso", "no encontrado", "conflicto con lo guardado", "entrada inválida para la regla" y "demasiados intentos" con un mensaje propio, y la API MUST responderlos como 401, 403, 404, 409, 422 y 429 respectivamente. "Demasiados intentos" MUST llevar el encabezado `Retry-After` con los segundos de espera que indique la operación.

#### Scenario: Recurso inexistente
- **WHEN** una operación señala que el recurso de la ruta no existe
- **THEN** la respuesta es 404 con el mensaje de la operación

#### Scenario: Conflicto de estado
- **WHEN** una operación señala un conflicto con lo guardado
- **THEN** la respuesta es 409 con el mensaje de la operación

#### Scenario: No autenticado
- **WHEN** una operación señala que las credenciales o la sesión no son válidas
- **THEN** la respuesta es 401 con el mensaje de la operación

#### Scenario: Sin permiso
- **WHEN** una operación señala que el usuario autenticado no puede realizarla
- **THEN** la respuesta es 403 con el mensaje de la operación y sin encabezados extra

#### Scenario: Demasiados intentos
- **WHEN** una operación señala que se superó un límite de intentos con una espera de N segundos
- **THEN** la respuesta es 429 con el mensaje de la operación y el encabezado `Retry-After: N`
