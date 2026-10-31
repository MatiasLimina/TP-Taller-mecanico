# Proposal — C-15 ordenes-lecturas-sin-n-plus-1

## Why

Con C-13 y C-14 una orden se crea y cambia de estado, pero nadie puede consultarla: no hay listado para el personal, ni detalle, ni forma de que un cliente vea las órdenes de sus vehículos (RN17). Además falta la evidencia del Ejercicio 8 (8 %, «Lecturas sin N+1 y asincronía»): el caso PDF C-15 exige que el detalle de una orden con 2 y con 4 ítems emita **la misma cantidad de consultas** en la consola (`SQL_ECHO=true`), y el README final (C-16) tiene que mostrar ese fragmento. Es ahora porque C-13 (con `get_detalle`/`armar_detalle`, la precarga del detalle) y C-14 (transiciones, historial completo, `mecanico_id`) ya están en `main`, y C-16 depende de este change.

## What Changes

- `GET /ordenes?estado&page&size` (RECEPCION, ADMIN o MECANICO vigentes; el personal ve **todas** las órdenes): página con el envoltorio común (`items`, `total`, `page`, `size`, `pages`), de la más nueva a la más vieja; `estado` opcional y sólo con los códigos del contrato (`PENDIENTE`, `EN_REPARACION`, `TERMINADA`, `CANCELADA`, mayúsculas exactas), cualquier otro → 422; `total` cuenta con el mismo filtro. Cada elemento es un **resumen** de la orden (sin ítems ni historial) con la patente y el nombre del cliente precargados en la misma consulta de la página.
- `GET /ordenes/{id}` (el personal, o el dueño del vehículo): **reutiliza** `OrdenTrabajoRepository.get_detalle` y `service.armar_detalle` de C-13 (misma forma que el alta y las transiciones: vehículo, cliente, ítems con su repuesto e historial completo). Orden de los rechazos: 401 → 403 (cambio pendiente) → 422 (id) → 404 → 403 (ni personal ni dueño), el mismo criterio «404 antes que 403» de C-14. El dueño es el usuario de la ficha del cliente del vehículo, también si el vehículo está dado de baja.
- `GET /mis-ordenes?page&size` (cualquier usuario autenticado): sólo las órdenes de los vehículos de la ficha del usuario de la sesión (RN17), incluidas las de vehículos dados de baja; sin ficha o sin vehículos → página vacía. Misma forma de resumen y mismo envoltorio.
- Número fijo de consultas: el detalle emite las mismas sentencias con 2 y con 4 ítems; una página de listado, las mismas con 1 o con N órdenes. Toda relación que la respuesta muestra se precarga en el método del repositorio (nunca carga perezosa); las tres rutas son de sólo lectura (sin bloqueos ni escrituras).
- Evidencia del caso PDF C-15 (entregable de Lauti por REPARTO §6): `test/evidencia_c15.txt`, las líneas de `SQL_ECHO=true` del detalle de una orden con 2 ítems y de otra con 4, generadas por el script temporal de verificación; C-16 la lleva al README.
- `test/lecturas_ordenes.http` (nuevo): casos del change y de los casos PDF C-15 y C-17 (catálogo de estados por posición y filtro por un estado que el contrato no declara → 422), sobre el estado conocido de `python seed.py`.

Fuera de alcance: filtros adicionales (por mecánico, vehículo, fechas), búsqueda de texto y orden configurable; el nombre o el correo del mecánico (se expone `mecanico_id`); `estado` en `/mis-ordenes`; cambios a `get_detalle`, `armar_detalle`, el alta o las transiciones; `GET /estados-orden` (ya existe desde C-13: sólo se usa en el caso C-17); README e integración de todos los `.http` (C-16); migraciones (no se crea ninguna; los índices existentes alcanzan).

## Capabilities

### New Capabilities
(ninguna)

### Modified Capabilities
- `work-orders`: se le **agregan** los requisitos de lectura que su propósito ya anuncia («C-15 agrega las lecturas»): listado del personal con filtro por estado, forma del resumen, detalle para el personal o el dueño con 404 antes que 403, órdenes propias del usuario autenticado, número fijo de consultas y lecturas sin escrituras ni bloqueos. No cambia ningún requisito del alta ni de las transiciones.

(`list-pagination`, `access-control`, `order-states` y `api-contracts` se usan tal como están: el envoltorio, el 422 de página, el orden 401 → 403 → 422 y el catálogo ya están especificados.)

## Impact

- **Código modificado** (sólo agregados al final de cada archivo; no se reescribe nada de C-13/C-14): `app/modules/ordenes/schemas.py` (un contrato de salida), `app/modules/ordenes/repository.py` (seis métodos de lectura en `OrdenTrabajoRepository`), `app/modules/ordenes/service.py` (constantes, un armado y tres lecturas), `app/modules/ordenes/router.py` (una dependencia de rol, un router `/mis-ordenes` y tres rutas), `main.py` (un import y una línea de montaje).
- **Archivos nuevos**: `test/lecturas_ordenes.http`, `test/evidencia_c15.txt`.
- **Sin cambios**: `app/core/*`, `app/modules/ordenes/unit_of_work.py` (ya tiene `ordenes` y `asignaciones`), modelos, migraciones, `seed.py`, los demás módulos y `.http`.
- **Dependencias**: ninguna nueva. Requiere C-13 y C-14 en `main` (cumplido, PR #16).
- **Downstream**: C-16 integra `test/lecturas_ordenes.http` y pone `test/evidencia_c15.txt` en el README (evidencia C-15).
- **Governance**: MEDIO (lógica de lectura y permiso por relación, sin escrituras). Propone Nico, implementa Lauti con modelos chicos: `tasks.md` fija archivo, firma, regla y casos de cada tarea. Los supuestos S-01…S-17 de `design.md` están **confirmados por el usuario el 2026-10-31**.
