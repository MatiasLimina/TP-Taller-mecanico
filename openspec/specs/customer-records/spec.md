# customer-records Specification

## Purpose

Define cómo el personal del taller da de alta y consulta las fichas de cliente: quién puede hacerlo, qué datos se aceptan, que el documento identifica a un único cliente y qué muestra el detalle de una ficha con sus vehículos vigentes.
## Requirements
### Requirement: Fichas de cliente sólo para recepción y administración
`POST /clientes` y `GET /clientes/{id}` SHALL pertenecer al grupo protegido y exigir el rol `RECEPCION` o `ADMIN` vigente en la base. Sin sesión MUST responder 401, con cambio de contraseña pendiente 403 por cambio pendiente y sin ninguno de esos roles 403 por permiso, sin leer ni escribir fichas. Un `MECANICO` o un `CLIENTE` MUST recibir 403 aunque pida su propia ficha.

#### Scenario: Sin sesión
- **WHEN** se llama a `POST /clientes` sin cookie con un cuerpo válido
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}` y no se crea ninguna ficha

#### Scenario: Cliente autenticado
- **WHEN** un usuario con sólo `CLIENTE` vigente llama a `POST /clientes` con un cuerpo válido
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}` y no se crea ninguna ficha

#### Scenario: Mecánico
- **WHEN** un usuario con sólo `MECANICO` vigente llama a `POST /clientes`
- **THEN** la respuesta es 403 por permiso

#### Scenario: Cliente pide su propia ficha
- **WHEN** un usuario con sólo `CLIENTE` vigente llama a `GET /clientes/{id}` con el id de su propia ficha
- **THEN** la respuesta es 403 por permiso (lo propio se consulta por `/mis-vehiculos`)

#### Scenario: Cambio de contraseña pendiente
- **WHEN** un usuario con `debe_cambiar_password` verdadero llama a `POST /clientes`
- **THEN** la respuesta es 403 `{"detail": "Debe cambiar la contraseña antes de continuar"}`

#### Scenario: Administración también puede
- **WHEN** un usuario con `ADMIN` vigente y sin `RECEPCION` da de alta una ficha válida
- **THEN** la respuesta es 201

### Requirement: Contrato del alta de una ficha
El cuerpo de `POST /clientes` SHALL aceptar sólo `nombre`, `documento` y `telefono`, con las mismas reglas que el registro: cada uno sin espacios al inicio ni al final y con 1 a 100, 20 y 30 caracteres respectivamente tras recortar, sin otra validación de formato. Si no se cumple, MUST responder 422 sin escribir nada. El cuerpo MUST NOT poder fijar el usuario vinculado.

#### Scenario: Campo no declarado
- **WHEN** el cuerpo incluye además `usuario_id`
- **THEN** la respuesta es 422 que nombra el campo sobrante y no se crea ninguna ficha

#### Scenario: Documento vacío tras recortar
- **WHEN** `documento` es `"   "`
- **THEN** la respuesta es 422 sobre `documento`

#### Scenario: Documento demasiado largo
- **WHEN** `documento` tiene 21 caracteres
- **THEN** la respuesta es 422 sobre `documento`

#### Scenario: Falta un campo
- **WHEN** el cuerpo no trae `telefono`
- **THEN** la respuesta es 422 sobre `telefono`

### Requirement: Alta de una ficha sin usuario
Un alta aceptada SHALL responder 201 con `{id, usuario_id, nombre, documento, telefono}` y crear la ficha con los valores recortados y `usuario_id` nulo. La respuesta MUST NOT incluir vehículos ni datos de ningún usuario.

#### Scenario: Alta con espacios
- **WHEN** la recepción da de alta `{"nombre": " Jorge Sinusuario ", "documento": " 43000010 ", "telefono": " 1155550010 "}`
- **THEN** la respuesta es 201 con `usuario_id: null`, `nombre: "Jorge Sinusuario"`, `documento: "43000010"` y `telefono: "1155550010"`, y la fila guardada tiene esos valores

### Requirement: Documento único
Un alta con un documento que ya pertenece a otra ficha —creada por el personal o por un auto-registro— SHALL responder 409 `{"detail": "El documento ya pertenece a un cliente del taller"}`, sin texto de la base y sin crear ninguna fila. La unicidad MUST decidirla la base, sin consulta previa, también con altas simultáneas.

#### Scenario: Documento de una ficha del personal
- **WHEN** se da de alta una segunda ficha con el documento `43000010`
- **THEN** la respuesta es 409 con ese mensaje y sigue habiendo una sola ficha con ese documento

#### Scenario: Documento de un cliente auto-registrado
- **WHEN** se da de alta una ficha con el documento de un cliente que se registró solo
- **THEN** la respuesta es 409 con el mismo mensaje

#### Scenario: Altas simultáneas del mismo documento
- **WHEN** dos altas con el mismo documento llegan a la vez
- **THEN** una responde 201 y la otra 409, nunca 500, y queda una sola ficha

#### Scenario: Registro con el documento de una ficha sin usuario
- **WHEN** alguien se auto-registra con el documento de una ficha creada por la recepción
- **THEN** el registro responde 409 y la ficha sigue sin usuario vinculado (RN02)

### Requirement: Detalle de una ficha con sus vehículos vigentes
`GET /clientes/{id}` SHALL responder 200 con `{id, usuario_id, nombre, documento, telefono, vehiculos}`, donde `vehiculos` contiene sólo los vehículos de la ficha sin baja, cada uno `{id, cliente_id, patente, marca, modelo, anio}`, en orden de id. Los vehículos MUST leerse junto con la ficha en un número fijo de consultas, sin importar cuántos tenga.

#### Scenario: Ficha sin vehículos
- **WHEN** se pide el detalle de una ficha recién creada
- **THEN** la respuesta es 200 con `vehiculos: []`

#### Scenario: Ficha con vehículos
- **WHEN** la ficha tiene dos vehículos vigentes
- **THEN** la respuesta los trae a los dos, en orden de id, y `usuario_id` es el del usuario vinculado o `null`

#### Scenario: Vehículo dado de baja
- **WHEN** uno de los vehículos de la ficha fue dado de baja
- **THEN** no aparece en `vehiculos`

#### Scenario: Consultas constantes
- **WHEN** se pide el detalle de una ficha con un vehículo y de otra con tres
- **THEN** ambas lecturas de la ficha y sus vehículos emiten la misma cantidad de consultas

### Requirement: Ficha inexistente o id inválido
`GET /clientes/{id}` con un id entero de 1 a 2147483647 que no corresponde a ninguna ficha SHALL responder 404 `{"detail": "El cliente no existe"}`; un id que no es entero o está fuera de ese rango MUST responder 422.

#### Scenario: Ficha inexistente
- **WHEN** se pide `GET /clientes/999999`
- **THEN** la respuesta es 404 `{"detail": "El cliente no existe"}`

#### Scenario: Id no numérico
- **WHEN** se pide `GET /clientes/abc`
- **THEN** la respuesta es 422

#### Scenario: Id cero
- **WHEN** se pide `GET /clientes/0`
- **THEN** la respuesta es 422
