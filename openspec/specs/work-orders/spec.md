# work-orders Specification

## Purpose

Define el ciclo de vida de una orden de trabajo del taller. Este change cubre el alta: quién abre una orden, qué datos viajan y cuáles calcula el servidor, qué la hace rechazar, qué queda escrito y cómo convive con las bajas y ediciones simultáneas de vehículos y repuestos. Cubre también la creación, las transiciones de estado (iniciar, terminar, cancelar) y las lecturas (listados y detalle).

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

### Requirement: Iniciar una orden sólo con rol de mecánico
`POST /ordenes/{id}/iniciar` SHALL aceptarse sólo para usuarios con rol vigente MECANICO (un ADMIN sin ese rol no inicia). Sin sesión → 401; con cambio de contraseña pendiente → 403; sin el rol → 403 `No tiene permiso para realizar esta operación`. Estos rechazos MUST producirse antes de buscar la orden y sin escribir nada.

#### Scenario: Mecánico inicia una orden pendiente
- **WHEN** un usuario con rol MECANICO inicia una orden `PENDIENTE`
- **THEN** la respuesta es 200 con `estado` `EN_REPARACION` y `mecanico_id` igual al id de ese usuario

#### Scenario: Administración sin rol de mecánico
- **WHEN** un usuario sólo ADMIN inicia una orden `PENDIENTE`
- **THEN** la respuesta es 403 y la orden sigue `PENDIENTE` sin mecánico

#### Scenario: Cliente o recepción
- **WHEN** un usuario sólo CLIENTE, o sólo RECEPCION, inicia una orden
- **THEN** la respuesta es 403 y la orden no cambia

#### Scenario: Rol antes que orden
- **WHEN** un usuario sólo CLIENTE inicia una orden inexistente
- **THEN** la respuesta es 403, no 404

### Requirement: Sólo se inicia una orden pendiente
Iniciar SHALL aceptarse sólo si la orden está `PENDIENTE`. En cualquier otro estado MUST responder 409 sin escribir nada; una orden ya iniciada MUST NOT reasignarse a otro mecánico.

#### Scenario: Orden ya iniciada por el mismo mecánico
- **WHEN** el mecánico asignado vuelve a iniciar su orden `EN_REPARACION`
- **THEN** la respuesta es 409 y el historial no gana líneas

#### Scenario: Orden ya iniciada por otro mecánico
- **WHEN** otro mecánico inicia una orden `EN_REPARACION`
- **THEN** la respuesta es 409 y `mecanico_id` sigue siendo el del primero

#### Scenario: Orden terminada o cancelada
- **WHEN** un mecánico inicia una orden `TERMINADA` o `CANCELADA`
- **THEN** la respuesta es 409

### Requirement: Las transiciones no reciben datos del cliente
Iniciar, terminar y cancelar SHALL operar sólo con el id de la ruta y el actor de la sesión: el estado destino, el mecánico asignado y el autor del historial los decide el servidor. Un cuerpo enviado MUST NOT cambiar el resultado.

#### Scenario: Cuerpo con mecánico y estado
- **WHEN** un mecánico inicia una orden enviando un cuerpo con otro `mecanico_id` y `estado` `TERMINADA`
- **THEN** la respuesta es 200 con `estado` `EN_REPARACION` y `mecanico_id` igual al del actor

### Requirement: Orden inexistente e id inválido en las transiciones
Una orden inexistente SHALL responder 404 `La orden no existe` en las tres transiciones, antes de evaluar el permiso por relación (terminar, cancelar) o el estado. Un id que no es entero entre 1 y 2147483647 MUST responder 422, nunca 500.

#### Scenario: Orden inexistente sin permiso
- **WHEN** un usuario sólo CLIENTE termina o cancela una orden inexistente
- **THEN** la respuesta es 404, no 403

#### Scenario: Id fuera de rango
- **WHEN** se llama a una transición con id `0`, `abc` o `2147483648`
- **THEN** la respuesta es 422

