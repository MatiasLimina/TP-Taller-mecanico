# Proposal — C-14 ordenes-transiciones

## Why

Con C-13 una orden nace `PENDIENTE` y no puede avanzar: nadie la inicia, la termina ni la cancela, y el stock nunca baja por una orden. Es el núcleo transaccional del TP (20 % de Repos/UoW): terminar descuenta el stock de cada ítem por el punto único de escritura (C-11), registra los movimientos y el historial, y todo se revierte junto si un repuesto no alcanza (RN13). Faltan además las evidencias de los casos PDF C-11 («terminar la orden 2, que pide más bujías que las que hay: 409 y todo queda como estaba»), C-12 («reponer y terminar: 200, baja el stock, aparecen los movimientos y el historial, el aviso sale en el registro después de la respuesta») y C-13 («el dueño cancela su orden pendiente: 200; una ajena, 403; una terminada, 409»). Ahora porque C-12 (reponer) y C-13 (alta, `OrdenesUoW`) ya están implementados y es el último change del camino crítico antes de C-16.

## What Changes

- `POST /ordenes/{id}/iniciar` (rol MECANICO vigente, con `requiere_rol`): `PENDIENTE → EN_REPARACION`; el actor queda como `mecanico_id`; cualquier otro estado → 409 (una orden ya iniciada no se reasigna). Sin cuerpo.
- `POST /ordenes/{id}/terminar` (el mecánico asignado con rol MECANICO vigente, o un ADMIN; **sin** `requiere_rol`): en **un** Unit of Work bloquea la orden primero, decide el permiso (403) y después el estado (`EN_REPARACION`, si no 409); descuenta el stock de cada ítem con `aplicar_movimientos_stock(…, incluir_bajas=True)` (movimiento negativo con `orden_id`, motivo `Orden #<id> terminada` y el actor), pasa a `TERMINADA` y agrega la línea de historial. Si un repuesto no alcanza → 409 `Stock insuficiente para el repuesto <código>: hay <N> y se necesitan <M>` y no queda **ninguna** escritura (RN13). Tras el commit, y sólo entonces, se agenda con `BackgroundTasks` el aviso simulado al cliente (`await asyncio.sleep(0.5)` + una línea en el registro), que corre después de enviar la respuesta.
- `POST /ordenes/{id}/cancelar` (RECEPCION o ADMIN vigentes, o el dueño del vehículo; **sin** `requiere_rol`): primero quién es y qué relación tiene con la orden (403), después el estado: sólo `PENDIENTE → CANCELADA`, otro estado → 409 (RN12). Sin cuerpo.
- Las tres transiciones: orden inexistente → 404 (antes que el permiso); id fuera de rango → 422; la regla de estados la guía el catálogo (`es_final`: un estado final no admite cambios; un estado destino ausente del catálogo → 409 propio) más la tabla de orígenes del servicio; cada transición agrega una línea a `historial_estado_orden` (sólo agregado) con el actor; la respuesta es 200 con el mismo detalle que el alta (`OrdenDetalleSalida`), releído después de escribir.
- Contrato de bloqueos: la orden con `FOR UPDATE` es siempre la primera fila bloqueada; después, sólo en terminar, los repuestos en orden ascendente de id (dentro del punto único). Nunca se bloquea un vehículo. Con el orden global de C-13 (orden → vehículo → repuestos) el sistema queda sin interbloqueos frente a otra transición de la misma orden, otras terminaciones, el alta (C-13), la reposición (C-12), el PATCH y la baja de repuestos (C-11) y la baja de vehículos (C-10).
- Agregados al módulo `ordenes` (sin tocar el alta): `OrdenTrabajoRepository.get_para_actualizar` y `get_usuario_dueno`, `ItemOrdenRepository.listar_de_orden`, y el `AsignacionRolRepository` de usuarios en el `OrdenesUoW` (roles vigentes leídos en la misma transacción, RN04).
- `test/transiciones.http` (nuevo): casos del change y PDF C-11, C-12 y C-13 con estado conocido propio.

Fuera de alcance: lecturas de órdenes (`GET /ordenes`, `/ordenes/{id}`, `/mis-ordenes`: C-15); editar una orden o reasignar el mecánico; reabrir o revertir una orden terminada; reintentos o colas para el aviso (cap. 8, DD-10); `seed.py` (C-06); `test/solo_agregado.sql` (evidencia del caso PDF C-14, ya existe desde C-04 y la integra C-16); migraciones (no se crea ninguna).

## Capabilities

### New Capabilities
(ninguna)

### Modified Capabilities
- `work-orders`: capacidad creada por C-13 (alta de orden; se sincroniza a `openspec/specs/` al archivar C-13, que debe ocurrir antes que el de este change). Se le **agregan** los requisitos de las transiciones: iniciar, terminar con descuento atómico de stock y aviso tras el commit, cancelar con permiso por relación antes que estado, reglas de estado guiadas por el catálogo, historial por transición, forma de la respuesta y serialización sin interbloqueos. No cambia ningún requisito del alta.

(`access-control`, `order-states`, `stock-movements`, `append-only-history`, `unit-of-work`, `data-repositories`, `error-translation` y `api-contracts` se usan tal como están: el punto único ya define el movimiento con signo, el rechazo atómico y la concurrencia de stock.)

## Impact

- **Código modificado** (todo en el módulo de Nico, sólo agregados): `app/modules/ordenes/repository.py` (tres métodos), `app/modules/ordenes/unit_of_work.py` (un atributo), `app/modules/ordenes/service.py` (constantes, tres transiciones, el aviso), `app/modules/ordenes/router.py` (tres rutas en `router_ordenes`).
- **Código nuevo**: `test/transiciones.http`.
- **Sin cambios**: `main.py` (las rutas se declaran en `router_ordenes`, que C-13 ya monta), `app/core/*`, modelos, migraciones, `app/modules/repuestos/*` (se usa `aplicar_movimientos_stock` tal cual), `app/modules/usuarios/*` y `app/modules/clientes/*` (sólo se importan), el alta de C-13.
- **Dependencias**: ninguna nueva. Requiere C-12 y C-13 mergeados en `main` antes del apply (cumplido: C-12 por el PR #13 y C-13 por el PR #12, ambos mergeados y archivados).
- **Downstream**: C-15 (`GET /ordenes/{id}` muestra `mecanico_id` y el historial completo de las transiciones; lee órdenes de vehículos dados de baja); C-16 integra `test/transiciones.http` y la evidencia del caso PDF C-14 (`test/solo_agregado.sql`, entregable de Nico por REPARTO §6).
- **Governance**: CRITICO (stock, permisos por relación y atomicidad). Análisis y aprobación humana explícita antes de escribir código; Mati revisa el propose y el apply (REPARTO §8.3). Los supuestos S-01…S-19 de design.md están **confirmados por el usuario el 2026-10-30**; falta la revisión de Mati del propose.
