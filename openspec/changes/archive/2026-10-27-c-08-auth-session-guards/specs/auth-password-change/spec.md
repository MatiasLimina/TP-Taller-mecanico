# Spec Delta — auth-password-change

## Purpose

Define el cambio de contraseña del propio usuario: su contrato, la verificación de la contraseña actual, la escritura atómica con su evento de seguridad y la invalidación de las sesiones anteriores con entrega de una cookie nueva válida (RN06, RN07).

## ADDED Requirements

### Requirement: Contrato del cambio de contraseña
`POST /auth/cambiar-password` SHALL aceptar sólo `password_actual` y `password_nueva`. `password_actual` MUST tener entre 1 carácter y 72 bytes UTF-8; `password_nueva`, al menos 8 caracteres y como máximo 72 bytes UTF-8, y distinta de `password_actual`. Si no se cumple, la respuesta MUST ser 422 sin reflejar las contraseñas y sin escribir nada.

#### Scenario: Nueva de más de 72 bytes
- **WHEN** `password_nueva` tiene 37 caracteres `ñ` (74 bytes)
- **THEN** la respuesta es 422 sobre `password_nueva`, no 500

#### Scenario: Actual de más de 72 bytes
- **WHEN** `password_actual` tiene 73 bytes
- **THEN** la respuesta es 422 sobre `password_actual`, no 401 ni 500

#### Scenario: Nueva demasiado corta
- **WHEN** `password_nueva` tiene 7 caracteres
- **THEN** la respuesta es 422 sobre `password_nueva`

#### Scenario: Nueva igual a la actual
- **WHEN** `password_nueva` es idéntica a `password_actual`
- **THEN** la respuesta es 422 y la contraseña no cambia

#### Scenario: Campo extra
- **WHEN** el cuerpo incluye además `debe_cambiar_password: false`
- **THEN** la respuesta es 422 que nombra el campo sobrante

#### Scenario: Sin sesión
- **WHEN** se llama sin cookie, con un cuerpo válido o con un JSON bien formado que no cumple el contrato
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`

### Requirement: Verificación de la contraseña actual
El cambio SHALL verificar `password_actual` contra el hash guardado del usuario de la sesión. Si no coincide, MUST responder 401 `{"detail": "La contraseña actual es incorrecta"}`, sin escribir nada, sin entregar cookie y sin invalidar la sesión en curso.

#### Scenario: Contraseña actual incorrecta
- **WHEN** un usuario con sesión válida envía una `password_actual` equivocada
- **THEN** la respuesta es 401 `{"detail": "La contraseña actual es incorrecta"}` sin `Set-Cookie`, y `GET /auth/yo` con la misma cookie sigue respondiendo 200

#### Scenario: La contraseña sigue siendo la anterior
- **WHEN** falla el cambio por contraseña actual incorrecta
- **THEN** el login con la contraseña anterior sigue funcionando y no hay línea nueva en `evento_seguridad`

### Requirement: Cambio atómico con evento de seguridad
Con la contraseña actual correcta, el sistema SHALL, en una sola transacción, guardar el hash de `password_nueva`, fijar `password_cambiada_en` en el instante del cambio, poner `debe_cambiar_password` en falso y agregar una línea en `evento_seguridad` con el correo del usuario como actor. El hash nuevo MUST calcularse antes de abrir esa transacción. Si algo falla, nada de eso queda.

#### Scenario: Cambio exitoso
- **WHEN** un usuario con sesión válida envía su contraseña actual correcta y una nueva válida
- **THEN** el usuario queda con el hash de la nueva, `password_cambiada_en` con fracción de segundo, `debe_cambiar_password` falso y una línea `evento_seguridad` (actor = su correo, acción "Cambio de contraseña")

#### Scenario: Credenciales después del cambio
- **WHEN** el cambio fue exitoso
- **THEN** el login con la contraseña anterior responde 401 y con la nueva responde 200

#### Scenario: Cambio voluntario
- **WHEN** un usuario sin cambio pendiente cambia su contraseña
- **THEN** el cambio se aplica igual y `debe_cambiar_password` queda falso

### Requirement: Cookie nueva válida y sesiones anteriores invalidadas
El cambio exitoso SHALL responder 200 `{"mensaje": "Contraseña actualizada", "debe_cambiar_password": false, "expira_en_segundos": N}` y entregar una cookie `access_token` nueva, con los mismos atributos que la del login y los roles vigentes del usuario. Esa cookie MUST valer de inmediato; toda sesión emitida antes del cambio, incluida la usada para pedirlo, MUST responder 401 (RN07).

#### Scenario: Cookie nueva válida
- **WHEN** el cambio es exitoso
- **THEN** `GET /auth/yo` con la cookie nueva responde 200 con `debe_cambiar_password: false`

#### Scenario: Cookie anterior rechazada sin esperar
- **WHEN** un usuario inicia sesión, cambia la contraseña enseguida (sin esperar entre ambas peticiones) y repite `GET /auth/yo` con la cookie del login
- **THEN** la respuesta es 401 `{"detail": "La sesión no es válida o venció"}`

#### Scenario: Otra sesión abierta del mismo usuario
- **WHEN** el usuario tenía además otra sesión iniciada antes del cambio
- **THEN** esa sesión también responde 401

#### Scenario: Cuerpo sin token
- **WHEN** el cambio es exitoso
- **THEN** el cuerpo trae sólo los tres campos declarados, sin token