### Requirement: Terminar sólo el mecánico asignado o la administración
`POST /ordenes/{id}/terminar` SHALL aceptarse para el mecánico asignado a la orden que conserva el rol MECANICO vigente, o para un usuario con rol ADMIN vigente. Cualquier otro usuario con sesión MUST recibir 403 antes de evaluar el estado y sin escribir nada.

#### Scenario: Mecánico no asignado
- **WHEN** un mecánico distinto del asignado termina una orden `EN_REPARACION`
- **THEN** la respuesta es 403 y la orden, el stock y los movimientos no cambian

#### Scenario: Administración no asignada
- **WHEN** un ADMIN termina una orden `EN_REPARACION` asignada a un mecánico
- **THEN** la respuesta es 200 y el historial y los movimientos registran al ADMIN como actor

#### Scenario: Mecánico asignado sin rol vigente
- **WHEN** al mecánico asignado le revocaron el rol MECANICO y termina su orden
- **THEN** la respuesta es 403

#### Scenario: Permiso antes que estado
- **WHEN** un mecánico (no ADMIN) termina una orden `PENDIENTE`, que no tiene mecánico asignado
- **THEN** la respuesta es 403, no 409

#### Scenario: Cliente o recepción
- **WHEN** un usuario sólo CLIENTE, o sólo RECEPCION, termina una orden
- **THEN** la respuesta es 403

### Requirement: Sólo se termina una orden en reparación
Terminar SHALL aceptarse, para quien tiene permiso, sólo si la orden está `EN_REPARACION`; en otro estado MUST responder 409 sin escribir nada.

#### Scenario: Orden pendiente por la administración
- **WHEN** un ADMIN termina una orden `PENDIENTE`
- **THEN** la respuesta es 409 y el stock no cambia

#### Scenario: Orden ya terminada
- **WHEN** el mecánico asignado termina otra vez su orden `TERMINADA`
- **THEN** la respuesta es 409 y no se registra ningún movimiento nuevo

### Requirement: Terminar descuenta el stock de cada ítem
Terminar SHALL, en una sola transacción, restar del stock de cada repuesto la cantidad de su ítem, registrar por ítem un movimiento con `cantidad` negativa, el `orden_id`, el actor como `usuario_id` y el motivo `Orden #<id> terminada`, pasar la orden a `TERMINADA` y agregar su línea de historial. Un repuesto dado de baja después de crear la orden MUST descontarse igual.

#### Scenario: Terminación con stock suficiente
- **WHEN** el mecánico asignado termina una orden con ítems de 1 filtro y 4 litros de aceite, con stock 10 y 20
- **THEN** la respuesta es 200 con `estado` `TERMINADA`, el stock queda en 9 y 16 y hay dos movimientos nuevos (-1 y -4) con ese `orden_id`

#### Scenario: Repuesto dado de baja
- **WHEN** se termina una orden cuyo repuesto fue dado de baja después del alta
- **THEN** la respuesta es 200 y el stock de ese repuesto baja con su movimiento

#### Scenario: Salida exacta
- **WHEN** un ítem pide exactamente el stock disponible
- **THEN** la respuesta es 200 y el stock de ese repuesto queda en 0

### Requirement: Falta de stock al terminar revierte todo
Si algún repuesto de la orden no alcanza, terminar SHALL responder 409 `Stock insuficiente para el repuesto <código>: hay <N> y se necesitan <M>` y MUST dejar sin cambios el estado de la orden, el stock y los movimientos de todos sus repuestos y el historial (RN13).

#### Scenario: Orden que pide más de lo que hay (PDF C-11)
- **WHEN** se termina una orden `EN_REPARACION` que pide 4 bujías y hay 2
- **THEN** la respuesta es 409 `Stock insuficiente para el repuesto <código de la bujía>: hay 2 y se necesitan 4`, la orden sigue `EN_REPARACION`, el stock sigue en 2 y no hay movimientos ni líneas de historial nuevos

