# Proposal — C-13 ordenes-alta-estados

## Why

El módulo `ordenes` sólo tiene modelos (C-03): no se puede abrir una orden de trabajo ni consultar el catálogo de estados, y sin órdenes no avanzan C-14 (iniciar, terminar, cancelar) ni C-15 (lecturas). Falta además la evidencia del caso PDF C-10 («alta de una orden con dos ítems: 201 con los precios copiados, el total y el historial; con un repuesto inexistente, 409 y la orden no queda creada») y de RN10, RN16 (vehículo o repuesto dado de baja no se usa en órdenes nuevas) y RN19 (catálogo vacío → 409 propio). Es el primer change que escribe en cuatro tablas en una transacción y que toma filas de otros dos módulos (vehículo y repuestos), así que fija el contrato de bloqueos que C-14 continúa.

## What Changes

- `POST /ordenes` (RECEPCION, ADMIN): cuerpo `{vehiculo_id, falla, items: [{repuesto_id, cantidad}]}`; `precio`, `precio_unitario`, `total`, `estado`, `fecha`, `creada_en`, `mecanico_id` o cualquier otro campo → 422 (`extra="forbid"`). Al menos un ítem, a lo sumo 50, sin repuestos repetidos (422 en el contrato). En **un solo Unit of Work**: verifica que el catálogo tenga el estado inicial `PENDIENTE` (si no, 409 propio, RN19), bloquea y verifica el vehículo vigente (inexistente o dado de baja → 409), lee **en una consulta** los repuestos pedidos vigentes con `FOR SHARE` en orden de id (alguno inexistente o dado de baja → 409 con todos los ids que faltan), copia `precio_unitario` de cada repuesto, calcula `total` en el servidor con `Decimal`, y crea la orden `PENDIENTE` (sin mecánico) + sus ítems + la primera línea de historial `null → PENDIENTE` con el actor como `usuario_id`. Cualquier rechazo deja la base sin orden, ítems ni historial. No toca `stock` (RN14: el stock sólo baja al terminar, C-14).
- Respuesta 201 con el detalle de la orden en la forma del ejemplo de la consigna: `id`, `estado`, `patente`, `total`, `creada_en`, `mecanico_id`, `falla`, `cliente` (nombre), `items` (`repuesto_id`, `codigo`, `descripcion`, `cantidad`, `precio_unitario`, `subtotal`) e `historial` (`desde_estado`, `hasta_estado`, `usuario_id`, `cuando`); dinero como texto (`"68000.00"`). Se arma releyendo la orden con un método de repositorio con precarga declarada y número fijo de consultas, que C-15 reutiliza para `GET /ordenes/{id}`.
- `GET /estados-orden` (cualquier usuario autenticado): el catálogo completo (`codigo`, `descripcion`, `posicion`, `es_final`) ordenado por `posicion`; catálogo vacío → `[]`.
- `EstadoOrdenRepository` de sólo lectura (no hereda de `BaseRepository`: la PK es `codigo` y la API no escribe el catálogo).
- `OrdenesUoW` compone los repositorios de órdenes, el `VehiculoRepository` de C-10 (bloqueo del vehículo) y el `RepuestoRepository` + `MovimientoStockRepository` de C-11 (lectura de repuestos y, para C-14, el protocolo `ConStock` del punto único de escritura de stock), todos sobre la misma sesión.
- Un método nuevo en `RepuestoRepository` (archivo de Mati, coordinado): lectura de los repuestos vigentes pedidos en una consulta, en orden de id, con `FOR SHARE` (design.md S-01).
- `main.py`: dos routers (`/ordenes`, `/estados-orden`) en `rutas_protegidas`, al final de la lista existente.
- `test/ordenes.http` (nuevo): casos del change y PDF C-10, con estado conocido propio.

Fuera de alcance: iniciar, terminar y cancelar (C-14); `GET /ordenes`, `GET /ordenes/{id}` y `GET /mis-ordenes` (C-15); descontar stock; editar una orden o sus ítems; `seed.py` (C-06); migraciones (no se crea ninguna).

## Capabilities

### New Capabilities
- `work-orders`: ciclo de vida de una orden de trabajo — en este change, el alta: contrato de entrada sin precio/total/estado/fecha, ítems sin repetir, vehículo y repuestos vigentes, precio copiado y total calculado en el servidor, estado inicial e historial, atomicidad, serialización con las bajas y ediciones concurrentes, y contrato de salida del detalle. C-14 le agrega las transiciones y C-15 las lecturas.
- `order-states`: catálogo de estados de una orden (RN19) — sus filas son los únicos estados posibles, la API lo expone de sólo lectura ordenado por `posicion`, y sin el estado inicial no se crean órdenes.

### Modified Capabilities
(ninguna: `access-control`, `api-contracts`, `unit-of-work`, `data-repositories`, `error-translation`, `append-only-history`, `parts-catalog` y `stock-movements` se usan tal como están; el bloqueo del vehículo cumple la nota que C-10 dejó para C-13 sin cambiar sus requisitos)

## Impact

- **Código nuevo**: `app/modules/ordenes/{schemas,repository,unit_of_work,service,router}.py`, `test/ordenes.http`.
- **Código modificado**: `main.py` (montaje de dos routers); `app/modules/repuestos/repository.py` (un método de lectura con `FOR SHARE`, sin cambiar los existentes — requiere acuerdo de Mati, S-01).
- **Sin cambios**: modelos y migraciones (`ck_orden_trabajo_total_no_negativo`, `ck_item_orden_cantidad_positiva`, `ck_item_orden_precio_unitario_positivo`, `uq_item_orden_orden_id_repuesto_id`, las FK a `estado_orden.codigo` y el disparador de sólo agregado sobre `historial_estado_orden` existen desde C-03/C-04), `app/core/*`, `app/modules/clientes/*`, `app/modules/usuarios/*`, el punto único de escritura de stock.
- **Dependencias**: ninguna nueva. Requiere C-10 y C-11 mergeados (lo están).
- **Downstream**: C-14 abre el mismo `OrdenesUoW`, bloquea la orden y llama a `aplicar_movimientos_stock` con él; C-15 reutiliza `OrdenTrabajoRepository.get_detalle` y el armado de `OrdenDetalleSalida` (si se confirma S-05, su alcance en `CHANGES.md` pasa de «implementar la precarga» a «reutilizarla y medirla»).
- **Governance**: ALTO (transacción multi-tabla, núcleo del dominio). Proponer y esperar revisión antes de escribir: los supuestos S-01…S-17 de design.md están **confirmados por el usuario el 2026-10-30** (S-01 queda pendiente del acuerdo de Mati).
