# Spec Delta — auth-registration

## Purpose

Define el auto-registro de clientes: quién puede registrarse, qué datos se aceptan y la garantía de que la cuenta, su rol CLIENTE, su ficha de cliente y el evento de seguridad quedan todos juntos o ninguno (RN01, RN02).

## ADDED Requirements

### Requirement: Registro público de clientes
`POST /auth/registro` SHALL estar disponible sin sesión y, con datos válidos y no repetidos, MUST responder 201 con el id, correo y nombre del usuario creado y los datos de su ficha de cliente. La respuesta MUST NOT incluir `password_hash`, la contraseña ni un token, y MUST NOT emitir la cookie de sesión.

#### Scenario: Registro exitoso
- **WHEN** un visitante envía correo, contraseña, nombre, documento y teléfono válidos que no existen en el sistema
- **THEN** la respuesta es 201 con el id, el correo, el nombre y la ficha de cliente (id, documento, teléfono), sin `password_hash` ni contraseña

#### Scenario: Sin sesión iniciada
- **WHEN** se registra un usuario
- **THEN** la respuesta no contiene `Set-Cookie: access_token` y el cuerpo no contiene un token

#### Scenario: La cuenta nueva puede iniciar sesión
- **WHEN** después del registro se hace login con el mismo correo y contraseña
- **THEN** el login responde 200

### Requirement: Contrato de entrada del registro
El cuerpo del registro SHALL aceptar sólo `email`, `password`, `nombre`, `documento` y `telefono`, y MUST rechazar con 422 —sin escribir nada y sin reflejar la contraseña— un campo no declarado, un correo con formato inválido o de más de 254 caracteres, una contraseña de menos de 8 caracteres o de más de 72 bytes UTF-8, o un `nombre`, `documento` o `telefono` vacío tras recortar espacios o de más de 100, 20 o 30 caracteres respectivamente. `nombre`, `documento` y `telefono` SHALL guardarse sin espacios al inicio ni al final, sin otra validación de formato. Ningún dato del cuerpo puede fijar rol, estado de cuenta ni fechas.

#### Scenario: Campo reservado en el cuerpo
- **WHEN** el cuerpo incluye además `rol: "ADMIN"` o `activo: false`
- **THEN** la respuesta es 422 que nombra el campo sobrante y no se crea ninguna fila

#### Scenario: Contraseña de más de 72 bytes
- **WHEN** la contraseña tiene 40 caracteres `ñ` (80 bytes)
- **THEN** la respuesta es 422 sobre el campo `password`, sin el valor enviado y sin un 500

#### Scenario: Contraseña de exactamente 72 bytes
- **WHEN** la contraseña tiene 72 bytes UTF-8
- **THEN** el contrato la acepta

#### Scenario: Correo inválido
- **WHEN** el correo no tiene formato de dirección de correo
- **THEN** la respuesta es 422 sobre el campo `email`

#### Scenario: Contraseña de menos de 8 caracteres
- **WHEN** la contraseña del registro tiene 7 caracteres
- **THEN** la respuesta es 422 sobre el campo `password` y no se crea ninguna fila

#### Scenario: Texto vacío
- **WHEN** `nombre`, `documento` o `telefono` es vacío
- **THEN** la respuesta es 422 sobre ese campo

#### Scenario: Texto sólo con espacios
- **WHEN** `nombre`, `documento` o `telefono` contiene sólo espacios (por ejemplo `"   "`)
- **THEN** la respuesta es 422 sobre ese campo y no se crea ninguna fila

#### Scenario: Texto demasiado largo
- **WHEN** `documento` tiene 21 caracteres
- **THEN** la respuesta es 422 sobre el campo `documento`, no un 500

#### Scenario: Espacios alrededor recortados
- **WHEN** se registra con `documento` `" 30123456 "` y `nombre` `"  Ana Pérez "`
- **THEN** la respuesta es 201 y la ficha guarda `documento` `"30123456"` y `nombre` `"Ana Pérez"`, sin espacios al inicio ni al final

### Requirement: Correo normalizado
El correo SHALL compararse y guardarse sin espacios al inicio o al final y en minúsculas, de modo que dos correos que sólo difieren en mayúsculas sean el mismo para la unicidad y para el login.

#### Scenario: Mismo correo con otras mayúsculas
- **WHEN** existe `ana@example.com` y se registra `Ana@Example.com`
- **THEN** la respuesta es 409 por correo repetido

#### Scenario: Login con mayúsculas
- **WHEN** un usuario registrado como `ana@example.com` inicia sesión con ` ANA@example.com `
- **THEN** el login lo reconoce como el mismo usuario

### Requirement: Alta atómica de cuenta, rol, ficha y evento
Un registro aceptado SHALL crear en una única transacción el usuario activo y sin cambio de contraseña pendiente, una asignación abierta del rol CLIENTE sin vencimiento, su ficha de cliente vinculada y una línea en `evento_seguridad`; si cualquiera de esas escrituras falla, MUST NOT quedar ninguna.

#### Scenario: Filas creadas
- **WHEN** un registro responde 201
- **THEN** existen el usuario (`activo` verdadero, `debe_cambiar_password` falso), una asignación CLIENTE con `revocada_en` y `vence_en` nulos, una ficha de cliente con `usuario_id` igual al del usuario y con su nombre, documento y teléfono, y una línea nueva de `evento_seguridad`

#### Scenario: Contraseña nunca en claro
- **WHEN** se consulta la fila del usuario registrado
- **THEN** `password_hash` es un hash bcrypt con el costo configurado y no contiene la contraseña

### Requirement: Correo repetido
Un registro con un correo ya registrado SHALL responder 409 con un mensaje propio que indique que el correo ya está registrado, sin texto de la base, y MUST NOT dejar ninguna fila nueva (ni ficha, ni rol, ni evento). La unicidad la garantiza la base, sin consulta previa.

#### Scenario: Correo existente con documento nuevo
- **WHEN** se registra un correo existente con un documento que no existe
- **THEN** la respuesta es 409 con el mensaje de correo repetido y un registro posterior de ese mismo documento con otro correo responde 201 (la ficha rechazada no quedó guardada)

### Requirement: Documento de un cliente existente
Un registro cuyo documento ya pertenece a una ficha de cliente —tenga o no usuario— SHALL responder 409 con un mensaje propio, MUST NOT vincular ni modificar esa ficha y MUST NOT dejar el usuario, el rol ni el evento del registro rechazado (RN02).

#### Scenario: Documento de un cliente del taller sin usuario
- **WHEN** se registra un correo nuevo con el documento de un cliente cargado por el taller que no tiene usuario
- **THEN** la respuesta es 409 con el mensaje de documento repetido y la ficha existente conserva `usuario_id` nulo y sus datos

#### Scenario: Documento repetido que sólo difiere en espacios
- **WHEN** existe una ficha con documento `30123456` y se registra un correo nuevo con documento `" 30123456 "`
- **THEN** la respuesta es 409 con el mensaje de documento repetido y no se crea ninguna fila

#### Scenario: Sin usuario suelto
- **WHEN** un registro es rechazado por documento repetido
- **THEN** un registro posterior con ese mismo correo y un documento nuevo responde 201 (el usuario rechazado no quedó guardado)

#### Scenario: Registros simultáneos
- **WHEN** dos registros con el mismo correo o el mismo documento llegan a la vez
- **THEN** uno responde 201 y el otro 409, nunca 500