#### Scenario: Falta el segundo de tres repuestos
- **WHEN** se termina una orden con tres repuestos y sólo el segundo (por id) no alcanza
- **THEN** la respuesta es 409 con el código del segundo y el stock del primero, ya descontado dentro de la transacción, vuelve a su valor anterior

#### Scenario: Reponer y terminar (PDF C-12)
- **WHEN** después del 409 un ADMIN repone 2 bujías y se vuelve a terminar la orden
- **THEN** la respuesta es 200, el stock de la bujía queda en 0 y sus movimientos muestran la reposición (+2) y la salida (-4) con el `orden_id`

### Requirement: Aviso al cliente sólo después de confirmar
Al terminar una orden con éxito el servidor SHALL agendar un aviso simulado al cliente (espera de 0,5 s y una línea en el registro del servidor con el id de la orden y la patente) que corre después de enviar la respuesta y sólo si la transacción se confirmó. Una terminación rechazada (403, 404, 409, 422) MUST NOT producir aviso.

#### Scenario: Aviso tras terminar (PDF C-12)
- **WHEN** una orden se termina con 200
- **THEN** la línea del aviso aparece en el registro del servidor después de la respuesta, y en ese momento la orden ya figura `TERMINADA` para cualquier otra conexión

#### Scenario: Sin aviso si no se confirma
- **WHEN** terminar responde 409 por falta de stock, o 403, o 404
- **THEN** no aparece ninguna línea de aviso

#### Scenario: Iniciar y cancelar no avisan
- **WHEN** una orden se inicia o se cancela con 200
- **THEN** no aparece ninguna línea de aviso

### Requirement: Cancelar sólo recepción, administración o el dueño
`POST /ordenes/{id}/cancelar` SHALL aceptarse para usuarios con rol vigente RECEPCION o ADMIN, o para el usuario de la ficha de cliente dueña del vehículo de la orden, aunque no tenga rol de personal. Cualquier otro usuario con sesión MUST recibir 403 antes de evaluar el estado y sin escribir nada (RN12).

#### Scenario: El dueño cancela su orden pendiente (PDF C-13)
- **WHEN** el dueño del vehículo, sólo CLIENTE, cancela su orden `PENDIENTE`
- **THEN** la respuesta es 200 con `estado` `CANCELADA` y la línea de historial lo registra como actor

#### Scenario: Orden ajena (PDF C-13)
- **WHEN** un usuario sólo CLIENTE cancela una orden de un vehículo que no es suyo
- **THEN** la respuesta es 403 y la orden sigue `PENDIENTE`

#### Scenario: Mecánico que no es el dueño
- **WHEN** un usuario sólo MECANICO cancela una orden de un vehículo ajeno
- **THEN** la respuesta es 403

#### Scenario: Recepción cancela la orden de un cliente sin usuario
- **WHEN** un usuario RECEPCION cancela una orden `PENDIENTE` del vehículo de una ficha sin usuario
- **THEN** la respuesta es 200

#### Scenario: Permiso antes que estado
- **WHEN** un usuario ajeno cancela una orden `EN_REPARACION` o `TERMINADA`
- **THEN** la respuesta es 403, no 409

### Requirement: Sólo se cancela una orden pendiente
Cancelar SHALL aceptarse, para quien tiene permiso, sólo si la orden está `PENDIENTE`; en `EN_REPARACION`, `TERMINADA` o `CANCELADA` MUST responder 409 sin escribir nada. Cancelar no mueve stock ni asigna mecánico.

#### Scenario: Orden terminada (PDF C-13)
- **WHEN** la recepción o el dueño cancelan una orden `TERMINADA`
- **THEN** la respuesta es 409

#### Scenario: Orden en reparación
- **WHEN** el dueño cancela su orden `EN_REPARACION`
- **THEN** la respuesta es 409 y la orden sigue `EN_REPARACION`

#### Scenario: Orden ya cancelada
- **WHEN** se cancela otra vez una orden `CANCELADA`
- **THEN** la respuesta es 409 y el historial no gana líneas

