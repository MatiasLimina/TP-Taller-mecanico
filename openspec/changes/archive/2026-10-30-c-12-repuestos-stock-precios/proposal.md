# Proposal — C-12 repuestos-stock-precios

## Why

C-11 dejó el catálogo y el **punto único de escritura de stock** (`aplicar_movimientos_stock`), pero hoy el stock sólo entra por el alta («Stock inicial»): no hay reposición, y ni los movimientos ni el historial de precios —que ya se escriben— se pueden leer por la API. Sin este change no se puede reponer la bujía que le falta a la orden #2 (PDF C-12, que C-14 necesita para terminarla), no hay evidencia por HTTP del caso PDF C-18 («una línea nueva en `/repuestos/{id}/precios`») y RN14 queda a medias (la consigna: «el stock se escribe en un único punto, que usan la reposición y la terminación de órdenes»).

## What Changes

- `POST /repuestos/{id}/reponer` (ADMIN): cuerpo `{cantidad, motivo?}`; suma `cantidad` (entero de 1 a `CANTIDAD_MAXIMA_MOVIMIENTO`) al stock y registra un `movimiento_stock` con cantidad **positiva**, el motivo (por defecto «Reposición»), `orden_id` nulo y el ADMIN como `usuario_id`, en una sola transacción y **sólo a través de `aplicar_movimientos_stock`** (nunca escribiendo `stock` por otra vía). Responde 200 con el repuesto (mismo contrato que el catálogo) y el stock resultante. Cantidad o motivo inválidos, o cualquier campo no declarado (`stock`, `orden_id`…) → 422; repuesto inexistente o dado de baja → 404.
- `GET /repuestos/{id}/movimientos` (ADMIN): lista completa de los movimientos del repuesto, en orden cronológico (`id` ascendente), con `id`, `cantidad` (con signo), `motivo`, `orden_id`, `usuario_id` y `cuando`. Sin paginar (la consigna y la matriz no le dan `page`/`size`). Inexistente o dado de baja → 404.
- `GET /repuestos/{id}/precios` (ADMIN): historial de precios del repuesto en orden cronológico, con `id`, `precio_anterior` y `precio_nuevo` (texto `"8500.00"`), `usuario_id` y `cuando`. Sin paginar. Inexistente o dado de baja → 404. Cubre la lectura del caso PDF C-18; la escritura de la línea en el `PATCH` (RN20) **ya la hace C-11** y este change no toca `editar()`.
- Las tres rutas cuelgan de `router_admin_repuestos` (C-11): una sola consulta de roles por petición y `main.py` sin cambios.
- `test/stock.http` (nuevo): casos del change, PDF C-18 (lectura de `/precios` después del PATCH) y la reposición que usa PDF C-12.

Fuera de alcance: descontar stock al terminar órdenes (C-14) y el caso PDF C-12 completo (reponer **y terminar** la orden #2, que se cierra en C-14); `seed.py` (C-06); filtros o paginación de los historiales; mostrar el correo del actor; reponer o leer historiales de repuestos dados de baja; ajustes negativos de stock por la API (sólo las órdenes sacan stock); migraciones o índices nuevos.

## Capabilities

### New Capabilities
(ninguna: las tres rutas pertenecen a capacidades que creó C-11)

### Modified Capabilities
- `parts-catalog`: «Acceso al catálogo por rol» incluye `reponer`, `movimientos` y `precios` entre las rutas sólo ADMIN (403 antes de validar o buscar).
- `stock-movements`: se agregan la reposición (entrada positiva por el punto único, contrato de `{cantidad, motivo?}`, 404 por baja) y la consulta de movimientos de un repuesto.
- `price-history`: se agrega la consulta `GET /repuestos/{id}/precios` (orden, contrato de salida, 404).

## Impact

- **Código modificado**: `app/modules/repuestos/schemas.py` (contratos `ReposicionEntrada`, `MovimientoSalida`, `PrecioHistorialSalida`), `repository.py` (un listado por repuesto en `MovimientoStockRepository` y en `HistorialPrecioRepository`), `service.py` (`reponer`, `listar_movimientos`, `listar_precios`), `router.py` (tres rutas en `router_admin_repuestos`).
- **Código nuevo**: `test/stock.http`.
- **Sin cambios**: `aplicar_movimientos_stock` y su contrato, `editar()`, `alta()`, modelos, migraciones (los índices `ix_movimiento_stock_repuesto_id` e `ix_historial_precio_repuesto_repuesto_id` ya existen), `app/core/*`, `main.py`, otros módulos, `test/repuestos.http`.
- **Dependencias**: ninguna nueva.
- **Downstream**: C-14 (terminar) usa el mismo punto único con cantidades negativas y `orden_id`; esas salidas aparecerán en `GET /repuestos/{id}/movimientos` sin cambios en este change. La evidencia PDF C-12 se completa en el `.http` de C-14 (reponer acá + terminar allá).
- **Governance**: ALTO (stock e historiales de sólo agregado). Proponer y esperar revisión antes de escribir: los supuestos S-01…S-12 de design.md están **confirmados por el usuario el 2026-10-30**.
