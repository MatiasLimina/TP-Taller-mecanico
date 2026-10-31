## ADDED Requirements

### Requirement: Listado de órdenes sólo para el personal
`GET /ordenes` SHALL pertenecer al grupo protegido y exigir el rol RECEPCION, ADMIN o MECANICO vigente en la base. El personal MUST ver todas las órdenes, también un mecánico las que no tiene asignadas. Sin sesión MUST responder 401, con cambio de contraseña pendiente 403 y sin esos roles 403, antes de validar los parámetros.

#### Scenario: Sin sesión
- **WHEN** se llama a `GET /ordenes?estado=REABIERTA` sin cookie
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`, no 422

#### Scenario: Cliente sin rol de personal
- **WHEN** un usuario con sólo `CLIENTE` llama a `GET /ordenes`, con o sin un `estado` inválido
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}`

#### Scenario: Cambio de contraseña pendiente
- **WHEN** un usuario con `debe_cambiar_password` verdadero llama a `GET /ordenes`
- **THEN** la respuesta es 403 `{"detail": "Debe cambiar la contraseña antes de continuar"}`

#### Scenario: Un mecánico ve todas las órdenes
- **WHEN** un mecánico que no está asignado a ninguna orden llama a `GET /ordenes`
- **THEN** la respuesta es 200 y `total` cuenta todas las órdenes del taller

#### Scenario: Recepción y administración
- **WHEN** la recepción o un ADMIN llaman a `GET /ordenes`
- **THEN** la respuesta es 200 con todas las órdenes

### Requirement: Filtro por estado del listado
`GET /ordenes` SHALL aceptar un parámetro `estado` opcional cuyo valor MUST ser exactamente uno de los códigos del contrato: `PENDIENTE`, `EN_REPARACION`, `TERMINADA` o `CANCELADA`. Con `estado`, la página y `total` cuentan sólo las órdenes en ese estado; sin él, todas. Cualquier otro valor, también en minúsculas o vacío, MUST responder 422 sin consultar las órdenes.

#### Scenario: Filtrar por un estado
- **WHEN** hay dos órdenes `PENDIENTE` y una `EN_REPARACION` y se pide `GET /ordenes?estado=PENDIENTE`
- **THEN** la respuesta es 200 con esas dos órdenes y `total` 2

#### Scenario: Estado sin órdenes
- **WHEN** ninguna orden está `TERMINADA` y se pide `GET /ordenes?estado=TERMINADA`
- **THEN** la respuesta es 200 con `items` vacío, `total` 0 y `pages` 1

#### Scenario: Estado que el contrato no declara (PDF C-17)
- **WHEN** el personal pide `GET /ordenes?estado=REABIERTA`
- **THEN** la respuesta es 422 sobre `["query", "estado"]`

#### Scenario: Código en minúsculas o vacío
- **WHEN** se pide `GET /ordenes?estado=pendiente` o `GET /ordenes?estado=`
- **THEN** la respuesta es 422

#### Scenario: Total con el filtro
- **WHEN** hay dos órdenes `PENDIENTE` y se pide `GET /ordenes?estado=PENDIENTE&size=1&page=2`
- **THEN** la respuesta trae una orden, `total` 2 y `pages` 2

### Requirement: Orden y paginación de los listados de órdenes
`GET /ordenes` y `GET /mis-ordenes` SHALL paginar con el envoltorio común (`items`, `total`, `page`, `size`, `pages`) y sus reglas de `page`/`size`, y MUST listar de la orden más nueva a la más vieja (id descendente), un orden estable entre páginas.

#### Scenario: Más nueva primero
- **WHEN** existen las órdenes 1, 2 y 3 y la recepción pide `GET /ordenes`
- **THEN** `items` trae las órdenes 3, 2 y 1 en ese orden, con `total` 3, `page` 1, `size` 20 y `pages` 1

#### Scenario: Segunda página
- **WHEN** existen tres órdenes y se pide `GET /ordenes?page=2&size=2`
- **THEN** la respuesta trae sólo la orden 1, con `total` 3 y `pages` 2

#### Scenario: Página inexistente
- **WHEN** existen tres órdenes y se pide `GET /ordenes?page=3&size=2`
- **THEN** la respuesta es 422 `{"detail": "La página 3 no existe: hay 2"}`

#### Scenario: Tamaño fuera de rango
- **WHEN** se pide `GET /ordenes?size=500` o `GET /mis-ordenes?size=0`
- **THEN** la respuesta es 422

