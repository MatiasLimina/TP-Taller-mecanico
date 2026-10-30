# price-history Specification

## Purpose

Garantiza que cada cambio del precio de un repuesto quede registrado en `historial_precio_repuesto` con el precio anterior, el nuevo y quién lo cambió, en la misma transacción que el cambio (RN20).

## Requirements

### Requirement: Cambio de precio con línea de historial
Un `PATCH /repuestos/{id}` que cambia el precio SHALL agregar exactamente una línea en `historial_precio_repuesto` con `precio_anterior`, `precio_nuevo`, el ADMIN como `usuario_id` y `cuando` con zona, en la misma transacción que la actualización: o quedan el precio nuevo y la línea, o ninguno.

#### Scenario: Cambio de precio (PDF C-18)
- **WHEN** un ADMIN cambia el precio de un repuesto de 8500.00 a 9000
- **THEN** la respuesta es 200 con `precio` `"9000.00"` y existe una línea nueva con `precio_anterior` 8500.00, `precio_nuevo` 9000.00 y `usuario_id` del ADMIN

#### Scenario: Atomicidad
- **WHEN** el registro de la línea de historial falla
- **THEN** el precio del repuesto queda como estaba

### Requirement: Sin línea si el precio no cambia
Un PATCH que no envía `precio`, o que envía un precio numéricamente igual al vigente (p. ej. `9000` y `"9000.00"`), SHALL responder 200 sin agregar líneas de historial.

#### Scenario: Sólo descripción (PDF C-18)
- **WHEN** después de cambiar el precio un ADMIN envía un PATCH sólo con `descripcion`
- **THEN** la respuesta es 200 y la cantidad de líneas de historial de ese repuesto no cambia

#### Scenario: Mismo precio
- **WHEN** el repuesto vale 9000.00 y el PATCH envía `"precio": "9000.00"`
- **THEN** la respuesta es 200 y no se agrega ninguna línea

### Requirement: Sólo ADMIN cambia precios
Un usuario sin ADMIN vigente SHALL recibir 403 al intentar un PATCH de precio, y MUST NOT quedar cambio de precio ni línea de historial.

#### Scenario: Recepción intenta cambiar el precio (PDF C-18)
- **WHEN** un usuario con rol RECEPCION envía `PATCH /repuestos/{id}` con un precio nuevo
- **THEN** la respuesta es 403 y el precio y el historial quedan como estaban

### Requirement: Cambios de precio simultáneos encadenados
Dos cambios de precio simultáneos del mismo repuesto SHALL serializarse: el `precio_anterior` de la segunda línea MUST ser el `precio_nuevo` de la primera.

#### Scenario: Dos PATCH de precio a la vez
- **WHEN** un repuesto vale 100.00 y llegan a la vez un PATCH a 200 y otro a 300
- **THEN** quedan dos líneas encadenadas (100.00 → X y X → Y, con {X, Y} = {200.00, 300.00}) y el precio final es Y

### Requirement: Consulta del historial de precios
`GET /repuestos/{id}/precios` SHALL responder 200 con la lista completa de las líneas de historial de precios del repuesto vigente, sin paginar, en orden de registro (la más antigua primero). Cada línea MUST tener exactamente `id`, `precio_anterior` y `precio_nuevo` (texto decimal con dos decimales, p. ej. `"8500.00"`), `usuario_id` y `cuando`. Inexistente o dado de baja → 404.

#### Scenario: Cambio de precio y después sólo descripción (PDF C-18)
- **WHEN** un ADMIN cambia el precio de un repuesto de 8500.00 a 9000, después envía un PATCH sólo con `descripcion` y luego consulta `GET /repuestos/{id}/precios`
- **THEN** la respuesta es 200 con exactamente una línea: `precio_anterior` `"8500.00"`, `precio_nuevo` `"9000.00"` y `usuario_id` del ADMIN

#### Scenario: Recepción no cambia el historial (PDF C-18)
- **WHEN** un usuario con rol RECEPCION intenta un PATCH de precio (403) y un ADMIN consulta después el historial
- **THEN** la lista tiene las mismas líneas que antes del intento

#### Scenario: Líneas encadenadas en orden
- **WHEN** el precio pasó de 8500.00 a 9000.00 y después a 9500.50
- **THEN** la lista tiene dos líneas, en ese orden: 8500.00 → 9000.00 y 9000.00 → 9500.50

#### Scenario: Repuesto sin cambios de precio
- **WHEN** se consulta el historial de un repuesto cuyo precio nunca cambió (aunque se haya repuesto)
- **THEN** la respuesta es 200 `[]`

#### Scenario: Repuesto no vigente
- **WHEN** se consulta el historial de un repuesto inexistente o dado de baja
- **THEN** la respuesta es 404 `{"detail": "El repuesto no existe"}`

#### Scenario: Número fijo de consultas
- **WHEN** se consulta el historial de un repuesto con 1 línea y de otro con 3
- **THEN** ambas peticiones emiten la misma cantidad de consultas a la base
