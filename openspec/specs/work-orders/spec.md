# work-orders Specification

## Purpose

Define el ciclo de vida de una orden de trabajo del taller. Este change cubre el alta: quién abre una orden, qué datos viajan y cuáles calcula el servidor, qué la hace rechazar, qué queda escrito y cómo convive con las bajas y ediciones simultáneas de vehículos y repuestos. C-14 agrega las transiciones y C-15 las lecturas.

## Requirements


### Requirement: Alta de orden sólo por recepción o administración
`POST /ordenes` SHALL estar en el grupo protegido y aceptarse sólo para usuarios con rol vigente RECEPCION o ADMIN. Sin sesión → 401; con cambio de contraseña pendiente → 403; sin esos roles (CLIENTE, MECANICO) → 403 `No tiene permiso para realizar esta operación`. Estos rechazos MUST producirse antes de validar el cuerpo y sin escribir nada, salvo un JSON mal formado, que FastAPI rechaza con 422 antes de resolver la sesión.

#### Scenario: Recepción abre una orden
- **WHEN** un usuario con rol RECEPCION envía un alta válida
- **THEN** la respuesta es 201

#### Scenario: Administración abre una orden
- **WHEN** un usuario con rol ADMIN (sin RECEPCION) envía un alta válida
- **THEN** la respuesta es 201 y la primera línea del historial registra a ese ADMIN

#### Scenario: Cliente o mecánico
- **WHEN** un usuario sólo CLIENTE, o sólo MECANICO, envía un alta válida
- **THEN** la respuesta es 403 y no se crea ninguna orden

#### Scenario: Rol antes que cuerpo
- **WHEN** un usuario sólo CLIENTE envía un cuerpo inválido (`"items": []`)
- **THEN** la respuesta es 403, no 422

#### Scenario: Sin sesión
- **WHEN** se envía `POST /ordenes` sin cookie, aunque el cuerpo traiga `total`
- **THEN** la respuesta es 401, no 422

### Requirement: Cuerpo del alta sin datos calculados por el servidor
El cuerpo SHALL ser `{"vehiculo_id": int, "falla": str, "items": [{"repuesto_id": int, "cantidad": int}, ...]}` y nada más (RN10). `precio`, `precio_unitario`, `total`, `estado`, `creada_en` (la fecha), `mecanico_id` o cualquier otro campo, en la orden o en un ítem, MUST responder 422 sin escribir nada.

#### Scenario: Campos reservados en el cuerpo
- **WHEN** el cuerpo trae además `total`, `estado`, `creada_en` o `mecanico_id`, o un ítem trae `precio_unitario`
- **THEN** la respuesta es 422 `extra_forbidden` sobre ese campo y no se crea ninguna orden

### Requirement: Reglas de los campos del alta
`vehiculo_id` y `repuesto_id` SHALL ser enteros entre 1 y 2147483647; `falla`, sin espacios al inicio ni al final, de 1 a 500 caracteres; `items`, de 1 a 50 elementos; `cantidad`, entera entre 1 y 1000; y ningún `repuesto_id` MUST repetirse en la misma orden. Toda violación MUST responder 422 con el error por campo, sin consultar la base y sin escribir nada.

#### Scenario: Sin ítems
- **WHEN** `items` es `[]` o falta
- **THEN** la respuesta es 422 sobre `items`

#### Scenario: Repuesto repetido
- **WHEN** `items` trae dos veces el mismo `repuesto_id`
- **THEN** la respuesta es 422 sobre `items`, con un mensaje que nombra el repuesto repetido

#### Scenario: Cantidad fuera de rango
- **WHEN** un ítem trae `cantidad` 0, -1, 1001 o 1.5
- **THEN** la respuesta es 422 sobre la `cantidad` de ese ítem

#### Scenario: Demasiados ítems
- **WHEN** `items` trae 51 elementos
- **THEN** la respuesta es 422 sobre `items`

