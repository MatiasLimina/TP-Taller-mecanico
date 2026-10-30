# stock-movements Specification

## Purpose

Define cómo cambia el stock de un repuesto (RN14): sólo a través de movimientos registrados por un único punto de escritura, que usan el alta con stock inicial, la reposición y la terminación de órdenes, sin stock negativo ni movimientos perdidos.

## Requirements

### Requirement: El stock sólo cambia por movimientos
Toda variación del `stock` de un repuesto SHALL quedar registrada en `movimiento_stock`, en la misma transacción, con una fila por repuesto afectado: `cantidad` con signo (positiva entra, negativa sale), `motivo`, `usuario_id` del actor, `orden_id` si la causa es una orden, y `cuando` con zona. Ninguna ruta MUST permitir fijar `stock` por el cuerpo.

#### Scenario: Invariante stock = suma de movimientos
- **WHEN** después de cualquier secuencia de operaciones aceptadas se compara, por repuesto, `stock` con `COALESCE(SUM(movimiento_stock.cantidad), 0)`
- **THEN** ambos valores coinciden para todos los repuestos creados por la API

#### Scenario: Stock por el cuerpo
- **WHEN** un ADMIN envía `stock` en el cuerpo de `POST /repuestos` o de `PATCH /repuestos/{id}`
- **THEN** la respuesta es 422 y no cambia ningún stock ni se registra ningún movimiento

### Requirement: Stock inicial como movimiento
Un alta con `stock_inicial` mayor que 0 SHALL registrar un movimiento con `cantidad` igual a `stock_inicial`, `motivo` «Stock inicial», `orden_id` nulo y el ADMIN como `usuario_id`, atómico con el alta. Con `stock_inicial` 0 u omitido MUST NOT registrarse movimiento y el stock queda en 0.

#### Scenario: Alta con stock inicial
- **WHEN** un ADMIN da de alta un repuesto con `stock_inicial` 10
- **THEN** existe exactamente un movimiento de ese repuesto: `cantidad` 10, `motivo` «Stock inicial», `orden_id` nulo y `usuario_id` del ADMIN

#### Scenario: Alta sin stock inicial
- **WHEN** un ADMIN da de alta un repuesto con `stock_inicial` 0 o sin ese campo
- **THEN** el repuesto queda con stock 0 y no tiene movimientos

#### Scenario: Atomicidad del alta
- **WHEN** el registro del movimiento inicial falla después de insertar el repuesto
- **THEN** no queda ni el repuesto ni el movimiento

### Requirement: Rechazo atómico por stock insuficiente
Un conjunto de movimientos aplicado en una transacción SHALL rechazarse completo con 409 `Stock insuficiente para el repuesto <CODIGO>: hay <N> y se necesitan <M>` si alguno dejaría el stock por debajo de 0: no queda ningún cambio de stock, ningún movimiento ni ninguna otra escritura de esa transacción.

#### Scenario: Uno de varios no alcanza
- **WHEN** en una transacción se aplican salidas de dos repuestos y el segundo no tiene stock suficiente
- **THEN** la operación responde 409 con el código de ese repuesto, y el stock y los movimientos de ambos quedan como estaban

#### Scenario: Salida exacta
- **WHEN** se aplica una salida igual al stock disponible
- **THEN** el stock queda en 0 y se registra el movimiento negativo

### Requirement: Concurrencia sin stock negativo ni actualización perdida
Dos transacciones que mueven el stock del mismo repuesto a la vez SHALL componerse: el resultado MUST ser igual a aplicarlas una después de la otra, el stock MUST NOT quedar negativo y, si la suma no alcanza, una de ellas MUST responder 409 sin escribir nada.

#### Scenario: Dos salidas simultáneas que no entran juntas
- **WHEN** un repuesto tiene stock 5 y dos transacciones simultáneas intentan sacar 3 cada una
- **THEN** una se confirma (stock 2, un movimiento -3) y la otra termina con 409 sin movimiento

#### Scenario: Dos entradas simultáneas
- **WHEN** dos transacciones simultáneas suman 4 y 6 al mismo repuesto con stock 0
- **THEN** el stock final es 10 y hay dos movimientos

#### Scenario: Varios repuestos en orden cruzado
- **WHEN** dos transacciones simultáneas mueven los mismos dos repuestos, cada una con su lista en orden inverso
- **THEN** ambas terminan (confirmadas o con 409) sin interbloqueo ni error 500

### Requirement: Movimientos de sólo agregado
Los movimientos registrados SHALL conservarse sin cambios: la aplicación MUST NOT modificar ni borrar filas de `movimiento_stock`, tampoco al dar de baja el repuesto.

#### Scenario: Baja de un repuesto con movimientos
- **WHEN** un ADMIN da de baja un repuesto con movimientos
- **THEN** sus movimientos siguen existiendo sin cambios

### Requirement: Reposición de stock
`POST /repuestos/{id}/reponer` SHALL sumar `cantidad` al stock de un repuesto vigente y registrar, en la misma transacción, un movimiento con esa `cantidad` (positiva), el `motivo`, `orden_id` nulo y el ADMIN como `usuario_id`. MUST pasar por el mismo punto único de escritura que el alta y la terminación. Responde 200 con el repuesto con el stock resultante.