### Requirement: Reglas de estado guiadas por el catálogo
Toda transición SHALL leer el catálogo de estados: si el estado actual de la orden es final (`es_final`) MUST responder 409 `La orden <id> está <estado>, un estado final: no admite más cambios`; si el estado destino no está en el catálogo MUST responder 409 `El catálogo de estados no tiene el estado <estado>`. Sin escribir nada en ambos casos.

#### Scenario: Estado final
- **WHEN** se inicia, termina o cancela una orden `TERMINADA` o `CANCELADA` (finales en el catálogo)
- **THEN** la respuesta es 409 con el mensaje de estado final

#### Scenario: El catálogo decide qué es final
- **WHEN** el catálogo marca `PENDIENTE` como final y un mecánico inicia una orden `PENDIENTE`
- **THEN** la respuesta es 409 con el mensaje de estado final

#### Scenario: Estado destino fuera del catálogo
- **WHEN** el catálogo no tiene `CANCELADA` y un ADMIN cancela una orden `PENDIENTE`
- **THEN** la respuesta es 409 `El catálogo de estados no tiene el estado CANCELADA` y la orden sigue `PENDIENTE`

### Requirement: Cada transición deja una línea de historial
Cada transición aceptada SHALL agregar exactamente una línea a `historial_estado_orden` con el estado anterior, el nuevo, el actor como `usuario_id` y el instante con zona; las líneas anteriores MUST conservarse sin cambios. Una transición rechazada MUST NOT agregar líneas.

#### Scenario: Ciclo completo
- **WHEN** una orden se crea, se inicia y se termina
- **THEN** su historial tiene, en orden, `null → PENDIENTE`, `PENDIENTE → EN_REPARACION` (el mecánico) y `EN_REPARACION → TERMINADA` (quien terminó)

#### Scenario: Cancelación
- **WHEN** una orden `PENDIENTE` se cancela
- **THEN** su historial termina en `PENDIENTE → CANCELADA` con quien canceló, y `mecanico_id` sigue nulo

### Requirement: Respuesta de las transiciones
Una transición aceptada SHALL responder 200 con el detalle de la orden en la misma forma que el alta (`id`, `estado`, `patente`, `total`, `creada_en`, `mecanico_id`, `falla`, `cliente`, `items`, `historial`), con el estado nuevo y el historial completo, leído después de escribir. MUST NOT incluir datos de autenticación ni el stock.

#### Scenario: Detalle tras terminar
- **WHEN** una orden se termina con 200
- **THEN** la respuesta trae `estado` `TERMINADA`, los mismos `items` y `total` del alta y tres líneas de `historial`

### Requirement: Transiciones concurrentes sin interbloqueos
Dos operaciones simultáneas sobre la misma orden SHALL resolverse como si fueran sucesivas (la segunda ve el estado que dejó la primera). Terminaciones, altas de órdenes, reposiciones, ediciones y bajas de repuestos y bajas de vehículos simultáneas MUST terminar todas con su respuesta normal (2xx, 403, 404 o 409), nunca con un interbloqueo ni un 500.

#### Scenario: Dos terminaciones de la misma orden
- **WHEN** dos usuarios con permiso terminan a la vez la misma orden `EN_REPARACION`
- **THEN** una responde 200 y la otra 409, y el stock se descuenta una sola vez

#### Scenario: Iniciar y cancelar a la vez
- **WHEN** a la vez una orden se inicia y se cancela estando `PENDIENTE`
- **THEN** exactamente una de las dos responde 200, la otra 409, y el historial tiene una sola línea nueva

#### Scenario: Repuestos compartidos en orden cruzado
- **WHEN** se terminan a la vez dos órdenes con los mismos repuestos, mientras se crea otra orden con ellos, se repone uno y se cambia el precio del otro
- **THEN** todas terminan sin interbloqueo ni 500, y el stock de cada repuesto es igual a la suma de sus movimientos

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