#### Scenario: Falla vacía o larga
- **WHEN** `falla` es `"   "`, tiene 501 caracteres o falta
- **THEN** la respuesta es 422 sobre `falla`

#### Scenario: Ids inválidos
- **WHEN** `vehiculo_id` o un `repuesto_id` es 0, `"abc"` o 2147483648
- **THEN** la respuesta es 422 sobre ese campo, nunca 500

#### Scenario: Recorte de la falla
- **WHEN** `falla` es `"  Ruido al frenar "`
- **THEN** la orden se guarda y se devuelve con `falla` `"Ruido al frenar"`

### Requirement: Sin catálogo de estados no hay órdenes
Si el catálogo `estado_orden` no tiene el estado inicial `PENDIENTE` (en particular, si está vacío), el alta SHALL responder 409 `No se pueden crear órdenes: el catálogo de estados está vacío o no tiene el estado PENDIENTE` (RN19), sin escribir nada. Esta verificación MUST hacerse antes que las del vehículo y los repuestos.

#### Scenario: Catálogo vacío
- **WHEN** `estado_orden` no tiene filas y la recepción envía un alta válida
- **THEN** la respuesta es 409 con ese mensaje y no queda ninguna orden, ítem ni línea de historial

#### Scenario: Catálogo sin el estado inicial
- **WHEN** `estado_orden` tiene EN_REPARACION, TERMINADA y CANCELADA pero no PENDIENTE
- **THEN** la respuesta es 409 con el mismo mensaje

### Requirement: Vehículo vigente
El vehículo de la orden SHALL existir y no estar dado de baja (RN16). Un `vehiculo_id` inexistente o de un vehículo dado de baja MUST responder 409 `El vehículo <id> no existe o está dado de baja`, sin escribir nada. El vehículo se verifica antes que los repuestos.

#### Scenario: Vehículo inexistente
- **WHEN** se envía un alta con `vehiculo_id` 999999
- **THEN** la respuesta es 409 `El vehículo 999999 no existe o está dado de baja`

#### Scenario: Vehículo dado de baja
- **WHEN** se envía un alta para un vehículo dado de baja
- **THEN** la respuesta es 409 con ese mensaje y no se crea ninguna orden

#### Scenario: Vehículo y repuesto inválidos a la vez
- **WHEN** el vehículo no existe y uno de los repuestos tampoco
- **THEN** la respuesta es 409 con el mensaje del vehículo

### Requirement: Repuestos vigentes
Todos los repuestos de los ítems SHALL existir y no estar dados de baja (RN16). Si alguno no cumple, el alta MUST responder 409 `Repuestos inexistentes o dados de baja: <ids>` con todos los ids que no cumplen, en orden ascendente y separados por coma y espacio, y MUST NOT quedar ninguna orden, ítem ni línea de historial (PDF C-10).

#### Scenario: Un repuesto inexistente (PDF C-10)
- **WHEN** la recepción envía un alta con dos ítems y uno tiene `repuesto_id` 999999
- **THEN** la respuesta es 409 `Repuestos inexistentes o dados de baja: 999999` y no queda la orden

#### Scenario: Repuesto dado de baja
- **WHEN** un ítem usa un repuesto dado de baja
- **THEN** la respuesta es 409 con su id y no se crea la orden

#### Scenario: Varios repuestos inválidos
- **WHEN** los ítems usan los repuestos 999998 y 5 (dado de baja) además de uno vigente
- **THEN** la respuesta es 409 `Repuestos inexistentes o dados de baja: 5, 999998`

### Requirement: Precio copiado y total calculado en el servidor
Cada ítem SHALL guardar como `precio_unitario` el precio vigente del repuesto en el momento del alta, y la orden SHALL guardar como `total` la suma exacta de `cantidad × precio_unitario` de sus ítems, en decimal con dos decimales (RN10). Un cambio de precio posterior del repuesto MUST NOT alterar los ítems ni el total de órdenes ya creadas. Si el total supera 9999999999.99, el alta MUST responder 422 `El total de la orden supera el máximo admitido (9999999999.99)` sin escribir nada.

