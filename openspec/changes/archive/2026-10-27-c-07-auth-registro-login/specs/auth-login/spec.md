# Spec Delta — auth-login

## Purpose

Define el inicio y el cierre de sesión: cómo se verifican las credenciales sin revelar qué cuentas existen, cómo se limita la fuerza bruta por correo e IP, cómo se registra cada intento y cómo se entrega y se borra la cookie de sesión (RN08, RN09).

## ADDED Requirements

### Requirement: Login exitoso con cookie de sesión
`POST /auth/login` SHALL estar disponible sin sesión y, con correo y contraseña correctos de un usuario activo, MUST responder 200 con `{mensaje, debe_cambiar_password, expira_en_segundos}` y entregar el token sólo en la cookie `access_token`. El token MUST llevar los roles vigentes del usuario al emitirse.

#### Scenario: Credenciales correctas
- **WHEN** un usuario activo envía su correo y su contraseña
- **THEN** la respuesta es 200 `{"mensaje": "Sesión iniciada", "debe_cambiar_password": false, "expira_en_segundos": 1800}` (con la vigencia configurada) y `Set-Cookie: access_token=…` con `HttpOnly`, `SameSite=lax`, `Path=/` y `Max-Age` igual a la vigencia

#### Scenario: Cuerpo sin token
- **WHEN** el login es exitoso
- **THEN** el cuerpo no contiene el token ni ningún otro campo además de los tres declarados

#### Scenario: Cambio de contraseña pendiente
- **WHEN** inicia sesión un usuario con `debe_cambiar_password` verdadero
- **THEN** la respuesta es 200 con `debe_cambiar_password: true` y la cookie se entrega igual

#### Scenario: Roles vigentes en el token
- **WHEN** inicia sesión un usuario con un rol abierto, uno revocado y uno vencido
- **THEN** el token sólo lista el rol abierto y sin vencer

### Requirement: Credenciales rechazadas sin revelar la cuenta
Un login con correo inexistente, contraseña incorrecta o usuario inactivo SHALL responder 401 con exactamente el mismo cuerpo y sin cookie, y MUST ejecutar la misma verificación bcrypt en los tres casos (contra el hash del usuario o contra el hash ficticio), de modo que el tiempo de respuesta no distinga si el correo existe (RN09).

#### Scenario: Contraseña incorrecta
- **WHEN** se envía un correo existente con una contraseña equivocada
- **THEN** la respuesta es 401 `{"detail": "Correo o contraseña incorrectos"}` sin `Set-Cookie`

#### Scenario: Correo inexistente
- **WHEN** se envía un correo que no está registrado
- **THEN** la respuesta es 401 con un cuerpo idéntico byte a byte al de la contraseña incorrecta y un tiempo de respuesta del mismo orden

#### Scenario: Usuario inactivo
- **WHEN** un usuario con `activo` falso envía su contraseña correcta
- **THEN** la respuesta es el mismo 401 y no se entrega cookie

### Requirement: Contrato de entrada del login
El cuerpo del login SHALL aceptar sólo `email` y `password`; un campo no declarado, un correo con formato inválido, una contraseña vacía o de más de 72 bytes UTF-8 MUST responder 422 sin reflejar la contraseña, sin verificar credenciales y sin contar como intento. El login MUST NOT exigir el mínimo de 8 caracteres del registro.

#### Scenario: Contraseña de más de 72 bytes
- **WHEN** la contraseña del login tiene 73 bytes
- **THEN** la respuesta es 422 sobre `password`, no 401 ni 500, y no se anota ningún intento

#### Scenario: Contraseña corta en el login
- **WHEN** se envía una contraseña de 3 caracteres
- **THEN** el login verifica credenciales como con cualquier otra (401 si no coincide, 200 si es la del usuario), nunca 422 por largo mínimo

#### Scenario: Campo extra
- **WHEN** el cuerpo incluye además `recordarme: true`
- **THEN** la respuesta es 422 que nombra el campo sobrante

### Requirement: Límite de intentos fallidos por correo e IP
Cuando existan 5 o más intentos fallidos con el mismo correo (normalizado) desde la misma IP en los últimos 60 segundos y posteriores al último intento exitoso de ese par, el login SHALL responder 429 con un mensaje propio y el encabezado `Retry-After` en segundos enteros, sin verificar la contraseña ni calcular ningún hash (RN08).

#### Scenario: Sexto intento fallido
- **WHEN** se envían seis logins seguidos con la contraseña incorrecta para el mismo correo desde la misma IP
- **THEN** los cinco primeros responden 401 y el sexto 429 con `Retry-After` y en pocos milisegundos (sin trabajo bcrypt)

#### Scenario: Bloqueo aunque la contraseña sea correcta
- **WHEN** con el límite alcanzado se envía la contraseña correcta
- **THEN** la respuesta sigue siendo 429 y no se entrega cookie

#### Scenario: Valor de Retry-After
- **WHEN** se responde 429
- **THEN** `Retry-After` es un entero entre 1 y 60 igual a los segundos que faltan, redondeados hacia arriba, para que el quinto fallo más reciente salga de la ventana

#### Scenario: Fin del bloqueo
- **WHEN** pasan los segundos indicados por `Retry-After` sin nuevos fallos
- **THEN** el siguiente login vuelve a verificar credenciales

#### Scenario: Otro par correo–IP
- **WHEN** el correo `a` está bloqueado desde una IP
- **THEN** el mismo correo desde otra IP, u otro correo desde la misma IP, se sigue verificando con normalidad

#### Scenario: Un éxito reinicia la cuenta
- **WHEN** hubo cuatro fallos, luego un login correcto y luego otros cuatro fallos dentro de los 60 s
- **THEN** el siguiente login todavía verifica credenciales (sólo cuentan los fallos posteriores al último éxito) y los fallos anteriores siguen en la tabla

### Requirement: Registro de cada intento verificado
Todo login que llegó a verificar credenciales SHALL anotar en `intento_acceso` una fila con fecha con zona, correo normalizado, IP y resultado, escrita con una transacción propia que se confirma aunque la petición termine en error. Un login rechazado por el límite (429) o por el contrato (422) MUST NOT anotarse.

#### Scenario: Cinco fallos registrados
- **WHEN** se ejecuta el caso de seis intentos fallidos
- **THEN** `intento_acceso` tiene exactamente cinco filas nuevas con `exito` falso para ese correo e IP, y ninguna por el 429

#### Scenario: Éxito registrado
- **WHEN** un login es exitoso
- **THEN** queda una fila con `exito` verdadero para ese correo e IP

#### Scenario: Correo inexistente también se anota
- **WHEN** falla un login con un correo que no existe
- **THEN** queda una fila con ese correo y `exito` falso, y cuenta para el límite igual que un fallo de una cuenta real

### Requirement: Cierre de sesión
`POST /auth/logout` SHALL estar disponible con o sin sesión, MUST responder 200 con un mensaje propio y borrar la cookie `access_token` (`Max-Age=0`, mismo `Path`), y MUST NOT escribir en la base.

#### Scenario: Logout con sesión
- **WHEN** se llama a logout con la cookie de sesión
- **THEN** la respuesta es 200 `{"mensaje": "Sesión cerrada"}` y un `Set-Cookie` de `access_token` con `Max-Age=0` y `Path=/`

#### Scenario: Logout sin sesión
- **WHEN** se llama a logout sin cookie
- **THEN** la respuesta es la misma 200 (operación idempotente)
