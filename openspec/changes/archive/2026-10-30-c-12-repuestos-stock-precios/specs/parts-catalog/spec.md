## MODIFIED Requirements

### Requirement: Acceso al catálogo por rol
Las rutas de `/repuestos` SHALL pertenecer al grupo protegido. `GET /repuestos` y `GET /repuestos/{id}` MUST exigir un rol vigente ADMIN, RECEPCION o MECANICO; `POST /repuestos`, `PATCH`, `DELETE`, `POST /repuestos/{id}/reponer`, `GET /repuestos/{id}/movimientos` y `GET /repuestos/{id}/precios` MUST exigir ADMIN vigente. Sin sesión → 401; cambio de contraseña pendiente → 403; sin el rol → 403, antes de validar el cuerpo o buscar el recurso.

#### Scenario: Sin sesión
- **WHEN** se llama a `GET /repuestos` sin cookie
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`

#### Scenario: Cliente sin rol de personal
- **WHEN** un usuario con sólo el rol CLIENTE llama a `GET /repuestos`
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}`

#### Scenario: Lectura para el personal
- **WHEN** un usuario con rol vigente RECEPCION o MECANICO llama a `GET /repuestos` o a `GET /repuestos/{id}` de un repuesto vigente
- **THEN** la respuesta es 200

#### Scenario: Escritura sólo ADMIN
- **WHEN** un usuario con rol RECEPCION o MECANICO (sin ADMIN) llama a `POST /repuestos`, `PATCH /repuestos/{id}`, `DELETE /repuestos/{id}` o `POST /repuestos/{id}/reponer` con un cuerpo válido
- **THEN** la respuesta es 403 y no se escribe ninguna fila

#### Scenario: Historiales sólo ADMIN
- **WHEN** un usuario con rol RECEPCION, MECANICO o sólo CLIENTE llama a `GET /repuestos/{id}/movimientos` o a `GET /repuestos/{id}/precios`
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}`

#### Scenario: Rol antes que existencia
- **WHEN** un usuario con rol RECEPCION llama a `POST /repuestos/999999/reponer` con un cuerpo válido
- **THEN** la respuesta es 403, no 404

#### Scenario: Permiso antes que contrato
- **WHEN** se llama a `POST /repuestos` o a `POST /repuestos/{id}/reponer` sin cookie y con un campo no declarado
- **THEN** la respuesta es 401, no 422
