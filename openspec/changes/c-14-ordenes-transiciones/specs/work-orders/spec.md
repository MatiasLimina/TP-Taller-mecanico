# Spec Delta — work-orders

## ADDED Requirements

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