### Requirement: Resumen de una orden en los listados
Cada elemento de `GET /ordenes` y de `GET /mis-ordenes` SHALL ser exactamente `{"id", "estado", "patente", "total", "creada_en", "mecanico_id", "falla", "cliente"}`: `patente` del vehículo, `cliente` el nombre de la ficha dueña del vehículo, `total` como texto con dos decimales y `creada_en` en ISO 8601 con zona. Un elemento MUST NOT traer ítems, historial ni otros campos.

#### Scenario: Forma exacta del resumen
- **WHEN** la recepción lista las órdenes
- **THEN** cada elemento tiene sólo los ocho campos enumerados, sin `items` ni `historial`

#### Scenario: Datos del vehículo y del cliente
- **WHEN** se lista una orden `EN_REPARACION` del vehículo `AD789GH` de la ficha «Jorge Pérez», con total 18000 y asignada al mecánico 4
- **THEN** su elemento trae `estado` `"EN_REPARACION"`, `patente` `"AD789GH"`, `cliente` `"Jorge Pérez"`, `total` `"18000.00"` y `mecanico_id` 4

#### Scenario: Orden sin mecánico
- **WHEN** se lista una orden `PENDIENTE`
- **THEN** su elemento trae `mecanico_id` `null`

### Requirement: Detalle de una orden para el personal o el dueño
`GET /ordenes/{id}` SHALL responder 200 al personal (RECEPCION, ADMIN o MECANICO vigente en la base, cualquiera sea la orden) y al dueño del vehículo: el usuario vinculado a la ficha del cliente del vehículo, también si el vehículo está dado de baja. A cualquier otro usuario con sesión MUST responder 403 `{"detail": "Sólo el personal del taller o el dueño del vehículo puede ver la orden"}`.

#### Scenario: Personal no asignado
- **WHEN** un mecánico que no está asignado a una orden pide su detalle
- **THEN** la respuesta es 200

#### Scenario: Dueño del vehículo
- **WHEN** el cliente dueño del vehículo de una orden pide su detalle
- **THEN** la respuesta es 200

#### Scenario: Orden de otro cliente
- **WHEN** un cliente pide el detalle de una orden de un vehículo de otra ficha
- **THEN** la respuesta es 403 con el mensaje del requisito

#### Scenario: Ficha sin usuario
- **WHEN** un cliente pide el detalle de una orden de un vehículo cuya ficha no tiene usuario vinculado
- **THEN** la respuesta es 403

#### Scenario: Vehículo dado de baja
- **WHEN** el dueño pide el detalle de una orden cancelada de un vehículo que después se dio de baja
- **THEN** la respuesta es 200 con la patente de ese vehículo

### Requirement: Orden de los rechazos del detalle
En `GET /ordenes/{id}` los controles SHALL evaluarse en este orden: sesión (401), cambio de contraseña pendiente (403), id de ruta (422 si no es entero o está fuera de 1 a 2147483647), existencia (404 `{"detail": "La orden no existe"}` a cualquier usuario con sesión) y recién después la relación con la orden (403).

#### Scenario: Sin sesión y con id inválido
- **WHEN** se pide `GET /ordenes/abc` sin cookie
- **THEN** la respuesta es 401, no 422

#### Scenario: Id inválido
- **WHEN** el personal pide `GET /ordenes/abc`, `GET /ordenes/0` o `GET /ordenes/2147483648`
- **THEN** la respuesta es 422

#### Scenario: Orden inexistente para un ajeno
- **WHEN** un cliente sin relación con ninguna orden pide `GET /ordenes/999999`
- **THEN** la respuesta es 404 `{"detail": "La orden no existe"}`, no 403

### Requirement: Forma del detalle de una orden
La respuesta 200 de `GET /ordenes/{id}` SHALL tener exactamente la forma del detalle que responden el alta y las transiciones: `{"id", "estado", "patente", "total", "creada_en", "mecanico_id", "falla", "cliente", "items", "historial"}`, con cada ítem `{"repuesto_id", "codigo", "descripcion", "cantidad", "precio_unitario", "subtotal"}` en el orden en que se cargaron y el historial completo, de la línea más vieja a la más nueva.

#### Scenario: Orden con dos ítems
- **WHEN** se pide el detalle de una orden con un filtro de aceite (1 × 8500) y aceite (4 × 12000)
- **THEN** la respuesta trae esos dos ítems con `subtotal` `"8500.00"` y `"48000.00"`, `total` `"56500.00"` y una línea de historial `null → PENDIENTE`

