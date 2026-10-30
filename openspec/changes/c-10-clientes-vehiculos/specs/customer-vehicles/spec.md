# Spec Delta — customer-vehicles

## Purpose

Define los vehículos de una ficha de cliente: su alta por el personal con una patente única entre los vigentes, su baja lógica bloqueada mientras tengan órdenes abiertas según el catálogo de estados, y la consulta que cada usuario autenticado hace de sus propios vehículos.

## ADDED Requirements

### Requirement: Alta y baja de vehículos sólo para recepción y administración
`POST /clientes/{id}/vehiculos` y `DELETE /vehiculos/{id}` SHALL pertenecer al grupo protegido y exigir el rol `RECEPCION` o `ADMIN` vigente en la base. Sin sesión MUST responder 401, con cambio de contraseña pendiente 403 por cambio pendiente y sin esos roles 403 por permiso, antes de comprobar si el recurso existe y sin escribir nada.

#### Scenario: Cliente intenta registrar un vehículo
- **WHEN** un usuario con sólo `CLIENTE` vigente llama a `POST /clientes/{id}/vehiculos` con un cuerpo válido
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}` y no se crea ningún vehículo

#### Scenario: Cliente intenta dar de baja un id inexistente
- **WHEN** un usuario con sólo `CLIENTE` vigente llama a `DELETE /vehiculos/999999`
- **THEN** la respuesta es 403 por permiso, no 404

#### Scenario: Baja sin sesión
- **WHEN** se llama a `DELETE /vehiculos/{id}` sin cookie
- **THEN** la respuesta es 401 y el vehículo no cambia

### Requirement: Contrato del alta de un vehículo
El cuerpo SHALL aceptar sólo `patente`, `marca`, `modelo` y `anio`. `anio` MUST ser un entero entre 1950 y 2100 inclusive; `marca` y `modelo`, de 1 a 50 caracteres tras recortar. Si no se cumple, MUST responder 422 por campo, sin escribir nada; el cuerpo MUST NOT poder fijar el cliente, el id ni la fecha de baja.

#### Scenario: Año anterior a 1950
- **WHEN** `anio` es 1949
- **THEN** la respuesta es 422 sobre `anio` y no se crea ningún vehículo

#### Scenario: Año posterior a 2100
- **WHEN** `anio` es 2101
- **THEN** la respuesta es 422 sobre `anio`

#### Scenario: Años en el borde
- **WHEN** se da de alta un vehículo con `anio` 1950 y otro con `anio` 2100
- **THEN** ambos responden 201

#### Scenario: Campo reservado
- **WHEN** el cuerpo incluye además `borrado_en` o `cliente_id`
- **THEN** la respuesta es 422 que nombra el campo sobrante

#### Scenario: Contrato antes que existencia
- **WHEN** se llama a `POST /clientes/999999/vehiculos` con `anio` 1900
- **THEN** la respuesta es 422, no 404

### Requirement: Patente normalizada
La patente SHALL guardarse y compararse sin espacios ni guiones y en mayúsculas; después de normalizarla MUST tener entre 6 y 8 caracteres, todos letras `A`–`Z` o dígitos, o el alta responde 422 sobre `patente`.

#### Scenario: Patente con minúsculas y espacios
- **WHEN** se da de alta la patente `" zc001aa "`
- **THEN** el vehículo se guarda y se responde con la patente `ZC001AA`

#### Scenario: Misma patente escrita de otra forma
- **WHEN** ya existe el vehículo vigente `ZC001AA` y se da de alta `"zc-001 aa"`
- **THEN** se trata como la misma patente y la respuesta es 409

#### Scenario: Patente demasiado corta
- **WHEN** la patente es `"AB"`
- **THEN** la respuesta es 422 sobre `patente`

### Requirement: Alta de un vehículo en una ficha
Un alta aceptada SHALL responder 201 con `{id, cliente_id, patente, marca, modelo, anio}` y crear el vehículo vigente en la ficha de la ruta. Si la ficha no existe MUST responder 404 `{"detail": "El cliente no existe"}` sin crear nada.

#### Scenario: Alta exitosa
- **WHEN** la recepción da de alta `{"patente": "ZC002AA", "marca": "Fiat", "modelo": "Cronos", "anio": 1950}` en una ficha existente
- **THEN** la respuesta es 201 con el id nuevo, el `cliente_id` de la ruta y los datos enviados, sin fecha de baja

#### Scenario: Ficha inexistente
- **WHEN** se da de alta un vehículo válido en `POST /clientes/999999/vehiculos`
- **THEN** la respuesta es 404 `{"detail": "El cliente no existe"}` y no se crea ningún vehículo

### Requirement: Patente única entre vigentes
Un alta con la patente de otro vehículo sin baja —de cualquier ficha— SHALL responder 409 `{"detail": "Ya hay un vehículo vigente con la patente <PATENTE>"}`, con la patente normalizada, sin texto de la base y sin crear nada. La unicidad MUST decidirla la base, también con altas simultáneas; la patente de un vehículo dado de baja MUST NOT impedir el alta.

#### Scenario: Patente vigente en otra ficha
- **WHEN** se da de alta en otra ficha un vehículo con la patente de uno vigente
- **THEN** la respuesta es 409 con el mensaje que nombra la patente y sigue habiendo un solo vehículo vigente con ella

#### Scenario: Altas simultáneas de la misma patente
- **WHEN** dos altas con la misma patente llegan a la vez
- **THEN** una responde 201 y la otra 409, nunca 500

#### Scenario: Patente de un vehículo vendido (PDF C-19)
- **WHEN** un vehículo sin órdenes se da de baja (204) y después se registra la misma patente para otro cliente
- **THEN** el alta responde 201, quedan dos filas con esa patente (una con fecha de baja) y un tercer alta con la misma patente responde 409

### Requirement: Baja lógica de un vehículo
`DELETE /vehiculos/{id}` sobre un vehículo vigente sin órdenes abiertas SHALL responder 204 sin cuerpo y registrar la fecha y hora de baja con zona horaria, conservando la fila, sus datos y sus órdenes. Desde entonces el vehículo MUST NOT aparecer en el detalle de su ficha ni en `/mis-vehiculos`.

#### Scenario: Baja exitosa
- **WHEN** la recepción da de baja un vehículo vigente sin órdenes
- **THEN** la respuesta es 204 sin cuerpo y la fila sigue en la tabla con `borrado_en` en UTC

#### Scenario: Deja de aparecer
- **WHEN** se consulta la ficha y `/mis-vehiculos` del dueño después de la baja
- **THEN** el vehículo no aparece en ninguna de las dos respuestas

### Requirement: Vehículo inexistente o ya dado de baja
`DELETE /vehiculos/{id}` con un id que no corresponde a un vehículo vigente —inexistente o ya dado de baja— SHALL responder 404 `{"detail": "El vehículo no existe"}` sin cambiar ninguna fila; un id no entero o fuera de 1..2147483647 MUST responder 422.

#### Scenario: Segunda baja
- **WHEN** se da de baja otra vez un vehículo ya dado de baja
- **THEN** la respuesta es 404 y su `borrado_en` no cambia

#### Scenario: Id inexistente
- **WHEN** se llama a `DELETE /vehiculos/999999`
- **THEN** la respuesta es 404

#### Scenario: Id no numérico
- **WHEN** se llama a `DELETE /vehiculos/abc`
- **THEN** la respuesta es 422

### Requirement: Baja bloqueada por órdenes abiertas
Si el vehículo tiene al menos una orden cuyo estado el catálogo `estado_orden` no marca como final (`es_final` falso), la baja SHALL responder 409 `{"detail": "El vehículo tiene órdenes abiertas y no se puede dar de baja"}` sin cambiar el vehículo (RN16). Las órdenes en estados finales MUST NOT impedir la baja. La decisión MUST salir del catálogo, no de una lista de estados en el código.

#### Scenario: Orden pendiente
- **WHEN** el vehículo tiene una orden `PENDIENTE`
- **THEN** la respuesta es 409 con ese mensaje y `borrado_en` sigue nulo

#### Scenario: Orden en reparación
- **WHEN** la única orden del vehículo está `EN_REPARACION`
- **THEN** la respuesta es 409

#### Scenario: Sólo órdenes terminadas
- **WHEN** la única orden del vehículo está `TERMINADA`
- **THEN** la respuesta es 204 y la orden sigue existiendo

#### Scenario: Sólo órdenes canceladas
- **WHEN** la única orden del vehículo está `CANCELADA`
- **THEN** la respuesta es 204

#### Scenario: Orden abierta confirmada durante la baja
- **WHEN** otra transacción que tiene bloqueada la fila del vehículo crea una orden `PENDIENTE` y confirma mientras la baja espera
- **THEN** la baja responde 409 y el vehículo queda vigente

### Requirement: Vehículos propios del usuario autenticado
`GET /mis-vehiculos` SHALL pertenecer al grupo protegido sin exigir rol: con sesión válida y sin cambio pendiente MUST responder 200 con un arreglo de `{id, cliente_id, patente, marca, modelo, anio}` de los vehículos vigentes de la ficha vinculada al usuario de la sesión, en orden de id, y nunca vehículos de otra ficha (RN17).

#### Scenario: Cliente con vehículos
- **WHEN** un cliente con dos vehículos vigentes llama a `GET /mis-vehiculos`
- **THEN** la respuesta es 200 con esos dos vehículos y ninguno de otro cliente

#### Scenario: Otro cliente
- **WHEN** otro cliente con un vehículo llama a `GET /mis-vehiculos`
- **THEN** la respuesta trae sólo su vehículo

#### Scenario: Usuario sin ficha de cliente
- **WHEN** un usuario autenticado sin ficha vinculada (p. ej. personal dado de alta por un ADMIN) llama a `GET /mis-vehiculos`
- **THEN** la respuesta es 200 con `[]`

#### Scenario: Ficha sin vehículos
- **WHEN** un usuario cuya ficha no tiene vehículos vigentes llama a `GET /mis-vehiculos`
- **THEN** la respuesta es 200 con `[]`

#### Scenario: Sin sesión
- **WHEN** se llama a `GET /mis-vehiculos` sin cookie
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`

#### Scenario: Cambio de contraseña pendiente
- **WHEN** un usuario con `debe_cambiar_password` verdadero llama a `GET /mis-vehiculos`
- **THEN** la respuesta es 403 `{"detail": "Debe cambiar la contraseña antes de continuar"}`
