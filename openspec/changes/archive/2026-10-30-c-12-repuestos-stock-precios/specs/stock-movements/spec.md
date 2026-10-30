## ADDED Requirements

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
