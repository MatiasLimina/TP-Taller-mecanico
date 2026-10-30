# Design — C-14 ordenes-transiciones

## Context

Motivación en proposal.md — Why; requisitos en `specs/work-orders` (delta que agrega las transiciones a la capacidad creada por C-13). Estado actual relevante:

- **Modelos (C-03)**: `OrdenTrabajo(id, vehiculo_id, mecanico_id | None, estado: str FK a estado_orden.codigo, falla, creada_en, total)`, `ItemOrden(orden_id, repuesto_id, cantidad, precio_unitario)`, `HistorialEstadoOrden(orden_id, desde_estado | None, hasta_estado, usuario_id NOT NULL, cuando)`, `EstadoOrden(codigo PK, descripcion, posicion, es_final)`, `CodigoEstado` (StrEnum, «vocabulario del servicio»). Relaciones `lazy="raise"`. FK `fk_orden_trabajo_estado_estado_orden`, `fk_orden_trabajo_mecanico_id_usuario`, `fk_historial_estado_orden_{desde,hasta}_estado_estado_orden`, `fk_historial_estado_orden_usuario_id_usuario`; `historial_estado_orden` y `movimiento_stock` con disparador de sólo agregado (C-04: `UPDATE`/`DELETE` → `P0001`; `TRUNCATE` no lo dispara). Las FK al catálogo son `NO ACTION`: un estado referenciado no se puede borrar. Sin migraciones nuevas (REPARTO §7.6).
- **C-13 (PR #12, `feat/C-13-ordenes-alta-estados`; se lee con `git show`)**: `ordenes/{schemas,repository,unit_of_work,service,router}.py`. `OrdenesUoW` compone `estados`, `ordenes`, `items`, `historial`, `vehiculos` (C-10), `repuestos` y `movimientos` (C-11): ya cumple `ConStock`. `OrdenTrabajoRepository.get_detalle(id)` (3 SELECT fijos, `populate_existing`) + `service.armar_detalle(orden) -> OrdenDetalleSalida`; `EstadoOrdenRepository.listar()` (por `posicion`) y `get_por_codigo()`; `RESTRICCIONES_DE_ESTADO` (las dos FK al catálogo que puede violar una escritura de estado) y `CENTAVO`. `router_ordenes = APIRouter(prefix="/ordenes")` **sin** rol de router, ya montado en `main.py`. Orden global de bloqueo (C-13 D6): 1) una orden existente (`FOR UPDATE`, sólo C-14) → 2) vehículo (`FOR UPDATE`: alta C-13, baja C-10) → 3) repuestos por id ascendente (`FOR SHARE` del alta, `FOR UPDATE` de PATCH/DELETE, `UPDATE` condicional del punto único). Su nota para C-14 es contrato de este design.
- **C-11 (archivado) — punto único**: `aplicar_movimientos_stock(uow: ConStock, movimientos, *, usuario_id, incluir_bajas=False) -> dict[int, int]`, `MovimientoPedido(repuesto_id, cantidad, motivo, orden_id=None)`, `StockInsuficiente(Conflicto)` (409 `Stock insuficiente para el repuesto {codigo}: hay {disponible} y se necesitan {requerido}`). Por pedido, en orden ascendente de `repuesto_id`: `UPDATE repuesto SET stock = stock + :delta WHERE id = :id [AND borrado_en IS NULL] AND stock + :delta >= 0 RETURNING stock` (`synchronize_session=False`) + `INSERT movimiento_stock` (un `flush` por movimiento). Si no alcanza, `leer_stock` arma el 409; con `incluir_bajas=True` el 404 sólo ocurriría con un repuesto físicamente inexistente (imposible: FK). `_validar_pedidos` lanza `ValueError` con una lista vacía. Nota para C-14: bloquear la orden antes, no capturar `StockInsuficiente` dentro del bloque, `BackgroundTasks` después del bloque.
- **C-12 (implementado y archivado en `feat/C-12-repuestos-stock-precios`, sin mergear)**: `POST /repuestos/{id}/reponer` (ADMIN, `{"cantidad": n}`, 200 `RepuestoSalida`) por el punto único, y `GET /repuestos/{id}/movimientos` (lista cronológica `{id, cantidad, motivo, orden_id, usuario_id, cuando}`). Su nota: el caso PDF C-12 completo (reponer y terminar) lo cierra C-14.
- **C-10 (archivado)**: dueño de un vehículo = `vehiculo.cliente_id → cliente.usuario_id` (UNIQUE, nulo si la ficha no tiene usuario). `DELETE /vehiculos/{id}` toma el vehículo `FOR UPDATE` y lee las órdenes abiertas (join a `es_final`) **sin** bloquearlas.
- **Usuarios / core**: `requiere_rol(*roles)` consulta los roles vigentes en la base (RN04, sin comodín de ADMIN) dentro de un `UsuariosUoW` propio; `UsuarioActualDep` (`app/core/dependencies.py`) da `UsuarioActual(id, …)`; `AsignacionRolRepository.roles_vigentes(usuario_id, ahora) -> list[str]` (sólo la columna `rol`). `exigir_password_al_dia` se aplica una vez en `rutas_protegidas`. `IdRuta = Annotated[int, Path(ge=1, le=INT4_MAX)]`. Errores `NoEncontrado`/`SinPermiso`/`Conflicto`. Sesión por petición con `expire_on_commit=False`; READ COMMITTED.
- **Registro del servidor**: el proyecto no configura `logging`; los módulos usan `logging.getLogger(__name__)` y sólo se ve lo de nivel WARNING (por el `lastResort` de Python). uvicorn configura sus loggers `uvicorn`/`uvicorn.error` en INFO con salida a consola (S-13).
- **Consigna**: «al terminar una orden se agenda con BackgroundTasks el aviso al cliente, simulado con `await asyncio.sleep(0.5)` y un mensaje en el registro, que corre después de enviar la respuesta y sólo si la operación se confirmó». Matriz validada (KB 03): iniciar MECANICO → 200/404/409; terminar «mecánico asignado, o ADMIN» → 200/403/404/409; cancelar «RECEPCION, ADMIN o el dueño» → 200/403/404/409, sin `requiere_rol`. Toda ruta protegida da además 401 y 403 (cambio pendiente); `IdRuta` da 422 como en los demás módulos.

## Goals / Non-Goals

**Goals:**

- Tres transiciones en un solo servicio con un contrato común (bloquear → permiso → estado → escribir → releer), sin duplicar reglas y sin reabrir decisiones de C-11/C-13.
- Terminar todo o nada: stock, movimientos, estado e historial en un Unit of Work; el aviso sólo después del commit.
- Contrato de bloqueos explícito que mantiene el sistema completo libre de interbloqueos.

**Non-Goals:**

- Cambiar `aplicar_movimientos_stock`, `RepuestoRepository`, el alta de C-13, `app/core/*` o `usuarios`.
- Lecturas de órdenes (C-15) y su permiso; reasignar mecánico; reabrir órdenes; reintentos del aviso (DD-10).
- Número constante de consultas en terminar: el punto único hace un `UPDATE` + un `INSERT` por ítem por contrato (C-11 D4); se fija y se mide la fórmula (D8).

## Decisions

### D1 — Archivos

| Archivo | Cambio (sólo agregados) |
|---------|-------------------------|
| `app/modules/ordenes/repository.py` | `OrdenTrabajoRepository.get_para_actualizar`, `OrdenTrabajoRepository.get_usuario_dueno`, `ItemOrdenRepository.listar_de_orden`; import de `Cliente` |
| `app/modules/ordenes/unit_of_work.py` | atributo `self.asignaciones = AsignacionRolRepository(session)` y su import (S-03) |
| `app/modules/ordenes/service.py` | constantes y mensajes (D7), `_bloquear_orden`, `_roles_vigentes`, `_exigir_transicion`, `_aplicar_transicion`, `iniciar`, `terminar`, `cancelar`, `avisar_orden_terminada`; docstring del módulo ampliado |
| `app/modules/ordenes/router.py` | `iniciar_orden = requiere_rol(Rol.MECANICO)`, `IniciarOrdenDep`, tres `@router_ordenes.post(...)`; docstring ampliado |
| `test/transiciones.http` (nuevo) | casos del change (D9) |

`main.py` no cambia: las rutas nuevas se declaran en `router_ordenes` antes de que `main.py` lo importe e incluya (mismo criterio que C-12 con `router_admin_repuestos`). `schemas.py` no cambia: las transiciones no tienen cuerpo (S-02) y responden `OrdenDetalleSalida` (S-01).

### D2 — Rutas, permisos y orden de rechazos (S-02, S-04, S-05, S-07, S-08)

```python
# router.py
iniciar_orden = requiere_rol(Rol.MECANICO)                     # UNA función, como alta_orden
IniciarOrdenDep = Annotated[UsuarioActual, Depends(iniciar_orden)]

@router_ordenes.post("/{orden_id}/iniciar", status_code=200)
async def iniciar(orden_id: IdRuta, actual: IniciarOrdenDep, uow: OrdenesUoWDep) -> OrdenDetalleSalida:
    return await service.iniciar(uow, orden_id, actual.id)

@router_ordenes.post("/{orden_id}/terminar", status_code=200)
async def terminar(orden_id: IdRuta, actual: UsuarioActualDep, uow: OrdenesUoWDep,
                   tareas: BackgroundTasks) -> OrdenDetalleSalida:
    salida = await service.terminar(uow, orden_id, actual.id)   # al volver, YA confirmó
    tareas.add_task(service.avisar_orden_terminada, salida.id, salida.patente)   # D6
    return salida

@router_ordenes.post("/{orden_id}/cancelar", status_code=200)
async def cancelar(orden_id: IdRuta, actual: UsuarioActualDep, uow: OrdenesUoWDep) -> OrdenDetalleSalida:
    return await service.cancelar(uow, orden_id, actual.id)
```

| Ruta | Orden de rechazos |
|------|-------------------|
| iniciar | 401 → 403 cambio → 403 rol (sin MECANICO; ADMIN no es comodín) → 422 id → 404 → 409 |
| terminar | 401 → 403 cambio → 422 id → 404 → 403 (ni asignado con MECANICO vigente, ni ADMIN) → 409 (estado, luego stock) |
| cancelar | 401 → 403 cambio → 422 id → 404 → 403 (ni RECEPCION/ADMIN vigente, ni dueño) → 409 |

- Terminar y cancelar **no** llevan `requiere_rol` (consigna; nota de C-13): el permiso depende de la relación con la orden (mecánico asignado, dueño), que sólo se conoce después de leerla. El servicio lo decide con los roles vigentes leídos en la base en la misma transacción (S-03), no con los del token (RN04).
- **404 antes que 403** (S-07): la orden se busca primero; si no existe, 404 a cualquier usuario con sesión. Si existe y el actor no tiene relación, 403 (PDF C-13: «una orden ajena da 403»). Es el mismo criterio que la matriz da a `GET /ordenes/{id}` (200/403/404, C-15).
- **Sin cuerpo** (S-02): ningún handler declara cuerpo; FastAPI no lee uno si llega y el OpenAPI no declara `requestBody`. Estado destino, mecánico y actor los decide el servidor.
- El servicio recibe `actual.id`, nunca `UsuarioActual` ni `BackgroundTasks` (no conoce HTTP).

### D3 — Contrato de bloqueos y concurrencia (S-17)

Toda transición abre **un** `async with uow` y su **primera** sentencia es `SELECT … FROM orden_trabajo WHERE id = :id FOR UPDATE` (`get_para_actualizar`, paso 1 del orden global de C-13 D6). Después: lecturas sin bloqueo (roles, catálogo, ítems, dueño) y, sólo en terminar, el punto único, que toma los repuestos con su `UPDATE` en orden ascendente de id (paso 3). C-14 **nunca** bloquea un vehículo (paso 2) ni lee un repuesto con bloqueo antes de la orden. Las escrituras de la propia transacción toman `FOR KEY SHARE` por FK sobre filas que ya tiene (orden, repuestos) o que nadie bloquea en modo exclusivo (`estado_orden`, `usuario`; el `UPDATE` de contraseña toma `FOR NO KEY UPDATE`, compatible).

**Por qué no hay ciclos de espera** (READ COMMITTED; quien espera reevalúa la fila al seguir):

| Primero | Después | Resultado |
|---------|---------|-----------|
| Transición sobre la orden X | Otra transición sobre X | La segunda espera en el paso 1 **sin tener nada bloqueado**; al seguir, `populate_existing` le da el estado confirmado → 409 (o 200 si la primera falló y revirtió) |
| Terminar X (orden + repuestos `< r`) | Terminar Y con repuestos compartidos | Órdenes distintas no se esperan; en repuestos ambas avanzan por id ascendente: quien espera la fila `r` sólo tiene filas `< r`, así que el otro nunca espera algo que el primero tenga |
| Terminar | Alta (C-13: vehículo → repuestos `FOR SHARE` ascendentes) | El `FOR SHARE` espera al `UPDATE` (o al revés); ambos ascendentes en la tabla 3 y el alta nunca pide una orden existente → sin ciclo |
| Terminar | Reponer (C-12), PATCH o DELETE de repuesto (C-11) | Ellos bloquean **una** sola fila de repuesto y no esperan nada más → no pueden cerrar un ciclo. Baja confirmada antes: el `UPDATE` con `incluir_bajas=True` descuenta igual (S-11). PATCH primero: el precio no afecta a la orden (se copió al crearla) |
| Terminar / cancelar | Baja de vehículo (C-10) | No comparten filas bloqueadas (C-14 no toca el vehículo; la baja no bloquea órdenes). La baja lee las órdenes confirmadas: con una cancelación en curso sigue viendo `PENDIENTE` → 409 conservador |
| Iniciar y cancelar a la vez (misma orden `PENDIENTE`) | — | Serializadas en el paso 1: la segunda ve el estado nuevo → 409 |

- `FOR UPDATE` (no `FOR NO KEY UPDATE`): es lo acordado en C-13 D6; nadie toma `FOR KEY SHARE` sobre una orden existente salvo la propia transacción (los `INSERT` de historial y movimientos). Si C-15 o un futuro change insertara filas hijas de una orden existente desde otra transacción, deberá esperar a la transición: correcto.
- *Alternativa descartada*: validar permiso y estado con una lectura sin bloqueo y bloquear después — dos lecturas, y el estado validado podría cambiar antes del bloqueo (doble terminación con doble descuento).
- *Alternativa descartada*: `SERIALIZABLE` o reintentos — el UoW no reintenta; un fallo de serialización sería 500.
- *Alternativa descartada*: bloquear los repuestos con `SELECT … FOR UPDATE` antes del punto único — duplica el bloqueo que el `UPDATE` condicional ya toma (C-11 D4) y agrega N consultas.

### D4 — Repositorios y Unit of Work (S-03, S-08, S-18)

```python
# ordenes/repository.py — sólo se agregan estos tres métodos
class OrdenTrabajoRepository(BaseRepository[OrdenTrabajo]):
    async def get_para_actualizar(self, id: int) -> OrdenTrabajo | None:
        """Orden bloqueada con FOR UPDATE (paso 1 del orden global, C-13 D6). Sin relaciones."""
        consulta = (self._consulta_base().where(col(OrdenTrabajo.id) == id)
                    .with_for_update().execution_options(populate_existing=True))
        return (await self.session.exec(consulta)).first()

    async def get_usuario_dueno(self, orden_id: int) -> int | None:
        """`cliente.usuario_id` del vehículo de la orden (también si el vehículo está dado de baja,
        RN16); None si la ficha no tiene usuario. Columna suelta, sin bloqueo ni identity map."""
        consulta = (select(col(Cliente.usuario_id))
                    .join(Vehiculo, col(Vehiculo.cliente_id) == col(Cliente.id))
                    .join(OrdenTrabajo, col(OrdenTrabajo.vehiculo_id) == col(Vehiculo.id))
                    .where(col(OrdenTrabajo.id) == orden_id))
        return (await self.session.exec(consulta)).first()

class ItemOrdenRepository(BaseRepository[ItemOrden]):
    async def listar_de_orden(self, orden_id: int) -> list[ItemOrden]:
        """Ítems de la orden en orden de id, sin relaciones (usa uq_item_orden_orden_id_repuesto_id)."""
        consulta = (self._consulta_base().where(col(ItemOrden.orden_id) == orden_id)
                    .order_by(col(ItemOrden.id)))
        return list((await self.session.exec(consulta)).all())

# ordenes/unit_of_work.py — sólo se agrega
        self.asignaciones = AsignacionRolRepository(session)   # de usuarios: roles vigentes (RN04), S-03
```

- `populate_existing` en `get_para_actualizar`: si la orden ya estuviera en el identity map (no ocurre hoy, pero sí en el script con UoW inyectados), la fila bloqueada pisa los valores viejos; el estado que se valida es siempre el confirmado.
- `get_usuario_dueno`: tres búsquedas por PK, parámetros ligados; no filtra `vehiculo.borrado_en` (S-08). Vive en `ordenes` porque la pregunta es de la orden (precedente C-10 S-01: la consulta va donde se hace la pregunta, sin tocar el archivo del otro módulo).
- `listar_de_orden`: una consulta para cualquier cantidad de ítems; los ítems no se bloquean (no hay ruta que los edite y la orden padre está bloqueada).
- `AsignacionRolRepository` se importa de `app.modules.usuarios.repository` sin modificarlo; se usa sólo `roles_vigentes`. Los demás repositorios del UoW no cambian.

### D5 — Servicio de transiciones (S-04, S-06, S-09, S-10, S-14)

```python
ORIGEN: Mapping[CodigoEstado, CodigoEstado] = MappingProxyType({
    CodigoEstado.EN_REPARACION: CodigoEstado.PENDIENTE,      # iniciar
    CodigoEstado.TERMINADA: CodigoEstado.EN_REPARACION,      # terminar
    CodigoEstado.CANCELADA: CodigoEstado.PENDIENTE,          # cancelar (RN11/RN12)
})
ACCION = MappingProxyType({CodigoEstado.EN_REPARACION: "iniciar", CodigoEstado.TERMINADA: "terminar",
                           CodigoEstado.CANCELADA: "cancelar"})
ROLES_QUE_CANCELAN = frozenset({Rol.RECEPCION.value, Rol.ADMIN.value})
MOTIVO_ORDEN_TERMINADA = "Orden #{orden_id} terminada"

async def _bloquear_orden(uow: OrdenesUoW, orden_id: int) -> OrdenTrabajo:
    orden = await uow.ordenes.get_para_actualizar(orden_id)       # SIEMPRE la primera fila bloqueada
    if orden is None:
        raise NoEncontrado(MENSAJE_ORDEN_INEXISTENTE)
    return orden

async def _roles_vigentes(uow: OrdenesUoW, usuario_id: int) -> frozenset[str]:
    return frozenset(await uow.asignaciones.roles_vigentes(usuario_id, datetime.now(UTC)))

async def _exigir_transicion(uow: OrdenesUoW, orden: OrdenTrabajo, destino: CodigoEstado) -> None:
    """Reglas de estado guiadas por el catálogo (una consulta) + la tabla ORIGEN."""
    catalogo = {e.codigo: e for e in await uow.estados.listar()}
    actual = catalogo.get(orden.estado)            # existe siempre: FK NO ACTION
    if actual is not None and actual.es_final:
        raise Conflicto(MENSAJE_ESTADO_FINAL.format(orden_id=orden.id, estado=orden.estado))
    origen = ORIGEN[destino]
    if orden.estado != origen.value:
        raise Conflicto(MENSAJE_TRANSICION_INVALIDA.format(
            accion=ACCION[destino], orden_id=orden.id, estado=orden.estado, origen=origen.value))
    if destino.value not in catalogo:
        raise Conflicto(MENSAJE_CATALOGO_SIN_ESTADO.format(estado=destino.value))

async def _aplicar_transicion(uow: OrdenesUoW, orden: OrdenTrabajo, destino: CodigoEstado,
                              usuario_id: int, *, mecanico_id: int | None = None) -> OrdenDetalleSalida:
    assert orden.id is not None
    desde = orden.estado
    cambios: dict[str, object] = {"estado": destino.value}
    if mecanico_id is not None:
        cambios["mecanico_id"] = mecanico_id                       # sólo iniciar
    await uow.ordenes.update(orden, cambios)                        # UPDATE (flush)
    await uow.historial.add(HistorialEstadoOrden(                   # sólo agregado (RN15)
        orden_id=orden.id, desde_estado=desde, hasta_estado=destino.value,
        usuario_id=usuario_id, cuando=datetime.now(UTC)))
    detalle = await uow.ordenes.get_detalle(orden.id)               # relee TODO (populate_existing)
    assert detalle is not None
    return armar_detalle(detalle)                                   # dentro del bloque

async def iniciar(uow: OrdenesUoW, orden_id: int, usuario_id: int) -> OrdenDetalleSalida:
    destino = CodigoEstado.EN_REPARACION
    try:
        async with uow:
            orden = await _bloquear_orden(uow, orden_id)                       # 404
            await _exigir_transicion(uow, orden, destino)                      # 409 (rol: router)
            salida = await _aplicar_transicion(uow, orden, destino, usuario_id, mecanico_id=usuario_id)
    except IntegrityError as exc:
        _traducir_catalogo(exc, destino)                                       # S-10
        raise
    return salida

async def cancelar(uow: OrdenesUoW, orden_id: int, usuario_id: int) -> OrdenDetalleSalida:
    destino = CodigoEstado.CANCELADA
    try:
        async with uow:
            orden = await _bloquear_orden(uow, orden_id)                       # 404
            roles = await _roles_vigentes(uow, usuario_id)
            if roles.isdisjoint(ROLES_QUE_CANCELAN):                           # personal: sin más consultas
                if await uow.ordenes.get_usuario_dueno(orden_id) != usuario_id:
                    raise SinPermiso(MENSAJE_SIN_PERMISO_CANCELAR)             # 403 antes que 409 (RN12)
            await _exigir_transicion(uow, orden, destino)                      # 409
            salida = await _aplicar_transicion(uow, orden, destino, usuario_id)   # mecanico_id sigue nulo
    except IntegrityError as exc:
        _traducir_catalogo(exc, destino)
        raise
    return salida
```

- `_traducir_catalogo(exc, destino)`: si `restriccion_violada(exc) in RESTRICCIONES_DE_ESTADO` (las de C-13), `raise Conflicto(MENSAJE_CATALOGO_SIN_ESTADO.format(estado=destino.value)) from None`. Sólo ocurre si alguien saca el estado destino del catálogo por `psql` entre la lectura y el `UPDATE`; se traduce **fuera** del bloque con un valor que no es atributo de una entidad (regla de `app/core/unit_of_work.py`).
- **Catálogo** (S-10): `es_final` del estado **actual** decide «no admite más cambios» antes de mirar la tabla, así el catálogo manda (si el seed marcara otro estado como final, se respeta); la tabla `ORIGEN` fija el único origen de cada destino (RN11); un destino ausente del catálogo da 409 propio antes de escribir (RN19). Una sola consulta (`listar()`, 4 filas).
- **Historial** (S-14): `desde_estado` = estado leído bajo el bloqueo; `usuario_id` = actor; `cuando` = `datetime.now(UTC)`. Nunca `update`/`delete` de líneas.
- **Mecánico** (S-05): sólo iniciar fija `mecanico_id` (el actor); terminar y cancelar no lo tocan (una orden terminada por un ADMIN conserva su mecánico; una cancelada queda sin mecánico).
- **Respuesta** (S-01): se relee con `get_detalle` (populate_existing) después de escribir y se arma dentro del bloque: misma forma que el alta, estado y historial nuevos, ningún valor de entidades cargadas antes de escribir.

### D6 — `terminar` y el aviso (S-11, S-12, S-13)

```python
async def terminar(uow: OrdenesUoW, orden_id: int, usuario_id: int) -> OrdenDetalleSalida:
    destino = CodigoEstado.TERMINADA
    try:
        async with uow:
            orden = await _bloquear_orden(uow, orden_id)                       # paso 1 — 404
            roles = await _roles_vigentes(uow, usuario_id)
            asignado = orden.mecanico_id == usuario_id and Rol.MECANICO.value in roles
            if not (asignado or Rol.ADMIN.value in roles):
                raise SinPermiso(MENSAJE_SIN_PERMISO_TERMINAR)                 # 403 antes que 409
            await _exigir_transicion(uow, orden, destino)                      # 409 estado
            assert orden.id is not None
            items = await uow.items.listar_de_orden(orden.id)
            if items:                                     # siempre >= 1 (C-13); defensivo ante psql
                await aplicar_movimientos_stock(                               # paso 3 — PUNTO ÚNICO
                    uow,
                    [MovimientoPedido(i.repuesto_id, -i.cantidad,
                                      MOTIVO_ORDEN_TERMINADA.format(orden_id=orden.id), orden_id=orden.id)
                     for i in items],
                    usuario_id=usuario_id, incluir_bajas=True)                  # StockInsuficiente NO se captura
            salida = await _aplicar_transicion(uow, orden, destino, usuario_id)   # estado + historial + relectura
    except IntegrityError as exc:
        _traducir_catalogo(exc, destino)
        raise
    return salida                                                              # confirmado

DEMORA_AVISO_SEGUNDOS = 0.5
logger_avisos = logging.getLogger("uvicorn.error.avisos")                      # S-13

async def avisar_orden_terminada(orden_id: int, patente: str) -> None:
    """Aviso SIMULADO al cliente (DD-10): corre por BackgroundTasks, después de la respuesta."""
    await asyncio.sleep(DEMORA_AVISO_SEGUNDOS)                                 # nunca time.sleep
    logger_avisos.info(MENSAJE_AVISO.format(orden_id=orden_id, patente=patente))
```

- **Atomicidad (RN13)**: stock, movimientos, estado e historial se escriben en la misma transacción. `StockInsuficiente` (o cualquier excepción) sale del bloque y el UoW revierte **todo**, también los `UPDATE` de los ítems anteriores (con ids menores) ya aplicados. El estado se cambia **después** del descuento (Flujo 5), aunque el orden no cambia el resultado.
- **409 de stock**: el mensaje es el de `StockInsuficiente`, sin captura ni traducción (`requerido` = cantidad del ítem): PDF C-11 → `Stock insuficiente para el repuesto <código>: hay 2 y se necesitan 4`. Como el punto único aplica por id ascendente, el repuesto informado es el de menor id que no alcanza.
- **Movimientos** (S-12): uno por ítem, `cantidad = -item.cantidad`, `orden_id`, `usuario_id` = actor (el mecánico o el ADMIN que terminó), motivo `Orden #<id> terminada` (texto de la nota de C-11). `incluir_bajas=True` (C-11 S-11): un repuesto dado de baja después del alta se descuenta igual (RN16 conserva sus datos).
- **Aviso después del commit**: el servicio no conoce `BackgroundTasks`; el router agenda la tarea **después** de que `service.terminar` vuelve, es decir, después de salir del bloque (commit). Si el servicio lanza (403/404/409/422 o un error inesperado), la línea `add_task` no se ejecuta: sin aviso. Starlette corre la tarea después de enviar el cuerpo de la respuesta. Recibe valores (`salida.id`, `salida.patente`), nunca entidades ni la sesión (ya cerrada cuando corre). El router la referencia como `service.avisar_orden_terminada` (atributo del módulo) para que el script pueda envolverla (D9-f).
- *Alternativa descartada*: pasar `BackgroundTasks` al servicio y agendar al final del bloque — el servicio conocería FastAPI y la tarea quedaría agendada antes del commit (si el commit fallara, el aviso saldría igual).
- *Alternativa descartada*: capturar `StockInsuficiente` dentro del bloque para un mensaje propio — dejaría la transacción viva con escrituras parciales; el mensaje de C-11 ya es el del PDF.

### D7 — Mensajes (S-15)

| Situación | Código | `detail` |
|-----------|--------|----------|
| Orden inexistente | 404 | `La orden no existe` |
| Terminar sin ser el asignado con MECANICO vigente ni ADMIN | 403 | `Sólo el mecánico asignado o un administrador puede terminar la orden` |
| Cancelar sin RECEPCION/ADMIN vigente ni ser el dueño | 403 | `Sólo la recepción, un administrador o el dueño del vehículo puede cancelar la orden` |
| Iniciar sin MECANICO; sin sesión; cambio pendiente | 403 / 401 / 403 | mensajes de C-08 (`No tiene permiso para realizar esta operación`, …) |
| Estado actual final | 409 | `La orden <id> está <ESTADO>, un estado final: no admite más cambios` |
| Estado actual distinto del origen | 409 | `No se puede <iniciar\|terminar\|cancelar> la orden <id>: está <ESTADO> y debe estar <ORIGEN>` |
| Estado destino fuera del catálogo (también la carrera de la FK) | 409 | `El catálogo de estados no tiene el estado <ESTADO>` |
| Stock insuficiente al terminar | 409 | `Stock insuficiente para el repuesto <código>: hay <N> y se necesitan <M>` (C-11) |
| Id fuera de rango o no entero | 422 | validación de Pydantic sobre `["path", "orden_id"]` |

Constantes en `service.py`: `MENSAJE_ORDEN_INEXISTENTE`, `MENSAJE_SIN_PERMISO_TERMINAR`, `MENSAJE_SIN_PERMISO_CANCELAR`, `MENSAJE_ESTADO_FINAL` (`{orden_id}`, `{estado}`), `MENSAJE_TRANSICION_INVALIDA` (`{accion}`, `{orden_id}`, `{estado}`, `{origen}`), `MENSAJE_CATALOGO_SIN_ESTADO` (`{estado}`), `MENSAJE_AVISO` = `Aviso simulado al cliente: la orden #{orden_id} del vehículo {patente} está terminada` (sin nombre, correo ni teléfono en el registro).

### D8 — Consultas por operación (S-18)

Sentencias del bloque del servicio (además de las de sesión: `autenticar` y, en iniciar, la de `requiere_rol`):

| Operación | Sentencias |
|-----------|-----------|
| iniciar | `FOR UPDATE` 1 + catálogo 1 + `UPDATE orden_trabajo` 1 + `INSERT historial` 1 + detalle 3 = **7** |
| cancelar (personal) | 1 + roles 1 + catálogo 1 + `UPDATE` 1 + `INSERT` 1 + detalle 3 = **8**; (dueño) + dueño 1 = **9** |
| terminar (N ítems) | 1 + roles 1 + catálogo 1 + ítems 1 + N × (`UPDATE repuesto` + `INSERT movimiento_stock`) + `UPDATE` 1 + `INSERT` 1 + detalle 3 = **9 + 2N** |

Los ids viajan siempre como parámetros ligados. La primera sentencia del bloque es el `SELECT … FOR UPDATE` de `orden_trabajo`; ninguna sentencia de C-14 lleva `FOR` sobre `vehiculo`; los `UPDATE repuesto` salen en orden ascendente de id. Índices usados: PK de `orden_trabajo`, `vehiculo`, `cliente`, `repuesto`, `estado_orden`; `uq_item_orden_orden_id_repuesto_id`; índice de `asignacion_rol.usuario_id`; `ix_historial_estado_orden_orden_id` (detalle). No se crea ninguno.

### D9 — Verificación sin pytest (Strict TDD adaptado, como C-13 D12)

- **RED**: `test/transiciones.http` completo (tarea 1.1) se corre contra el servidor sin las rutas: preparación (registro, login, repuestos, ficha, vehículos, órdenes; requiere C-12 y C-13 en `main`) responde como hoy; `POST /ordenes/{id}/iniciar|terminar|cancelar` → 404 (ruta inexistente; también 405 del caso de método). Se anota la línea de base.
- **GREEN**: cada tarea hace pasar los casos numerados que cita. **TRIANGULATE**: cada regla con al menos dos casos (acepta/rechaza o dos motivos). **Safety net**: `test/health.http`, `auth.http`, `sesion.http`, `personal.http`, `clientes.http`, `repuestos.http`, `stock.http`, `ordenes.http` y `test/verificar_security_core.py` antes de tocar el módulo y al final.
- Lo que un `.http` no muestra va en **un** script temporal `$env:TEMP\verificar_c14.py` (no versionado), con `httpx.AsyncClient(transport=ASGITransport(app=…))` dentro de `async with main.lifespan(main.app)`, conexiones `asyncpg` propias para sostener bloqueos y leer lo confirmado, y sesiones de `main.app.state.session_factory` para llamar al servicio con UoW inyectados. Precondición: correr después de `test/transiciones.http`; inicia sesión con sus usuarios (`@transiciones.example.com`) y crea sus propios repuestos `SCRIPT-C14-…`, vehículos `ZTS…` y órdenes (los limpia el encabezado del `.http`). Bloques:
  - (a) **misma orden**: otra conexión toma `SELECT … FROM orden_trabajo WHERE id = X FOR UPDATE`; se lanzan dos `terminar` de X (asignado y ADMIN); a los 0,5 s ambos esperan; `ROLLBACK` → uno 200 y otro 409 de estado final; el stock bajó una sola vez, un movimiento por ítem, una línea `EN_REPARACION → TERMINADA` y un solo aviso. Igual con `iniciar` + `cancelar` simultáneos sobre una `PENDIENTE` → exactamente un 200 y una sola línea nueva; y `terminar` + `cancelar` sobre una `EN_REPARACION` → 200 y 409.
  - (b) **terminar detenido después del descuento**: `service.terminar` con un `OrdenesUoW` cuyo `historial.add` espera un `asyncio.Event` (ya tiene la orden y los repuestos); se lanzan `POST /repuestos/{P}/reponer`, `PATCH /repuestos/{P}` (precio), `DELETE /repuestos/{Q}` y `POST /ordenes` (alta con P y Q en otro vehículo); a los 0,5 s esperan; se libera el evento → la orden confirma; después reponer suma sobre el stock descontado, PATCH 200, DELETE 204, alta 201; invariante de stock.
  - (c) **repuesto bloqueado primero**: otra conexión toma `SELECT … FROM repuesto WHERE id = P FOR UPDATE` (como PATCH/DELETE); `terminar` de una orden con P espera **con la orden bloqueada**; un `cancelar` de la misma orden espera en el paso 1; `COMMIT` → terminar 200, cancelar 409 de estado final. Variante con `UPDATE repuesto SET borrado_en = now()` antes del `COMMIT` → terminar 200 igual (`incluir_bajas=True`).
  - (d) **sin interbloqueos**: 20 repeticiones de, a la vez, dos `terminar` de órdenes distintas con los mismos dos repuestos (ítems en orden inverso en el cuerpo de cada alta), un alta (C-13) con esos repuestos, un `reponer` de uno y un `PATCH` de precio del otro → todas terminan con 200/201/409, nunca `40P01` ni 500; invariante `stock = SUM(movimientos)` al final de cada vuelta.
  - (e) **atomicidad**: orden con tres repuestos donde sólo el segundo por id no alcanza → 409 con su código; antes/después idénticos: `stock` de los tres, filas de `movimiento_stock`, `estado`/`mecanico_id` de la orden y su historial. Variante con falla inyectada: `OrdenesUoW` cuyo `historial.add` lanza `RuntimeError` después del descuento → el error llega sin reemplazo y no queda ningún cambio de stock ni movimiento ni estado.
  - (f) **aviso**: se envuelve la app ASGI para registrar el instante del mensaje `http.response.body` y se reemplaza `service.avisar_orden_terminada` por un envoltorio que, al empezar, anota su instante y lee con su propia conexión `asyncpg` el estado de la orden y sus movimientos; luego llama a la original. Se comprueba: 200 → exactamente una llamada, que empieza **después** del cuerpo de la respuesta y ve la orden `TERMINADA` y sus movimientos (confirmados); 409 de stock, 403, 404 y 409 de estado → ninguna llamada; iniciar y cancelar → ninguna. Con un `logging.Handler` en `uvicorn.error.avisos` (nivel INFO): una sola línea con el texto de D7, ≥ 0,5 s después de que la tarea empezó.
  - (g) **consultas**: listener `before_cursor_execute` sobre `main.app.state.engine.sync_engine`: iniciar 7, cancelar 8 (personal) y 9 (dueño), terminar 11 (N = 1) y 15 (N = 3), más las de sesión/rol; la primera sentencia del bloque es `SELECT … FROM orden_trabajo … FOR UPDATE`; ninguna `FOR` sobre `vehiculo`; los `UPDATE repuesto` en orden ascendente de id; ids como parámetros.
  - (h) **OpenAPI** (`/openapi.json`): las tres rutas `POST /ordenes/{orden_id}/…` sin `requestBody`, con `orden_id` entero 1…2147483647 y respuesta 200 `OrdenDetalleSalida`; ninguna con `password_hash`, `borrado_en` ni `stock`.
  - (i) **invariantes** sobre todas las filas (también las del script): `stock = COALESCE(SUM(cantidad), 0)` por repuesto; cada orden `TERMINADA` tiene un movimiento por ítem con `cantidad = -item.cantidad` y su `orden_id`, y ninguna otra orden tiene movimientos; historial encadenado (`desde_estado` de cada línea = `hasta_estado` de la anterior) y último `hasta_estado` = `estado` de la orden; `mecanico_id` nulo en toda orden que nunca se inició.

## Risks / Trade-offs

- [Prerrequisitos sin mergear] → C-12 vive en su rama y C-13 en el PR #12. Mitigación: el apply empieza sólo con ambos en `main` (REPARTO §8.7); si la revisión de C-13 cambia `get_detalle`, `armar_detalle`, `OrdenesUoW` o `RESTRICCIONES_DE_ESTADO`, se actualiza este design antes de escribir.
- [Un actor sin permiso bloquea la orden un instante] → terminar/cancelar toman el `FOR UPDATE` antes de saber si el actor puede (la relación sale de la orden). Dura lo que tardan dos consultas hasta el 403 y el rollback; se acepta a cambio de decidir permiso y estado sobre la misma versión de la fila.
- [Terminar no tiene consultas constantes] → 9 + 2N por el punto único (un `UPDATE` + un `INSERT` por ítem, C-11 D4); con el tope de 50 ítems, 109 sentencias. Se acepta: la consigna exige consultas fijas en el **detalle** (C-15), no en la terminación.
- [El «hay N» del 409 puede no ser exacto con concurrencia] → `leer_stock` es una lectura aparte del `UPDATE` fallido (nota de C-11). No afecta el rollback; se acepta (S-19).
- [403 revela que la orden existe] → un usuario con sesión distingue «no existe» (404) de «no es tuya» (403). Es lo que pide el PDF C-13 y la matriz (S-07).
- [Aviso perdido o duplicado] → corre en el proceso (DD-10): si el proceso se reinicia, se pierde; sin reintentos. Aceptado por la consigna (cap. 8).
- [Logger acoplado a uvicorn] → `uvicorn.error.avisos` se ve en la consola de uvicorn sin configurar `logging` (S-13); fuera de uvicorn (script) hay que agregarle un handler. Alternativa B lista si se rechaza.
- [Roles leídos sin bloqueo] → una revocación simultánea puede no verse en esa transacción (READ COMMITTED). Mismo criterio que `requiere_rol`; se acepta.
- [Orden sin ítems cargada por `psql`] → `aplicar_movimientos_stock` lanzaría `ValueError` (500): el `if items:` la deja terminar sin movimientos. Nunca ocurre por la API (C-13 exige ≥ 1 ítem).
- [Conflictos de merge con C-15] → C-15 (Lauti) también agrega métodos a `ordenes/repository.py` y rutas a `router.py`. Mitigación: todo es agregado al final de cada clase/archivo; se resuelve conservando ambos.
- [Datos de prueba no borrables] → el historial y los movimientos son de sólo agregado: el encabezado de `test/transiciones.http` usa `TRUNCATE` de órdenes y repuestos (vacía también los de otros `.http` y de desarrollo; mismo criterio que C-11/C-12/C-13).

## Migration Plan

Sin cambios de esquema ni de datos. Despliegue: los cuatro archivos del módulo (sólo agregados) y `test/transiciones.http`; reiniciar uvicorn. Rollback: revertir los cuatro archivos y borrar `test/transiciones.http`; las filas de prueba se limpian con el bloque `psql` de su encabezado o con `python seed.py` (C-06).

## Open Questions / Supuestos

Todos **confirmados por el usuario el 2026-10-30**, cada uno con la recomendación indicada; falta la revisión de Mati del propose (REPARTO §8.3). Cada uno con opciones, recomendación y por qué.

- **S-01 — Respuesta de las transiciones.** Opciones: (A) 200 con `OrdenDetalleSalida` releída con `get_detalle` + `armar_detalle` (misma forma que el alta y que `GET /ordenes/{id}`); (B) 200 mínimo `{id, estado, mecanico_id}`; (C) 204. **Recomendado A**: una sola forma de orden en toda la API, muestra el historial nuevo (evidencia de RN15) y cumple la regla de C-13 de releer después del punto único; cuesta 3 SELECT.
- **S-02 — Cuerpo.** Opciones: (A) sin cuerpo declarado (FastAPI no lo lee; el OpenAPI no declara `requestBody`); (B) cuerpo opcional `EntradaBase` vacío, que daría 422 a cualquier campo. **Recomendado A**: la matriz no da 422 por cuerpo, nada viaja del cliente y no hay schema de entrada que vigilar; el caso 53 muestra que un cuerpo no cambia nada.
- **S-03 — Roles dentro del servicio.** Opciones: (A) `AsignacionRolRepository` (usuarios, sin modificarlo) como `uow.asignaciones` en el `OrdenesUoW`, leído en la misma transacción; (B) una dependencia del router que lea los roles con el `UsuariosUoW` (el router llamaría a un repositorio o habría que agregar una función a `usuarios/service.py`, archivo de Mati); (C) `requiere_rol(Rol.MECANICO, Rol.ADMIN)` como filtro grueso en terminar (el servicio igual necesita saber si es ADMIN). **Recomendado A**: respeta Router → Service → UoW → Repository, no toca `usuarios` ni `core` y decide con roles de la base (RN04).
- **S-04 — «Mecánico asignado».** Opciones: (A) `mecanico_id == actor` **y** rol MECANICO vigente; (B) sólo `mecanico_id == actor`. **Recomendado A**: RN04 (permisos con la base en cada petición); a un mecánico dado de baja no le alcanza con haber iniciado la orden. Un ADMIN siempre puede.
- **S-05 — Iniciar.** Sólo MECANICO vigente por `requiere_rol` (un ADMIN sin MECANICO → 403, matriz); una orden ya `EN_REPARACION` (propia o de otro) → 409 sin reasignar; el actor queda como `mecanico_id` y nadie lo cambia después. Alternativa: permitir que otro mecánico la «tome» (reasignación) — no está en RN11. **Recomendado** como está.
- **S-06 — Terminar una `PENDIENTE`.** Un mecánico no ADMIN → 403 (nadie está asignado y el permiso va antes que el estado); un ADMIN → 409 `No se puede terminar … debe estar EN_REPARACION`. Alternativa: 409 para todo MECANICO. **Recomendado** como está: es la regla «403 antes que 409» aplicada literalmente.
- **S-07 — 404 antes que 403.** Opciones: (A) orden inexistente → 404 a cualquiera con sesión; existente sin relación → 403; (B) 404 también para quien no tiene relación (oculta la existencia). **Recomendado A**: el PDF C-13 pide 403 para «una orden ajena» y la matriz lista 403 y 404; mismo criterio para C-15 (`GET /ordenes/{id}`).
- **S-08 — Dueño y personal que cancela.** Dueño = el usuario de la ficha (`cliente.usuario_id`) del vehículo de la orden, también si el vehículo está dado de baja (RN16), sin exigir el rol CLIENTE; una ficha sin usuario no tiene dueño que cancele. Personal = RECEPCION o ADMIN vigentes (MECANICO no cancela salvo que sea el dueño). Alternativa: exigir además CLIENTE vigente al dueño. **Recomendado** como está: la consigna define al dueño por la relación, no por un rol (como `/mis-vehiculos`, «Autenticado»).
- **S-09 — Cancelar sólo `PENDIENTE`.** `EN_REPARACION` → 409 (RN11: la única transición a CANCELADA sale de PENDIENTE). Alternativa: permitir cancelar en reparación — no está en RN11/RN12. **Recomendado**.
- **S-10 — Reglas guiadas por el catálogo.** Una consulta `estados.listar()`: estado actual con `es_final` → 409 «estado final»; luego la tabla `ORIGEN` (un origen por destino); destino ausente del catálogo → 409 propio; la FK violada por una carrera con `psql` se traduce al mismo 409. Alternativas: sólo la tabla en código (el catálogo no guiaría nada, contra el alcance de CHANGES) o dos `get_por_codigo` (dos consultas). **Recomendado** como está.
- **S-11 — Repuestos dados de baja al terminar.** `incluir_bajas=True` (C-11 S-11, confirmado): se descuentan igual. Alternativa: `False` y 404/409 — la orden quedaría sin poder terminarse. **Recomendado**.
- **S-12 — Movimientos de la terminación.** Uno por ítem, `cantidad` negativa, `orden_id`, `usuario_id` = el actor que terminó, motivo `Orden #<id> terminada`. Alternativa: `usuario_id` = el mecánico asignado aunque termine un ADMIN — el movimiento registra quién lo hizo. **Recomendado**.
- **S-13 — Contenido y registro del aviso.** `await asyncio.sleep(0.5)` + una línea INFO `Aviso simulado al cliente: la orden #<id> del vehículo <patente> está terminada` (sin datos personales). Logger: (A) `logging.getLogger("uvicorn.error.avisos")`, que hereda el nivel INFO y la salida de consola que uvicorn ya configura, así «el aviso sale en el registro» sin tocar `main.py` ni `core`; (B) `logging.getLogger(__name__)` con `logger.warning` (visible por el `lastResort`, nivel engañoso); (C) configurar `logging` en `main.py`/lifespan (archivo compartido, afecta a todos). **Recomendado A**, con B si se prefiere no depender del nombre de logger de uvicorn. Verificable en el script con un handler propio (D9-f).
- **S-14 — Historial y fechas.** `usuario_id` = actor de cada transición; `cuando = datetime.now(UTC)` por transición; `desde_estado` = estado leído bajo el bloqueo; nunca se actualiza una línea. **Recomendado**.
- **S-15 — Mensajes.** Los de D7 (403 específicos por ruta; 409 de estado con la acción, el estado actual y el esperado; el de stock sin cambios). Alternativa: reutilizar `No tiene permiso para realizar esta operación` en los 403 de terminar/cancelar. **Recomendado** específicos: dicen qué relación falta, sin revelar más que el 403 mismo.
- **S-16 — Archivo de casos.** Nuevo `test/transiciones.http` (correos `@transiciones.example.com`, documentos `470000xx`, patentes `ZT…`, códigos `TRN-…`; encabezado `TRUNCATE` como `test/ordenes.http`). Alternativa: extender `test/ordenes.http` (renumerar 79 casos y más conflictos con C-15). **Recomendado** archivo nuevo.
- **S-17 — Bloqueo de la orden.** `FOR UPDATE` simple sobre `orden_trabajo`, primera sentencia de las tres transiciones; nunca vehículo; repuestos sólo por el punto único. Alternativa: `FOR NO KEY UPDATE` (dejaría pasar `INSERT` hijos de otra transacción, que hoy no existen). **Recomendado** `FOR UPDATE` (C-13 D6).
- **S-18 — Lectura de ítems.** `ItemOrdenRepository.listar_de_orden` (1 consulta, sin relaciones) antes del punto único; la respuesta se relee con `get_detalle`. Alternativa: `get_detalle` antes y después (3 + 3). **Recomendado** como está.
- **S-19 — «Hay N» del 409.** Se acepta el valor de `leer_stock` sin `FOR SHARE` (nota de C-11): puede reflejar el stock que dejó otra transacción confirmada. Alternativa: pedir a Mati `leer_stock` con `FOR SHARE` (toca el punto único). **Recomendado** aceptarlo.

## Notas para otros changes

**Mati (revisa propose y apply; dueño de `repuestos/*`, `usuarios/*` y `core/*`)**
- C-14 no modifica archivos de Mati: usa `aplicar_movimientos_stock` tal cual (`incluir_bajas=True`), importa `AsignacionRolRepository` (S-03) y `UsuarioActualDep`. Confirmar S-03, S-11 (ya confirmado en C-11) y S-19.

**C-15 (lecturas — Nico propone, Lauti implementa)**
- `GET /ordenes/{id}`: reutilizar `get_detalle` + `armar_detalle` (ya muestran `mecanico_id` y el historial completo de las transiciones). Para «el personal o el dueño» puede reutilizar `OrdenTrabajoRepository.get_usuario_dueno` o leer `vehiculo.cliente.usuario_id` ya precargado; mismo orden 404 → 403 (S-07).
- Las órdenes de un vehículo dado de baja (C-10 sólo lo permite si todas están en estado final) siguen existiendo y su dueño sigue siendo dueño (S-08): decidir allí si `/mis-ordenes` las muestra (recomendable: sí, RN16).
- `mecanico_id` se expone como id (sin nombre ni correo del mecánico); si C-15 quiere el nombre, agregar la precarga en su repositorio.
- El filtro `estado` de `GET /ordenes` puede validar con `CodigoEstado` y ordenar como el catálogo.

**C-06 (seed — Lauti)**
- La orden #2 del seed (`EN_REPARACION`, `mecanico@example.com`, 4 bujías con stock 2) debe tener `mecanico_id` del mecánico y dos líneas de historial (`null → PENDIENTE`, `PENDIENTE → EN_REPARACION` con el mecánico) para que el caso PDF C-11/C-12 se reproduzca con `POST /ordenes/2/terminar` (409) → `POST /repuestos/{bujía}/reponer` → terminar (200). El catálogo debe marcar `TERMINADA` y `CANCELADA` con `es_final = true` (D5 lo usa).

**C-16 (integración — Lauti; evidencia — Nico)**
- Integrar `test/transiciones.http` (su encabezado vacía órdenes y repuestos: correrlo después de `test/ordenes.http`/`test/stock.http` o antes de `python seed.py`).
- Evidencia del caso PDF C-14 = `test/solo_agregado.sql` (ya existe desde C-04; entregable de Nico por REPARTO §6): capturar en `psql` los seis rechazos del disparador y el de la FK. No es parte de este change.
- Evidencia del caso PDF C-12: la línea del aviso en la consola de uvicorn después de la línea de acceso del `POST /ordenes/2/terminar`.

## Notas para el archivo

- KB `07_flujos_principales.md` Flujo 5: el paso 3 dice «CHECK `stock >= 0` / validación»; precisar que el 409 lo decide el `UPDATE` condicional del punto único y agregar el orden de bloqueo (orden `FOR UPDATE` → repuestos ascendentes). Flujo 6: dueño = usuario de la ficha del vehículo (S-08) y 404 antes que 403 (S-07).
- KB `03_actores_y_roles.md`: anotar que las tres transiciones dan además 422 por id inválido y que «mecánico asignado» exige MECANICO vigente (S-04).
- KB `09_decisiones_y_supuestos.md` DD-10: logger del aviso (S-13); DD-11: las transiciones se serializan por el bloqueo de la orden.
- KB `06_funcionalidades.md` US-051: marcar como cubierta.
- `CHANGES.md`: marcar C-14 `[x]` (lo hace Mati al archivar).
