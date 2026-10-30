## ADDED Requirements

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
