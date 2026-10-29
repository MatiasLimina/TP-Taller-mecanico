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