#### Scenario: Precios y total (PDF C-10)
- **WHEN** se abre una orden con 1 de un repuesto de precio 32000.00 y 3 de uno de 12000.00
- **THEN** los ítems guardan `precio_unitario` 32000.00 y 12000.00 y la orden `total` 68000.00

#### Scenario: El precio se copia, no se referencia
- **WHEN** después de crear esa orden el ADMIN cambia el precio del primer repuesto a 35000.00 y se abre otra orden con ese repuesto
- **THEN** la primera orden sigue con `precio_unitario` 32000.00 y `total` 68000.00, y la nueva usa 35000.00

#### Scenario: Total fuera de rango
- **WHEN** un ítem pide 1000 unidades de un repuesto de precio 99999999.99
- **THEN** la respuesta es 422 con el mensaje del máximo y no se crea la orden, nunca 500

#### Scenario: Total fuera de rango con vehículo inválido
- **WHEN** el pedido tiene un total que supera el máximo y además un vehículo inexistente o dado de baja
- **THEN** la respuesta es el 409 del vehículo: el 422 del total se evalúa después de las comprobaciones de vehículo y repuestos, y su `detail` es un texto, no la lista por campo de los 422 de contrato

### Requirement: Estado inicial, mecánico e historial
Una orden aceptada SHALL nacer en estado `PENDIENTE`, sin mecánico (`mecanico_id` nulo), con `creada_en` con zona horaria, y con exactamente una línea de `historial_estado_orden`: `desde_estado` nulo, `hasta_estado` `PENDIENTE`, `usuario_id` del usuario que la creó y `cuando` con zona horaria (RN10, RN19). La orden, sus ítems y esa línea MUST escribirse en una sola transacción: si cualquiera falla, no queda ninguna.

#### Scenario: Filas escritas
- **WHEN** la recepción crea una orden de dos ítems
- **THEN** existen una fila en `orden_trabajo` (`PENDIENTE`, `mecanico_id` nulo), dos en `item_orden` y una en `historial_estado_orden` (`null → PENDIENTE`, `usuario_id` de la recepción)

#### Scenario: Atomicidad
- **WHEN** la escritura de la línea de historial falla después de insertar la orden y sus ítems
- **THEN** no queda la orden ni sus ítems

### Requirement: El alta no mueve stock
El alta de una orden MUST NOT cambiar el `stock` de ningún repuesto ni registrar movimientos (RN14: el stock baja al terminar la orden). Una orden MAY pedir más unidades que el stock disponible; la falta de stock se rechaza al terminarla.

#### Scenario: Stock intacto
- **WHEN** se crea una orden que pide 3 unidades de un repuesto con stock 20
- **THEN** el stock sigue en 20 y `movimiento_stock` no tiene filas nuevas

#### Scenario: Pedido mayor que el stock
- **WHEN** se crea una orden que pide 4 unidades de un repuesto con stock 2
- **THEN** la respuesta es 201 y el stock sigue en 2

### Requirement: Detalle de la orden en la respuesta
La respuesta 201 SHALL ser exactamente `{"id", "estado", "patente", "total", "creada_en", "mecanico_id", "falla", "cliente", "items", "historial"}`: `patente` del vehículo, `cliente` el nombre de la ficha dueña, cada ítem exactamente `{"repuesto_id", "codigo", "descripcion", "cantidad", "precio_unitario", "subtotal"}` en el orden del cuerpo, y cada línea de historial exactamente `{"desde_estado", "hasta_estado", "usuario_id", "cuando"}`, de la más vieja a la más nueva.

