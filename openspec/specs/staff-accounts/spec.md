# staff-accounts Specification

## Purpose
Define el alta de personal por un administrador: qué datos se aceptan, que la cuenta nace con una contraseña provisoria que obliga a cambiarla antes de usar las rutas protegidas, y que el alta queda registrada junto con su evento de seguridad o no queda nada.

## Requirements

### Requirement: Alta de personal sólo para ADMIN
`POST /usuarios` SHALL pertenecer al grupo protegido y exigir el rol `ADMIN` vigente en la base. Sin sesión MUST responder 401, con cambio de contraseña pendiente 403 por cambio pendiente y sin `ADMIN` vigente 403 por permiso, sin crear ninguna fila.

#### Scenario: Sin sesión
- **WHEN** se llama a `POST /usuarios` sin cookie y con un cuerpo válido
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}` y no se crea ningún usuario

#### Scenario: Usuario sin rol ADMIN
- **WHEN** un usuario con sólo `CLIENTE` vigente llama a `POST /usuarios` con un cuerpo válido
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}` y no se crea ningún usuario

#### Scenario: ADMIN con cambio de contraseña pendiente
- **WHEN** un usuario con `ADMIN` vigente y `debe_cambiar_password` verdadero llama a `POST /usuarios`
- **THEN** la respuesta es 403 `{"detail": "Debe cambiar la contraseña antes de continuar"}` y no se crea ningún usuario

### Requirement: Contrato del alta de personal
El cuerpo SHALL aceptar sólo `email`, `nombre` y `password_provisoria`. El correo MUST seguir las reglas del registro (formato, 254 caracteres, recorte y minúsculas); `nombre`, 1 a 100 caracteres tras recortar; `password_provisoria`, 8 caracteres a 72 bytes UTF-8. Si no se cumple, MUST responder 422 sin reflejar la contraseña y sin escribir nada.

#### Scenario: Campo reservado en el cuerpo
- **WHEN** el cuerpo incluye además `rol: "ADMIN"` o `debe_cambiar_password: false`
- **THEN** la respuesta es 422 que nombra el campo sobrante y no se crea ninguna fila

#### Scenario: Contraseña provisoria corta
- **WHEN** `password_provisoria` tiene 7 caracteres
- **THEN** la respuesta es 422 sobre `password_provisoria`, sin el valor enviado

#### Scenario: Contraseña provisoria de más de 72 bytes
- **WHEN** `password_provisoria` tiene 37 caracteres `ñ` (74 bytes)
- **THEN** la respuesta es 422 sobre `password_provisoria`, no 500

#### Scenario: Correo inválido
- **WHEN** el correo no tiene formato de dirección
- **THEN** la respuesta es 422 sobre `email`

#### Scenario: Correo y nombre normalizados
- **WHEN** se da de alta `" Nuevo@Personal.example.com "` con nombre `"  Nora Nueva "`
- **THEN** el usuario se guarda con correo `nuevo@personal.example.com` y nombre `Nora Nueva`

### Requirement: Cuenta nueva con contraseña provisoria
Un alta aceptada SHALL responder 201 con `{id, email, nombre, activo, debe_cambiar_password}` y crear el usuario activo, con `debe_cambiar_password` verdadero, el hash bcrypt de la contraseña provisoria y sin ninguna asignación de rol ni ficha de cliente. La respuesta MUST NOT incluir la contraseña, `password_hash` ni un token, ni emitir cookie.

#### Scenario: Alta exitosa
- **WHEN** un ADMIN da de alta un correo nuevo con datos válidos
- **THEN** la respuesta es 201 con el id, el correo normalizado, el nombre, `activo: true` y `debe_cambiar_password: true`, sin `Set-Cookie`

#### Scenario: Sin roles ni ficha
- **WHEN** se consulta la base después del alta
- **THEN** el usuario no tiene filas en `asignacion_rol` ni en `cliente`

#### Scenario: Primer login del personal
- **WHEN** la persona dada de alta inicia sesión con la contraseña provisoria
- **THEN** el login responde 200 con `debe_cambiar_password: true` y toda ruta protegida responde 403 por cambio pendiente hasta que cambie la contraseña

### Requirement: Correo ya registrado
Un alta con un correo que ya pertenece a cualquier usuario (personal o cliente auto-registrado) SHALL responder 409 `{"detail": "El correo ya está registrado"}` sin texto de la base y MUST NOT dejar ninguna fila nueva, tampoco su evento. La unicidad la garantiza la base.

#### Scenario: Correo repetido con otras mayúsculas
- **WHEN** existe `nuevo@personal.example.com` y se da de alta `NUEVO@personal.example.com`
- **THEN** la respuesta es 409 con el mensaje de correo repetido y no se agrega ninguna línea en `evento_seguridad`

#### Scenario: Correo de un cliente auto-registrado
- **WHEN** se da de alta como personal el correo de un cliente que se registró solo
- **THEN** la respuesta es 409 con el mensaje de correo repetido y la cuenta del cliente no cambia

#### Scenario: Altas simultáneas
- **WHEN** dos altas con el mismo correo llegan a la vez
- **THEN** una responde 201 y la otra 409, nunca 500

### Requirement: Alta atómica con su evento
El alta SHALL guardar el usuario y una línea en `evento_seguridad` en una sola transacción; si cualquiera de las dos escrituras falla, MUST NOT quedar ninguna. El hash de la contraseña provisoria MUST calcularse antes de abrir esa transacción.

#### Scenario: Evento del alta
- **WHEN** un alta responde 201
- **THEN** hay una línea nueva en `evento_seguridad` con el correo del ADMIN como actor y una acción que nombra el alta de personal y el correo dado de alta

#### Scenario: Falla al registrar el evento
- **WHEN** la escritura del evento falla dentro del alta
- **THEN** el usuario tampoco queda guardado

### Requirement: Sin listado de usuarios
La API MUST NOT ofrecer un listado de usuarios: `GET /usuarios` no existe (IN-02). Las únicas operaciones bajo `/usuarios` son el alta y las de roles de un usuario.

#### Scenario: Pedir el listado
- **WHEN** se llama a `GET /usuarios` con o sin sesión
- **THEN** la respuesta es 405 sin cuerpo de usuarios, y ningún esquema de `/openapi.json` describe un listado de usuarios
