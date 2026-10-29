# Proposal — C-11 repuestos-catalogo

## Why

El módulo `repuestos` sólo tiene modelos (C-03): no hay forma de dar de alta, buscar, editar ni dar de baja un repuesto, y no existe el **punto único de escritura de stock** que exige la consigna (RN14, Ejercicio 6: «el stock se escribe en un único punto, que usan la reposición y la terminación de órdenes»). Sin este change no avanzan C-12 (reposición, movimientos e historial de precios), C-13 (alta de órdenes, que copia el precio de repuestos vigentes) ni C-14 (terminar descuenta stock por ese punto único, RN13). Tampoco hay evidencia del caso PDF C-16 (búsqueda con `' OR '1'='1`, paginación con filtro, PATCH parcial, PATCH del stock → 422).

## What Changes

- `GET /repuestos?q&page&size` (ADMIN, RECEPCION, MECANICO): catálogo de repuestos vigentes, paginado con el envoltorio común; `q` busca por descripción o código, sin distinguir mayúsculas, con parámetros ligados (`' OR '1'='1` → página vacía con `total` 0; `%` y `_` se buscan como texto).
- `GET /repuestos/{id}` (ADMIN, RECEPCION, MECANICO): detalle de un repuesto vigente; inexistente o dado de baja → 404.
- `POST /repuestos` (ADMIN): alta con `{codigo, descripcion, precio, stock_inicial?}`. Un `stock_inicial` mayor que 0 entra **por el punto único de escritura**: deja un `movimiento_stock` «Stock inicial» con cantidad positiva y el ADMIN como `usuario_id`, en el mismo Unit of Work. Código vigente repetido → 409 propio (lo decide el índice único parcial, sin consulta previa); el código de un repuesto dado de baja se puede reutilizar. `stock` en el cuerpo → 422.
- `PATCH /repuestos/{id}` (ADMIN): sólo `descripcion` y `precio`, con `exclude_unset`; `stock`, `codigo` o cualquier otro campo → 422. **Si el precio cambia, se agrega la línea de `historial_precio_repuesto` (anterior/nuevo) en la misma transacción; si no cambia, ninguna** (RN20, adelantado de C-12 — ver design.md S-03).
- `DELETE /repuestos/{id}` (ADMIN): baja lógica (`borrado_en`), 204; el repuesto deja de aparecer en el catálogo, conserva stock, movimientos e historial.
- **Punto único de escritura de stock (RN14)**: `aplicar_movimientos_stock(...)` en `app/modules/repuestos/service.py`, que se llama **dentro** de un Unit of Work ya abierto por el servicio que lo usa (repuestos u órdenes), aplica cada movimiento con un `UPDATE` atómico condicional (`stock + :delta >= 0`), en orden ascendente de `repuesto_id`, escribe siempre su `movimiento_stock` y lanza un 409 propio si el stock no alcanza. C-11 lo usa para «Stock inicial»; C-12 (reponer) y C-14 (terminar) lo reutilizan sin escribir `stock` por su cuenta. Contrato completo en design.md (D4 y «Notas para otros changes»).
- `main.py`: los dos routers de `/repuestos` (lectura para el personal, escritura sólo ADMIN) se montan en `rutas_protegidas` antes de `app.include_router(rutas_protegidas)`.
- `test/repuestos.http` (nuevo): casos del change, PDF C-16 y la parte de PDF C-18 que cubre el PATCH (línea nueva al cambiar el precio, ninguna al cambiar sólo la descripción, RECEPCION → 403).

Fuera de alcance: `POST /repuestos/{id}/reponer`, `GET /repuestos/{id}/movimientos` y `GET /repuestos/{id}/precios` (C-12); descontar stock al terminar órdenes (C-14); `seed.py` (C-06); listar repuestos dados de baja o reactivarlos; cambiar el código de un repuesto; índices de búsqueda (sin migraciones nuevas).

## Capabilities

### New Capabilities
- `parts-catalog`: catálogo de repuestos — alta, búsqueda paginada con parámetros ligados, detalle, edición parcial (descripción y precio) y baja lógica; contrato de entrada y salida, unicidad del código entre vigentes, visibilidad por rol.
- `stock-movements`: cómo cambia el stock (RN14) — sólo por movimientos registrados por el punto único de escritura; alta con stock inicial; nunca por PATCH; invariante `stock = SUM(movimiento_stock.cantidad)`; rechazo atómico cuando no alcanza; concurrencia sin stock negativo ni actualización perdida.
- `price-history`: cada cambio de precio deja una línea anterior/nuevo en la misma transacción y un PATCH que no cambia el precio no deja ninguna (RN20). C-12 le suma la consulta `GET /repuestos/{id}/precios`.

### Modified Capabilities
(ninguna: `access-control`, `api-contracts`, `list-pagination`, `data-repositories`, `unit-of-work`, `error-translation` y `append-only-history` se usan tal como están)

## Impact

- **Código nuevo**: `app/modules/repuestos/{schemas,repository,unit_of_work,service,router}.py`, `test/repuestos.http`.
- **Código modificado**: `main.py` (montaje de dos routers en `rutas_protegidas`).
- **Sin cambios**: modelos y migraciones (`uq_repuesto_codigo` parcial, `ck_repuesto_precio_positivo`, `ck_repuesto_stock_no_negativo`, `ck_movimiento_stock_cantidad_no_nula`, `ck_historial_precio_repuesto_precio_distinto` y el disparador de sólo agregado existen desde C-03/C-04), `app/core/*`, módulo `usuarios`, `test/solo_agregado.sql`.
- **Dependencias**: ninguna nueva.
- **Downstream**: C-12 agrega reponer/movimientos/precios sobre los mismos archivos y reutiliza el punto único; C-13 usa `RepuestoRepository` para validar repuestos vigentes y copiar el precio; C-14 descuenta stock **sólo** con `aplicar_movimientos_stock`. Si se confirma S-03, el alcance de C-12 en `CHANGES.md` pierde «extensión del PATCH» (lo actualiza quien archiva).
- **Governance**: MEDIO. Implementación por pasos con checkpoints; los supuestos S-01…S-16 de design.md están **confirmados por el usuario el 2026-10-29** (en especial S-01/S-02, que fijan el contrato que consumen C-12 y C-14, y S-03, que mueve RN20 desde C-12).