#### Scenario: Forma exacta
- **WHEN** se crea una orden válida
- **THEN** la respuesta no tiene otros campos que los enumerados, ni en la orden, ni en los ítems, ni en el historial

#### Scenario: Forma de la respuesta (PDF C-10)
- **WHEN** la recepción crea la orden `{"vehiculo_id": <ZOR001>, "falla": "Ruido al frenar", "items": [{"repuesto_id": 2, "cantidad": 1}, {"repuesto_id": 4, "cantidad": 3}]}`
- **THEN** la respuesta es 201 con `estado` `"PENDIENTE"`, `patente` `"ZOR001"`, `total` `"68000.00"`, `mecanico_id` `null`, el nombre del cliente, dos ítems con `precio_unitario` `"32000.00"`/`"12000.00"` y `subtotal` `"32000.00"`/`"36000.00"`, y un historial `[{"desde_estado": null, "hasta_estado": "PENDIENTE", "usuario_id": <recepción>, "cuando": ...}]`

#### Scenario: Orden de los ítems
- **WHEN** los ítems llegan con `repuesto_id` 4, 1 y 3
- **THEN** la respuesta los lista en ese mismo orden

### Requirement: Importes, fechas y consultas de la respuesta
Los importes de la respuesta (`total`, `precio_unitario` y `subtotal = cantidad × precio_unitario`) SHALL viajar como texto con dos decimales y las fechas en ISO 8601 con zona. La cantidad de consultas necesarias para armar la respuesta MUST NOT depender de la cantidad de ítems.

#### Scenario: Importes como texto
- **WHEN** se crea una orden con 3 unidades de un repuesto de precio 12000
- **THEN** el ítem trae `precio_unitario` `"12000.00"` y `subtotal` `"36000.00"`, y `creada_en`/`cuando` traen zona horaria

#### Scenario: Consultas constantes
- **WHEN** se crea una orden con 1 ítem y otra con 5
- **THEN** ambas altas emiten la misma cantidad de sentencias SQL

### Requirement: Altas concurrentes con bajas y ediciones
El alta SHALL serializarse con la baja del vehículo y con la baja o el cambio de precio de sus repuestos, con el resultado de ejecutarlas una tras otra: MUST NOT quedar una orden abierta sobre un vehículo dado de baja, un ítem de un repuesto dado de baja antes del alta ni un precio distinto del confirmado al leerlo. Ninguna combinación simultánea de altas, bajas, cambios de precio y movimientos de stock MUST terminar en interbloqueo ni en 500.

#### Scenario: Baja del vehículo primero
- **WHEN** una baja del vehículo está en curso y llega un alta para ese vehículo
- **THEN** el alta espera, y al confirmarse la baja responde 409 con el mensaje del vehículo, sin crear la orden

#### Scenario: Alta primero
- **WHEN** un alta está en curso y llega `DELETE /vehiculos/{id}` del mismo vehículo
- **THEN** la baja espera, y al confirmarse el alta responde 409 `El vehículo tiene órdenes abiertas y no se puede dar de baja`

#### Scenario: Baja del repuesto primero
- **WHEN** la baja de un repuesto está en curso y llega un alta que lo usa
- **THEN** el alta espera y responde 409 con el id de ese repuesto

#### Scenario: Cambio de precio primero
- **WHEN** un cambio de precio de un repuesto está en curso y llega un alta que lo usa
- **THEN** el alta espera y el ítem guarda el precio nuevo

#### Scenario: Alta primero contra la baja del repuesto
- **WHEN** un alta que usa un repuesto está en curso y llega su baja
- **THEN** la baja espera al alta; la orden queda con el ítem y después la baja responde 204

#### Scenario: Sin interbloqueos
- **WHEN** se lanzan repetidamente, a la vez, altas con los mismos repuestos en distinto orden, cambios de precio y movimientos de stock de esos repuestos
- **THEN** cada operación termina con su código normal (201, 200, 204, 409) y ninguna con interbloqueo o 500