#### Scenario: Reposición con motivo
- **WHEN** un ADMIN repone 7 unidades con `motivo` `"  Compra a proveedor  "` de un repuesto con stock 5
- **THEN** la respuesta es 200 con el repuesto (`id`, `codigo`, `descripcion`, `precio`, `stock`) y `stock` 12, y existe un movimiento nuevo con `cantidad` 7, `motivo` `"Compra a proveedor"`, `orden_id` nulo y `usuario_id` del ADMIN

#### Scenario: Reposición sin motivo
- **WHEN** un ADMIN repone 4 unidades sin enviar `motivo`
- **THEN** la respuesta es 200 y el movimiento nuevo tiene `motivo` «Reposición»

#### Scenario: Atomicidad de la reposición
- **WHEN** el registro del movimiento falla después de sumar el stock
- **THEN** el stock del repuesto queda como estaba y no queda ningún movimiento nuevo

#### Scenario: Reposiciones simultáneas
- **WHEN** llegan a la vez varias reposiciones del mismo repuesto
- **THEN** todas responden 200, el stock final es el inicial más la suma de las cantidades y hay un movimiento por reposición

### Requirement: Contrato de la reposición
El cuerpo de `reponer` SHALL ser `{cantidad, motivo?}`: `cantidad` entero de 1 a 100 000; `motivo` opcional, recortado, de 1 a 200 caracteres (por defecto «Reposición»). Un valor fuera de contrato, un `null` o un campo no declarado (`stock`, `orden_id`…) MUST responder 422 sin cambiar el stock ni registrar movimientos.

#### Scenario: Cantidad fuera de rango
- **WHEN** un ADMIN envía `cantidad` 0, -3, 1.5, 100001, `"abc"`, `null` o la omite
- **THEN** la respuesta es 422 sobre `cantidad` y el stock y los movimientos quedan como estaban

#### Scenario: Límites aceptados
- **WHEN** un ADMIN envía `cantidad` 1 y después `cantidad` 100000
- **THEN** ambas responden 200 y el stock sube 1 y 100000

#### Scenario: Motivo inválido
- **WHEN** un ADMIN envía `motivo` `"   "`, de 201 caracteres o `null`
- **THEN** la respuesta es 422 sobre `motivo` y no se registra ningún movimiento

#### Scenario: Campo no declarado
- **WHEN** un ADMIN envía `{"cantidad": 2, "stock": 50}` o `{"cantidad": 2, "orden_id": 1}`
- **THEN** la respuesta es 422 y el stock no cambia

#### Scenario: Contrato antes que existencia
- **WHEN** un ADMIN envía un cuerpo inválido a un repuesto inexistente
- **THEN** la respuesta es 422, no 404

### Requirement: Reposición de un repuesto no vigente
Reponer un repuesto inexistente o dado de baja SHALL responder 404 `{"detail": "El repuesto no existe"}` sin cambiar ningún stock ni registrar movimientos, también si la baja ocurre a la vez que la reposición.

#### Scenario: Repuesto inexistente
- **WHEN** un ADMIN repone el repuesto 999999 con un cuerpo válido
- **THEN** la respuesta es 404 `{"detail": "El repuesto no existe"}`

#### Scenario: Repuesto dado de baja
- **WHEN** un ADMIN repone un repuesto dado de baja con stock 3
- **THEN** la respuesta es 404, su stock sigue en 3 y sus movimientos no cambian

#### Scenario: Baja simultánea
- **WHEN** una reposición y una baja del mismo repuesto llegan a la vez
- **THEN** o bien la reposición responde 200 y la baja 204, o bien la baja responde 204 y la reposición 404; nunca 500, y el stock sigue igual a la suma de los movimientos

### Requirement: Consulta de movimientos de un repuesto
`GET /repuestos/{id}/movimientos` SHALL responder 200 con la lista completa de los movimientos del repuesto vigente, sin paginar, en orden de registro (el más antiguo primero). Cada elemento MUST tener exactamente `id`, `cantidad` (con signo), `motivo`, `orden_id` (nulo si no viene de una orden), `usuario_id` y `cuando`. Inexistente o dado de baja → 404.

#### Scenario: Movimientos en orden de registro
- **WHEN** un repuesto se dio de alta con stock inicial 5 y luego se repuso 7
- **THEN** la respuesta es 200 con dos elementos: primero `cantidad` 5 y `motivo` «Stock inicial», después `cantidad` 7, ambos con `orden_id` nulo y `usuario_id` del ADMIN

#### Scenario: Suma de la lista igual al stock
- **WHEN** se suman las `cantidad` de la lista de un repuesto
- **THEN** el resultado es igual al `stock` que muestra `GET /repuestos/{id}`

#### Scenario: Repuesto sin movimientos
- **WHEN** se consultan los movimientos de un repuesto dado de alta con stock 0 y nunca repuesto
- **THEN** la respuesta es 200 `[]`

#### Scenario: Repuesto no vigente
- **WHEN** se consultan los movimientos de un repuesto inexistente o dado de baja
- **THEN** la respuesta es 404 `{"detail": "El repuesto no existe"}`

#### Scenario: Número fijo de consultas
- **WHEN** se consultan los movimientos de un repuesto con 1 movimiento y de otro con 5
- **THEN** ambas peticiones emiten la misma cantidad de consultas a la base