#### Scenario: Historial de una orden iniciada
- **WHEN** se pide el detalle de una orden que pasó de `PENDIENTE` a `EN_REPARACION`
- **THEN** `historial` tiene dos líneas, `null → PENDIENTE` y `PENDIENTE → EN_REPARACION` con el mecánico como `usuario_id`, y `mecanico_id` es el de ese mecánico

#### Scenario: Igual que la respuesta del alta
- **WHEN** se crea una orden y después se pide su detalle sin cambios intermedios
- **THEN** ambos cuerpos tienen los mismos campos y valores

### Requirement: Órdenes propias del usuario autenticado
`GET /mis-ordenes` SHALL pertenecer al grupo protegido sin exigir rol y responder 200 con las órdenes de todos los vehículos de la ficha vinculada al usuario de la sesión, también los dados de baja, y nunca órdenes de otra ficha (RN17). Un usuario sin ficha, o con una ficha sin vehículos, MUST recibir una página vacía. La ruta MUST NOT aceptar un id de usuario ni de cliente.

#### Scenario: Cliente con órdenes
- **WHEN** un cliente con dos órdenes en sus vehículos llama a `GET /mis-ordenes`
- **THEN** la respuesta es 200 con esas dos órdenes, `total` 2, y ninguna orden de otra ficha

#### Scenario: Usuario sin ficha
- **WHEN** un mecánico sin ficha de cliente llama a `GET /mis-ordenes`
- **THEN** la respuesta es 200 con `items` vacío, `total` 0 y `pages` 1

#### Scenario: Ficha sin vehículos
- **WHEN** un cliente cuya ficha no tiene vehículos llama a `GET /mis-ordenes?page=2`
- **THEN** la respuesta es 422 `{"detail": "La página 2 no existe: hay 1"}`

#### Scenario: Orden de un vehículo dado de baja
- **WHEN** el cliente cancela la orden de un vehículo, el vehículo se da de baja y el cliente llama a `GET /mis-ordenes`
- **THEN** esa orden sigue en la respuesta

#### Scenario: Sin sesión o con cambio pendiente
- **WHEN** se llama a `GET /mis-ordenes` sin cookie, o con un usuario con `debe_cambiar_password` verdadero
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}` o 403 `{"detail": "Debe cambiar la contraseña antes de continuar"}`

### Requirement: Lecturas con un número fijo de consultas
Cada lectura de órdenes SHALL obtener con carga anticipada toda relación que su respuesta muestra, y la cantidad de sentencias SQL MUST NOT depender de la cantidad de ítems de la orden ni de órdenes de la página. Las consultas MUST poder verse en la consola con `SQL_ECHO=true`.

#### Scenario: Detalle con 2 y con 4 ítems (PDF C-15)
- **WHEN** se pide el detalle de una orden con 2 ítems y después el de otra con 4, con `SQL_ECHO=true`
- **THEN** ambas peticiones emiten la misma cantidad de sentencias SQL

#### Scenario: Página con una y con varias órdenes
- **WHEN** se pide `GET /ordenes?size=1` y después `GET /ordenes?size=20` con tres órdenes de vehículos y clientes distintos
- **THEN** ambas peticiones emiten la misma cantidad de sentencias SQL

#### Scenario: Órdenes propias con una y con dos órdenes
- **WHEN** un cliente pide `GET /mis-ordenes` con una orden y, tras crearse otra en otro de sus vehículos, de nuevo
- **THEN** ambas peticiones emiten la misma cantidad de sentencias SQL

### Requirement: Las lecturas no escriben ni bloquean
`GET /ordenes`, `GET /ordenes/{id}` y `GET /mis-ordenes` SHALL ser de sólo lectura: MUST NOT insertar, actualizar ni borrar filas, ni tomar bloqueos de fila, también cuando responden 403, 404 o 422.

#### Scenario: Sin escrituras
- **WHEN** se ejecutan las tres lecturas, incluidas respuestas 403, 404 y 422
- **THEN** ninguna emite `INSERT`, `UPDATE` ni `DELETE` y la cantidad de filas de cada tabla no cambia

#### Scenario: Sin bloqueos
- **WHEN** otra transacción tiene una orden bloqueada con `FOR UPDATE`
- **THEN** su detalle y los listados responden sin esperar a que esa transacción termine
