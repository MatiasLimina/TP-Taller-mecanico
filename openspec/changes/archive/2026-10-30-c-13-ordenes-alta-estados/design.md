# Design — C-13 ordenes-alta-estados

## Context

Motivación en proposal.md — Why; requisitos en `specs/work-orders` y `specs/order-states`. Estado actual relevante:

- **Modelos (C-03)**: `app/modules/ordenes/models.py` tiene `CodigoEstado` (StrEnum `PENDIENTE`, `EN_REPARACION`, `TERMINADA`, `CANCELADA`), `EstadoOrden(codigo PK, descripcion, posicion UNIQUE, es_final)`, `OrdenTrabajo(id, vehiculo_id, mecanico_id | None, estado: str FK, falla, creada_en [default_factory ahora_utc + server_default now()], total: Decimal(12,2) sin default)`, `ItemOrden(id, orden_id [CASCADE], repuesto_id, cantidad, precio_unitario: Decimal(10,2))` e `HistorialEstadoOrden(id, orden_id, desde_estado | None, hasta_estado, usuario_id [NOT NULL], cuando)`. Todas las relaciones `lazy="raise"`; `OrdenTrabajo.items` y `.historial` declaran `order_by` por id; `vehiculo`, `ItemOrden.repuesto` y `Vehiculo.cliente` existen en ambos extremos. El docstring fija: las columnas de estado son `str` (no ENUM nativo) y `CodigoEstado` es «el vocabulario del servicio».
- **Esquema (migración 1)**: `pk_estado_orden`, `uq_estado_orden_posicion`; `ck_orden_trabajo_total_no_negativo`, `fk_orden_trabajo_estado_estado_orden`, `fk_orden_trabajo_vehiculo_id_vehiculo`, `fk_orden_trabajo_mecanico_id_usuario`, índices `ix_orden_trabajo_{estado,mecanico_id,vehiculo_id}`; `ck_item_orden_cantidad_positiva`, `ck_item_orden_precio_unitario_positivo`, `uq_item_orden_orden_id_repuesto_id`, `fk_item_orden_orden_id_orden_trabajo` (`ON DELETE CASCADE`), `fk_item_orden_repuesto_id_repuesto`, `ix_item_orden_repuesto_id`; `fk_historial_estado_orden_{orden_id_orden_trabajo,desde_estado_estado_orden,hasta_estado_estado_orden,usuario_id_usuario}` con sus índices. `falla` es `VARCHAR` sin largo. El catálogo nace **vacío** (lo carga C-06, no mergeado). No hace falta migración (y no se puede: REPARTO §7.6).
- **Sólo agregado (migración 2)**: `trg_solo_agregado` rechaza `UPDATE`/`DELETE` por fila en `historial_estado_orden` (`P0001` → 500 por el manejador global); `TRUNCATE` no lo dispara. Consecuencia para el `.http`: una orden creada por la API no se puede borrar (su historial la referencia) — S-16.
- **Errores (C-02)**: `IntegrityError` 23505/23503 → 409 genérico; 23514 (CHECK) → 422 genérico; `DBAPIError` clase 22 (p. ej. `NUMERIC(12,2)` desbordado) → 422 genérico. Por eso los rechazos de negocio se deciden antes de escribir, con mensaje propio, y las restricciones quedan de red.
- **C-10 (mergeado, sin archivar)**: `VehiculoRepository.get_vigente_para_actualizar(id)` = `_consulta_base()` (vigentes) `.with_for_update()` + `populate_existing`; `DELETE /vehiculos/{id}` lo usa y después `tiene_ordenes_abiertas` (join a `estado_orden.es_final`). Su design deja a C-13 la obligación de leer el vehículo con ese bloqueo dentro del UoW de la orden (S-02 de C-10: el `FOR KEY SHARE` que toma la FK al insertar la orden no espera a una baja lógica, que sólo hace `UPDATE`).
- **C-11 (archivado)**: `RepuestoRepository(SoftDeleteRepository[Repuesto])` con `get_vigente_para_actualizar` (`FOR UPDATE`, usado por PATCH y DELETE), `sumar_stock`/`leer_stock` (sólo el punto único); `MovimientoStockRepository`; protocolo `ConStock` (`repuestos`, `movimientos`) y `aplicar_movimientos_stock` en `repuestos/service.py`. Su nota para C-13: el `OrdenesUoW` compone esos dos repositorios y agrega a `RepuestoRepository` (coordinado con Mati) una lectura de los repuestos pedidos vigentes en una consulta, en orden de id, con `FOR SHARE`.
- **Core**: `BaseRepository` (`add` con `flush()`, `_consulta_base`, `get_by_id` con `select`), `UnitOfWork` (no se abre dos veces; sesión con `expire_on_commit=False`), `EntradaBase`/`SalidaBase` (revisa `password_hash` y modelos de tabla al definir el contrato; no admite referencias en texto), `IdRuta`/`INT4_MAX`, `NoEncontrado`/`Conflicto`/`EntradaInvalida`, `restriccion_violada`, `requiere_rol`, `UsuarioActualDep`. Sólo Mati modifica `app/core/*` (REPARTO §9): este change no lo toca. Aislamiento por defecto de PostgreSQL (READ COMMITTED).
- **Consigna**: ejemplo de cuerpo `{"vehiculo_id": 2, "falla": "Ruido al frenar", "items": [{"repuesto_id": 2, "cantidad": 1}, {"repuesto_id": 4, "cantidad": 3}]}` y respuesta `{id, estado, patente, total: "68000.00", creada_en, mecanico_id: null, falla, cliente: "Laura Cliente", items: [{repuesto_id, codigo, descripcion, cantidad, precio_unitario, subtotal}], historial: [{desde_estado: null, hasta_estado: "PENDIENTE", usuario_id: 3, cuando}]}` (el `usuario_id` 3 es la recepción del seed: el actor). Matriz validada: `POST /ordenes` RECEPCION, ADMIN → 201, 409, 422 (sin 404); `GET /estados-orden` Autenticado → 200.

## Goals / Non-Goals

**Goals:**

- Módulo `ordenes` con la estructura obligatoria y el patrón de C-10/C-11, que C-14 y C-15 extienden sin reabrir decisiones: un `OrdenesUoW` que ya cumple `ConStock`, un armado único de la salida de detalle y un contrato de bloqueos explícito.
- Alta atómica en cuatro tablas, con todos los rechazos de negocio decididos antes de escribir y con mensaje propio; ninguna entrada inválida termina en 500.
- Serialización con la baja de vehículos (C-10) y con la baja y el cambio de precio de repuestos (C-11), sin interbloqueos con el punto único de escritura de stock (C-11/C-12/C-14).
- Número fijo de consultas en el alta, independiente de la cantidad de ítems.

**Non-Goals:**

- Transiciones, cancelación, lecturas de órdenes (C-14, C-15); validar stock al crear (S-17).
- Cambiar el comportamiento de `clientes` o `repuestos`: sólo se reutilizan sus repositorios y se agrega **un** método de lectura a `RepuestoRepository` (S-01).
- Reintentos, `SERIALIZABLE` o bloqueos de asesoramiento: alcanza con bloqueos de fila en orden fijo.

## Decisions

### D1 — Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/modules/ordenes/schemas.py` (nuevo) | constantes de contrato; tipos `IdEntidad`, `Falla`, `Cantidad`; `ItemAltaEntrada`, `OrdenAltaEntrada`; `ItemOrdenSalida`, `HistorialEstadoSalida`, `OrdenDetalleSalida`, `EstadoOrdenSalida` |
| `app/modules/ordenes/repository.py` (nuevo) | `EstadoOrdenRepository` (sólo lectura, sin `BaseRepository`), `OrdenTrabajoRepository` (`get_detalle`), `ItemOrdenRepository` (`add_varios`), `HistorialEstadoOrdenRepository` |
| `app/modules/ordenes/unit_of_work.py` (nuevo) | `OrdenesUoW`, `get_ordenes_uow`, `OrdenesUoWDep` |
| `app/modules/ordenes/service.py` (nuevo) | `ESTADO_INICIAL`, `TOTAL_MAXIMO`, mensajes; `calcular_total`, `armar_detalle`, `alta`, `listar_estados` |
| `app/modules/ordenes/router.py` (nuevo) | `alta_orden` (`requiere_rol`), `AltaOrdenDep`, `router_ordenes`, `router_estados` |
| `app/modules/repuestos/repository.py` | **sólo agrega** `RepuestoRepository.listar_vigentes_para_orden` (S-01; coordinado con Mati) |
| `main.py` | import y dos `rutas_protegidas.include_router(...)` al final de la lista, antes de `app.include_router(rutas_protegidas)`; comentario del grupo (C-13) |
| `test/ordenes.http` (nuevo) | casos del change (D12) |

### D2 — Rutas, roles y montaje (S-14, S-15)

```python
# router.py
alta_orden = requiere_rol(Rol.RECEPCION, Rol.ADMIN)            # UNA función
AltaOrdenDep = Annotated[UsuarioActual, Depends(alta_orden)]

router_ordenes = APIRouter(prefix="/ordenes", tags=["ordenes"])           # sin rol a nivel de router
router_estados = APIRouter(prefix="/estados-orden", tags=["estados-orden"])  # cualquier autenticado

@router_ordenes.post("", status_code=201)
async def alta(datos: OrdenAltaEntrada, actual: AltaOrdenDep, uow: OrdenesUoWDep) -> OrdenDetalleSalida:
    return await service.alta(uow, datos, actual.id)

@router_estados.get("")
async def listar_estados(uow: OrdenesUoWDep) -> list[EstadoOrdenSalida]:
    return await service.listar_estados(uow)
```

- `/ordenes` mezcla roles: el alta es RECEPCION/ADMIN, `GET /ordenes` (C-15) suma MECANICO, `iniciar` es MECANICO, y `cancelar`/`terminar`/`GET /ordenes/{id}` no llevan `requiere_rol` (dueño, mecánico asignado). Por eso el rol va **por ruta** y no a nivel de router: un rol de router obligaría a C-14/C-15 a crear routers paralelos con el mismo prefijo.
- `/estados-orden` sólo depende del grupo protegido (`exigir_password_al_dia` → 401/403 cambio). Sin `requiere_rol`: la matriz dice «Autenticado».
- El handler necesita el actor (historial), así que `AltaOrdenDep` va como parámetro y FastAPI la resuelve antes de validar el cuerpo: orden de rechazos heredado 401 → 403 cambio → 403 rol → 422 → 409 (`access-control`; un JSON mal formado da 422 antes).
- El servicio recibe `actual.id` (`usuario_id: int`), no `UsuarioActual`: `ordenes.service` no depende de `usuarios.service` (como C-10/C-11).
- `main.py`: `from app.modules.ordenes.router import router_estados, router_ordenes` (orden de imports de ruff) y `rutas_protegidas.include_router(router_ordenes)` + `rutas_protegidas.include_router(router_estados)` **después** de `router_mis_vehiculos` sin reordenar las existentes (REPARTO §9).

### D3 — Contratos (S-06, S-07, S-08)

```python
CANTIDAD_MAXIMA_ITEMS = 50
CANTIDAD_MAXIMA_POR_ITEM = 1_000
LARGO_MAXIMO_FALLA = 500

IdEntidad = Annotated[int, Field(ge=1, le=INT4_MAX)]
Falla = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LARGO_MAXIMO_FALLA)]
Cantidad = Annotated[int, Field(ge=1, le=CANTIDAD_MAXIMA_POR_ITEM)]

class ItemAltaEntrada(EntradaBase):          # extra="forbid" también en el ítem
    repuesto_id: IdEntidad
    cantidad: Cantidad

class OrdenAltaEntrada(EntradaBase):
    vehiculo_id: IdEntidad
    falla: Falla
    items: Annotated[list[ItemAltaEntrada], Field(min_length=1, max_length=CANTIDAD_MAXIMA_ITEMS)]

    @field_validator("items")
    @classmethod
    def _sin_repetidos(cls, items: list[ItemAltaEntrada]) -> list[ItemAltaEntrada]:
        vistos, repetidos = set(), set()
        for item in items:
            (repetidos if item.repuesto_id in vistos else vistos).add(item.repuesto_id)
        if repetidos:
            raise ValueError(f"Hay repuestos repetidos en la orden: {', '.join(map(str, sorted(repetidos)))}")
        return items

class ItemOrdenSalida(SalidaBase):
    repuesto_id: int; codigo: str; descripcion: str; cantidad: int; precio_unitario: Decimal; subtotal: Decimal

class HistorialEstadoSalida(SalidaBase):
    desde_estado: str | None; hasta_estado: str; usuario_id: int; cuando: datetime

class OrdenDetalleSalida(SalidaBase):        # forma y orden de campos del ejemplo de la consigna (S-05)
    id: int; estado: str; patente: str; total: Decimal; creada_en: datetime; mecanico_id: int | None
    falla: str; cliente: str; items: list[ItemOrdenSalida]; historial: list[HistorialEstadoSalida]

class EstadoOrdenSalida(SalidaBase):
    codigo: str; descripcion: str; posicion: int; es_final: bool
```

- `extra="forbid"` (de `EntradaBase`) da el 422 de `precio_unitario`, `total`, `estado`, `creada_en`, `mecanico_id` sin código propio (RN10). El `field_validator` corre después de validar cada ítem: un ítem inválido da su propio error y no se evalúan repetidos.
- Los `Decimal` de salida salen como texto (`"68000.00"`, Pydantic v2), igual que `RepuestoSalida.precio`. Las clases de salida se definen en el orden de la tabla (las anidadas primero).
- Los CHECK de `item_orden` y `orden_trabajo` quedan de red: el contrato ya impide `cantidad <= 0` y el catálogo de repuestos `precio <= 0`.

### D4 — Repositorios (S-01, S-04, S-14, S-18)

```python
# ordenes/repository.py
class EstadoOrdenRepository:                 # NO hereda de BaseRepository: PK `codigo`, sin escrituras (RN19)
    def __init__(self, session: AsyncSession) -> None: self.session = session
    async def listar(self) -> list[EstadoOrden]:                   # ORDER BY posicion
    async def get_por_codigo(self, codigo: str) -> EstadoOrden | None:   # select ... WHERE codigo = :codigo

class OrdenTrabajoRepository(BaseRepository[OrdenTrabajo]):
    async def get_detalle(self, id: int) -> OrdenTrabajo | None:
        consulta = (
            self._consulta_base().where(col(OrdenTrabajo.id) == id)
            .options(
                joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente),   # 1 SELECT con dos JOIN
                selectinload(OrdenTrabajo.items).joinedload(ItemOrden.repuesto),   # 1 SELECT (order_by id)
                selectinload(OrdenTrabajo.historial),                             # 1 SELECT (order_by id)
            )
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(consulta)).unique().first()

class ItemOrdenRepository(BaseRepository[ItemOrden]):
    async def add_varios(self, items: Sequence[ItemOrden]) -> list[ItemOrden]:
        self.session.add_all(items); await self.session.flush(); return list(items)   # un INSERT multi-fila

class HistorialEstadoOrdenRepository(BaseRepository[HistorialEstadoOrden]): ...   # sólo add() (RN15)

# repuestos/repository.py — SÓLO se agrega este método (S-01, coordinado con Mati)
class RepuestoRepository(...):
    async def listar_vigentes_para_orden(self, ids: Collection[int]) -> list[Repuesto]:
        """Repuestos VIGENTES de `ids`, en orden de id, con FOR SHARE (alta de orden, C-13). ..."""
        consulta = (
            self._consulta_base()                                   # borrado_en IS NULL
            .where(col(Repuesto.id).in_(sorted(ids)))              # parámetros ligados (expanding)
            .order_by(col(Repuesto.id))                             # orden de bloqueo = orden de id
            .with_for_update(read=True)                             # FOR SHARE
            .execution_options(populate_existing=True)
        )
        return list((await self.session.exec(consulta)).all())
```

- `get_detalle`: 3 consultas fijas para cualquier cantidad de ítems; `ItemOrden.repuesto` se carga sin filtrar bajas (RN16: el repuesto dado de baja conserva sus datos y la orden los muestra). `populate_existing` es obligatorio: la orden, los ítems y el historial recién agregados ya están en el identity map con las relaciones sin cargar (`lazy="raise"`); sin él, una colección ya presente podría no refrescarse. `.unique()` por el `joinedload` (lo exige SQLAlchemy 2.0 con colecciones; aquí es many-to-one, se deja por consistencia). C-15 lo reutiliza tal cual en `GET /ordenes/{id}`.
- `add_varios`: con `insertmanyvalues` de SQLAlchemy 2.0 (asyncpg), N ítems se insertan en **una** sentencia `INSERT … VALUES (…), (…) RETURNING id`, con los ids en el orden de la lista. `BaseRepository` no tiene `add_all` y `core` no se toca, así que el método vive en el repositorio del módulo. Se verifica en el script (D12-g).
- `listar_vigentes_para_orden`: `FOR SHARE` (S-04) choca con el `FOR UPDATE` de `get_vigente_para_actualizar` (PATCH y DELETE de C-11) y con el `UPDATE` del punto único; dos altas que comparten repuestos no se esperan entre sí. Con `ORDER BY`, PostgreSQL bloquea las filas en orden de id (el bloqueo se aplica después de ordenar). En READ COMMITTED, si la fila cambió mientras esperaba, la reevalúa: una baja confirmada la excluye (→ 409) y un precio nuevo se lee nuevo.
- Índices: PK de `estado_orden` y `uq_estado_orden_posicion` (orden del listado), PK de `vehiculo`, PK de `repuesto` (`IN`), PK de `orden_trabajo`, `uq_item_orden_orden_id_repuesto_id` (precarga de ítems por `orden_id`), `ix_historial_estado_orden_orden_id`. No se crea ninguno.

### D5 — Unit of Work

```python
class OrdenesUoW(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.estados = EstadoOrdenRepository(session)
        self.ordenes = OrdenTrabajoRepository(session)
        self.items = ItemOrdenRepository(session)
        self.historial = HistorialEstadoOrdenRepository(session)
        self.vehiculos = VehiculoRepository(session)        # de clientes (C-10): bloqueo del vehículo
        self.repuestos = RepuestoRepository(session)        # de repuestos (C-11): lectura FOR SHARE
        self.movimientos = MovimientoStockRepository(session)  # sin uso en C-13: completa ConStock para C-14
```

Todos sobre la misma sesión; no instancia ni abre `ClientesUoW` ni `RepuestosUoW` (nunca hay dos UoW abiertos). Cumple `ConStock` (`repuestos`, `movimientos`): C-14 llama `aplicar_movimientos_stock(uow, …)` dentro del bloque que abre su servicio.

### D6 — Contrato de bloqueos y concurrencia (S-02, S-03, S-04)

**Orden global de bloqueo de filas** (toda transacción que bloquee filas de varias tablas las toma en este orden y nunca vuelve atrás):

| Paso | Tabla | Quién | Modo |
|------|-------|-------|------|
| 1 | `orden_trabajo` (una orden existente) | C-14 iniciar/terminar/cancelar | `FOR UPDATE` |
| 2 | `vehiculo` | C-13 alta; C-10 baja | `FOR UPDATE` (`get_vigente_para_actualizar`) |
| 3 | `repuesto`, en orden ascendente de `id` | C-13 alta (`FOR SHARE`, una consulta); C-11 PATCH/DELETE (`FOR UPDATE`, una fila); punto único C-11/C-12/C-14 (`UPDATE` condicional, en orden de id) | según el caso |
| — | `estado_orden`, `usuario`, `cliente` | nadie explícitamente | sólo `FOR KEY SHARE` implícito de las FK |

El alta (C-13) toma 2 y luego 3; nunca bloquea una orden existente. Terminar (C-14) toma 1 y luego 3; no bloquea vehículos. La baja de vehículo (C-10) toma sólo 2 (lee órdenes sin bloquear). PATCH/DELETE de repuesto (C-11) toman una fila de 3. Como todas las esperas van «hacia adelante» en la tabla, no hay ciclos: **sin interbloqueos**. Los `INSERT` del alta toman `FOR KEY SHARE` por FK sobre filas que la transacción ya tiene bloqueadas (vehículo, repuestos) o que nadie bloquea en modo exclusivo (catálogo, usuario), y `FOR KEY SHARE` es compatible con el `FOR NO KEY UPDATE` de los `UPDATE` de stock y de contraseña.

**Interacciones** (READ COMMITTED; el que espera reevalúa la fila al seguir):

| Primero | Después | Resultado |
|---------|---------|-----------|
| Baja de vehículo (`FOR UPDATE` + `UPDATE borrado_en`) | Alta de orden | El alta espera; reevalúa `borrado_en IS NULL` → sin fila → 409 vehículo |
| Alta de orden (vehículo `FOR UPDATE`) | Baja de vehículo | La baja espera; al seguir, `tiene_ordenes_abiertas` ve la orden confirmada → 409 (C-10) |
| Baja de repuesto (`FOR UPDATE`) | Alta que lo usa | El alta espera; la fila ya no es vigente → 409 repuestos |
| PATCH de precio (`FOR UPDATE`) | Alta que lo usa | El alta espera y copia el precio nuevo |
| Alta (`FOR SHARE`) | PATCH o baja del repuesto | Esperan al alta; la orden queda con el precio y el repuesto de antes |
| Punto único (`UPDATE` de stock) | Alta con ese repuesto | El alta espera a que confirme (stock y precio no se mezclan) |
| Alta (`FOR SHARE`) | Punto único | El `UPDATE` espera al alta; luego aplica normalmente |
| Alta | Alta (mismo vehículo) | La segunda espera el vehículo; ambas 201 |
| Alta | Alta (otro vehículo, mismos repuestos) | `FOR SHARE` compatibles; ambas 201 sin esperar |

- *Alternativa descartada* (vehículo con `FOR SHARE` en un método nuevo): evitaría serializar dos altas del mismo vehículo, pero obliga a tocar `clientes/repository.py`; dos altas simultáneas del mismo vehículo son raras y la espera es de milisegundos. Se reutiliza el método de C-10 tal cual (S-02).
- *Alternativa descartada* (`FOR KEY SHARE` en los repuestos): no esperaría a los `UPDATE` de stock, pero sólo serializa con PATCH/DELETE mientras esos sigan tomando `FOR UPDATE` explícito; `FOR SHARE` es lo acordado con C-11 y no depende de cómo escriba el otro (S-04).
- *Alternativa descartada* (`SERIALIZABLE` o reintentos): el UoW no reintenta; un fallo de serialización sería 500.

### D7 — `POST /ordenes` (S-09, S-10, S-11, S-12, S-13)

```python
ESTADO_INICIAL = CodigoEstado.PENDIENTE
CENTAVO = Decimal("0.01")
TOTAL_MAXIMO = Decimal("9999999999.99")           # = NUMERIC(12,2) de orden_trabajo.total
RESTRICCIONES_DE_ESTADO = {"fk_orden_trabajo_estado_estado_orden",
                           "fk_historial_estado_orden_hasta_estado_estado_orden"}

def calcular_total(items: Sequence[ItemAltaEntrada], precios: Mapping[int, Decimal]) -> Decimal:
    return sum((precios[i.repuesto_id] * i.cantidad for i in items), Decimal("0")).quantize(CENTAVO)

async def alta(uow: OrdenesUoW, datos: OrdenAltaEntrada, usuario_id: int) -> OrdenDetalleSalida:
    try:
        async with uow:
            if await uow.estados.get_por_codigo(ESTADO_INICIAL.value) is None:          # RN19
                raise Conflicto(MENSAJE_CATALOGO_SIN_ESTADO_INICIAL)
            vehiculo = await uow.vehiculos.get_vigente_para_actualizar(datos.vehiculo_id)   # FOR UPDATE (D6 paso 2)
            if vehiculo is None:
                raise Conflicto(MENSAJE_VEHICULO_NO_DISPONIBLE.format(vehiculo_id=datos.vehiculo_id))
            pedidos = [i.repuesto_id for i in datos.items]
            repuestos = await uow.repuestos.listar_vigentes_para_orden(pedidos)        # FOR SHARE (D6 paso 3)
            precios = {r.id: r.precio for r in repuestos}
            faltantes = sorted(set(pedidos) - precios.keys())
            if faltantes:
                raise Conflicto(MENSAJE_REPUESTOS_NO_DISPONIBLES.format(ids=", ".join(map(str, faltantes))))
            total = calcular_total(datos.items, precios)
            if total > TOTAL_MAXIMO:
                raise EntradaInvalida(MENSAJE_TOTAL_EXCEDIDO)
            ahora = datetime.now(UTC)                                                   # S-12: un instante
            orden = await uow.ordenes.add(OrdenTrabajo(
                vehiculo_id=datos.vehiculo_id, estado=ESTADO_INICIAL.value, falla=datos.falla,
                total=total, creada_en=ahora))                                           # mecanico_id nulo
            assert orden.id is not None
            await uow.items.add_varios([
                ItemOrden(orden_id=orden.id, repuesto_id=i.repuesto_id, cantidad=i.cantidad,
                          precio_unitario=precios[i.repuesto_id]) for i in datos.items])   # orden del cuerpo
            await uow.historial.add(HistorialEstadoOrden(
                orden_id=orden.id, desde_estado=None, hasta_estado=ESTADO_INICIAL.value,
                usuario_id=usuario_id, cuando=ahora))
            detalle = await uow.ordenes.get_detalle(orden.id)
            assert detalle is not None
            salida = armar_detalle(detalle)                                             # dentro del bloque
    except IntegrityError as exc:
        if restriccion_violada(exc) in RESTRICCIONES_DE_ESTADO:   # el catálogo cambió por psql en el medio
            raise Conflicto(MENSAJE_CATALOGO_SIN_ESTADO_INICIAL) from None
        raise
    return salida
```

- Orden de las verificaciones = KB Flujo 4: catálogo (sin bloqueo, así un 409 de catálogo no bloquea nada) → vehículo → repuestos → total. Cada rechazo es una excepción que sale del bloque: el UoW revierte y libera los bloqueos; antes del primer `add` no se escribió nada, y después ningún paso falla por regla de negocio.
- Ninguna otra violación de integridad es alcanzable: el vehículo y los repuestos están bloqueados y nunca se borran físicamente; `uq_item_orden_orden_id_repuesto_id` lo evita el contrato; los CHECK, el contrato y el catálogo. Si aun así ocurriera, el manejador global responde 409/422 genérico, nunca 500 ni texto de la base.
- `datetime.now(UTC)` explícito en `creada_en` y `cuando`: un mismo instante para la creación y su primera línea de historial (S-12), con zona (regla dura).
- Consultas del alta autorizada (además de las de sesión/rol): catálogo 1, vehículo 1, repuestos 1, `INSERT` orden 1, `INSERT` ítems 1, `INSERT` historial 1, detalle 3 = **9 fijas** para cualquier cantidad de ítems.

### D8 — `armar_detalle` (S-05)

```python
def armar_detalle(orden: OrdenTrabajo) -> OrdenDetalleSalida:
    """Salida de detalle desde una orden leída con `OrdenTrabajoRepository.get_detalle` (C-13 y C-15)."""
    return OrdenDetalleSalida(
        id=orden.id, estado=orden.estado, patente=orden.vehiculo.patente, total=orden.total,
        creada_en=orden.creada_en, mecanico_id=orden.mecanico_id, falla=orden.falla,
        cliente=orden.vehiculo.cliente.nombre,
        items=[ItemOrdenSalida(repuesto_id=i.repuesto_id, codigo=i.repuesto.codigo,
                               descripcion=i.repuesto.descripcion, cantidad=i.cantidad,
                               precio_unitario=i.precio_unitario,
                               subtotal=(i.precio_unitario * i.cantidad).quantize(CENTAVO))
               for i in orden.items],
        historial=[HistorialEstadoSalida.model_validate(h) for h in orden.historial])
```

Sólo lee relaciones precargadas por `get_detalle` (con `lazy="raise"`, leer otra lanzaría en lugar de consultar). `items` y `historial` llegan en orden de id (`order_by` del modelo); los ítems tienen ids en el orden del cuerpo (D4), así que la respuesta respeta el orden en que llegaron.

### D9 — `GET /estados-orden` (S-14)

```python
async def listar_estados(uow: OrdenesUoW) -> list[EstadoOrdenSalida]:
    async with uow:
        estados = await uow.estados.listar()
        salida = [EstadoOrdenSalida.model_validate(e) for e in estados]
    return salida
```

Arreglo simple (sin paginar: la matriz sólo da 200 y son pocas filas). Catálogo vacío → `[]`. Una consulta.

### D10 — Mensajes

| Situación | Código | `detail` |
|-----------|--------|----------|
| Catálogo vacío o sin `PENDIENTE` (también la carrera de la FK) | 409 | `No se pueden crear órdenes: el catálogo de estados está vacío o no tiene el estado PENDIENTE` |
| Vehículo inexistente o dado de baja | 409 | `El vehículo <id> no existe o está dado de baja` |
| Repuestos inexistentes o dados de baja | 409 | `Repuestos inexistentes o dados de baja: <id>, <id>` (todos, ascendente) |
| Total mayor que `NUMERIC(12,2)` | 422 | `El total de la orden supera el máximo admitido (9999999999.99)` |
| Repuesto repetido en `items` | 422 | lista por campo (`loc` `["body", "items"]`) con `Hay repuestos repetidos en la orden: <ids>` |
| Sin sesión / cambio pendiente / sin rol | 401 / 403 / 403 | mensajes de C-08 |

Constantes en `service.py`: `MENSAJE_CATALOGO_SIN_ESTADO_INICIAL`, `MENSAJE_VEHICULO_NO_DISPONIBLE` (con `{vehiculo_id}`), `MENSAJE_REPUESTOS_NO_DISPONIBLES` (con `{ids}`), `MENSAJE_TOTAL_EXCEDIDO`.

### D11 — Alcance en archivos ajenos

- `app/modules/repuestos/repository.py` (Mati): **sólo** se agrega `listar_vigentes_para_orden` al final de `RepuestoRepository`, con su docstring (para qué sirve, `FOR SHARE`, orden de bloqueo, quién lo llama). Ningún método existente cambia. Si Mati prefiere no tocar su archivo (S-01-B), el mismo método vive como `RepuestoParaOrdenRepository` en `ordenes/repository.py` sobre el modelo `Repuesto`, y el `OrdenesUoW` lo expone como `self.repuestos_orden` (el `self.repuestos` de `ConStock` sigue siendo el de C-11).
- `app/modules/clientes/*`: no se toca; se importa `VehiculoRepository`.
- Nunca `repuesto.stock = …`, `uow.repuestos.update(…, {"stock": …})`, `sumar_stock` ni `MovimientoStock(...)` en `ordenes` (REPARTO §9).

### D12 — Verificación sin pytest (Strict TDD adaptado, como C-11 D12)

- **RED**: `test/ordenes.http` completo se escribe primero (tarea 1.1) y se corre contra el servidor actual: preparación (registro, login, repuestos, vehículos) responde como hoy; toda ruta `/ordenes` y `/estados-orden` → 404. Se anota la línea de base.
- **GREEN**: cada tarea hace pasar los casos numerados que cita. **TRIANGULATE**: cada regla con al menos dos casos (acepta/rechaza, o dos motivos de rechazo). **Safety net**: `test/health.http`, `test/auth.http`, `test/sesion.http`, `test/personal.http`, `test/clientes.http`, `test/repuestos.http` y `test/verificar_security_core.py` antes de tocar `main.py`/`repuestos/repository.py` y al final.
- Lo que un `.http` no muestra va en **un** script temporal `$env:TEMP\verificar_c13.py` (no versionado), con `httpx.AsyncClient(transport=ASGITransport(app=main.app))` dentro de `async with main.lifespan(main.app)`, conexiones `asyncpg` propias para sostener bloqueos y sesiones de `main.app.state.session_factory` para llamar al servicio con UoW inyectados. Precondición: correr después de `test/ordenes.http` (usa las sesiones de `recepcion@ordenes.example.com` y `jefa@ordenes.example.com`); crea sus propios repuestos `SCRIPT-C13-…` y vehículos `ZOS…` (los limpia el encabezado del `.http`). Bloques:
  - (a) **baja de vehículo primero**: otra conexión hace `BEGIN; SELECT … FROM vehiculo WHERE id = X FOR UPDATE; UPDATE vehiculo SET borrado_en = now() WHERE id = X`; se lanza `POST /ordenes` para X; a los 0,5 s sigue esperando; `COMMIT` → 409 vehículo y 0 órdenes de X.
  - (b) **alta primero contra baja de vehículo**: otra conexión toma `SELECT … FROM repuesto WHERE id = P FOR UPDATE` (el alta queda esperando **después** de bloquear el vehículo); se lanza el `POST /ordenes` con P; se lanza `DELETE /vehiculos/{X}`; a los 0,5 s ambos esperan; `ROLLBACK` de la otra conexión → alta 201 y baja 409 `El vehículo tiene órdenes abiertas…`.
  - (c) **baja de repuesto primero**: otra conexión `SELECT … FOR UPDATE` + `UPDATE repuesto SET borrado_en = now()` de P; `POST` espera; `COMMIT` → 409 `Repuestos inexistentes o dados de baja: P` y sin orden.
  - (d) **precio primero**: otra conexión `FOR UPDATE` + `UPDATE repuesto SET precio = 777.00` de P; `POST` espera; `COMMIT` → 201 con `precio_unitario` `"777.00"`.
  - (e) **alta primero contra baja/PATCH de repuesto**: se llama a `service.alta` con un `OrdenesUoW` cuyo `historial.add` espera un `asyncio.Event` (ya tomó vehículo y repuestos); se lanza `DELETE /repuestos/{P}` (y en otra corrida `PATCH` de precio); a los 0,5 s espera; se libera el evento → la orden confirma con el ítem de P y el precio viejo; después la baja responde 204 (el PATCH 200).
  - (f) **atomicidad**: `OrdenesUoW` cuyo `historial.add` lanza `RuntimeError` → no queda la orden ni sus ítems; otro cuyo `items.add_varios` lanza → no queda la orden; en ambos el stock y `movimiento_stock` no cambian.
  - (g) **consultas constantes**: listener `before_cursor_execute` sobre `main.app.state.engine.sync_engine`: `POST /ordenes` con 1 ítem y con 5 ítems emiten la misma cantidad de sentencias (9 propias del alta + las de sesión/rol), con un solo `INSERT INTO item_orden`; los ids de repuesto viajan como parámetros (nunca dentro del SQL) y la lectura de repuestos muestra `FOR SHARE`, la del vehículo `FOR UPDATE`.
  - (h) **sin interbloqueos**: 20 repeticiones de, a la vez, dos altas con los mismos dos repuestos en orden inverso sobre vehículos distintos, un `PATCH` de precio de uno de ellos, y `aplicar_movimientos_stock(uow_repuestos, [B:+1, A:+1])` en su propio UoW → todos terminan con 201/200/éxito o 409, nunca `40P01` ni 500.
  - (i) **dos altas del mismo vehículo a la vez** → ambas 201 con ids distintos.
  - (j) **OpenAPI** (`/openapi.json`): el cuerpo de `POST /ordenes` declara sólo `vehiculo_id`, `falla`, `items` (ítem: `repuesto_id`, `cantidad`) con `additionalProperties: false`; la respuesta 201 declara exactamente los campos de `OrdenDetalleSalida`; ninguna respuesta de `/ordenes` ni `/estados-orden` declara `password_hash` ni `borrado_en`.
  - (k) **invariantes**: para toda orden, `total = SUM(cantidad × precio_unitario)`, una sola línea de historial `null → PENDIENTE` y `estado` `PENDIENTE`; `movimiento_stock` sin filas con `orden_id`; `stock = COALESCE(SUM(cantidad), 0)` por repuesto.

## Risks / Trade-offs

- [Archivo de otro integrante] → `listar_vigentes_para_orden` se agrega en `repuestos/repository.py` (Mati). Mitigación: S-01 lo pide explícitamente a Mati; un solo método al final de la clase, sin tocar los demás; alternativa B lista si no acepta. Conflicto de merge con C-12 (mismo archivo): mínimo, se resuelve conservando ambos métodos.
- [Bloqueo del vehículo con `FOR UPDATE`] → dos altas simultáneas del mismo vehículo se serializan. Se acepta (milisegundos; caso raro) a cambio de no tocar `clientes`.
- [Altas esperan a movimientos de stock] → `FOR SHARE` espera a un `UPDATE` de stock en curso del mismo repuesto (reponer, terminar). Transacciones cortas; sin ciclos por el orden global (D6).
- [Respuesta con 3 consultas extra] → releer con `get_detalle` cuesta 3 SELECT por alta. Se acepta: la respuesta es idéntica a `GET /ordenes/{id}` (C-15) por construcción, con un solo armado (S-05).
- [Pedido mayor que el stock] → una orden puede pedir más de lo que hay (seed: orden #2 con 4 bujías y stock 2, IN-04). Es lo buscado: se valida al terminar (C-14, RN13).
- [Datos de prueba que no se pueden borrar] → una orden creada por la API tiene historial de sólo agregado: el encabezado de `test/ordenes.http` usa `TRUNCATE` del dominio órdenes + repuestos (S-16), que vacía también las órdenes y repuestos de otros datos de desarrollo (mismo criterio que `test/repuestos.http` y `seed.py`).
- [Catálogo editado por psql en el medio del alta] → la FK lo rechaza; se traduce al 409 de catálogo (D7). El catálogo no se edita desde la API (RN19).
- [Tope de 50 ítems y 1000 unidades] → arbitrarios; cambiar una constante. El tope de total protege `NUMERIC(12,2)` igual (D7).

## Migration Plan

Sin cambios de esquema ni de datos. Despliegue: archivos nuevos del módulo, el método agregado a `repuestos/repository.py`, `main.py` y `test/ordenes.http`; reiniciar uvicorn. Rollback: revertir `main.py` y el método de `repuestos/repository.py`, borrar los cinco archivos del módulo; las filas de prueba se limpian con el bloque `psql` del encabezado de `test/ordenes.http` o con `python seed.py` (C-06).

## Open Questions / Supuestos

Todos los supuestos fueron **confirmados por el usuario el 2026-10-30**, cada uno con la recomendación indicada; S-01 cuenta además con el acuerdo de Mati (2026-10-30). Cada uno con opciones, recomendación y por qué.

- **S-01 — Dónde vive la lectura `FOR SHARE` de repuestos.** Opciones: (A) `RepuestoRepository.listar_vigentes_para_orden(ids)` en `repuestos/repository.py`, coordinado con Mati (lo que dejó anotado C-11); (B) `RepuestoParaOrdenRepository` en `ordenes/repository.py` sobre el modelo `Repuesto` (precedente: C-10 S-01 puso la consulta de órdenes abiertas en `clientes` para no tocar el archivo de otro); (C) un `get_vigente_para_actualizar` por repuesto (N consultas y `FOR UPDATE`: serializa altas que comparten repuestos). **Recomendado A**: la pregunta es del catálogo («¿qué repuestos vigentes son estos?»), queda junto a los otros bloqueos de `repuesto` y su orden, y es lo acordado en C-11; B si Mati prefiere no tocar su archivo; C descartada (N+1 y bloqueo exclusivo).
- **S-02 — Bloqueo del vehículo.** Opciones: (A) reutilizar `VehiculoRepository.get_vigente_para_actualizar` (`FOR UPDATE`) dentro del `OrdenesUoW`; (B) método nuevo con `FOR SHARE` en `clientes/repository.py`; (C) sin bloqueo (la FK no espera a una baja lógica: quedaría una orden abierta sobre un vehículo dado de baja). **Recomendado A**: cumple el contrato de C-10 sin tocar `clientes`; el costo es serializar altas del mismo vehículo.
- **S-03 — Orden de verificaciones y de bloqueo.** Catálogo (sin bloqueo) → vehículo (`FOR UPDATE`) → repuestos (`FOR SHARE`, ascendente) → total; orden global de D6 (orden existente → vehículo → repuestos ascendentes), que C-14 respeta bloqueando la orden antes de llamar al punto único. Alternativa: repuestos antes que vehículo — invierte el orden respecto de C-10 (vehículo) y abre la puerta a ciclos con futuros cambios. **Recomendado** como está (es también el orden del Flujo 4).
- **S-04 — Modo de bloqueo de los repuestos.** Opciones: (A) `FOR SHARE`; (B) `FOR KEY SHARE` (no espera a los `UPDATE` de stock, pero sólo protege mientras PATCH/DELETE tomen `FOR UPDATE` explícito); (C) `FOR UPDATE` (serializa altas que comparten repuestos). **Recomendado A**: lo acordado en C-11, robusto ante cómo escriba el otro, compatible entre altas.
- **S-05 — Respuesta del alta.** Opciones: (A) detalle con la forma exacta del ejemplo de la consigna (`id, estado, patente, total, creada_en, mecanico_id, falla, cliente, items[repuesto_id, codigo, descripcion, cantidad, precio_unitario, subtotal], historial[desde_estado, hasta_estado, usuario_id, cuando]`), releído con `OrdenTrabajoRepository.get_detalle` (3 consultas fijas) y armado por `armar_detalle`, ambos reutilizados por C-15 en `GET /ordenes/{id}`; (B) la misma forma armada en memoria con lo ya leído + una consulta por el nombre del cliente (C-15 tendría un segundo armado que puede divergir); (C) sólo `{id, estado, total}` (no cumple «respuesta con precios copiados, total y primer historial», US-050 / PDF C-10). **Recomendado A**: una sola forma y un solo armado para el alta y el detalle. Implica que C-15 reutiliza la precarga en lugar de crearla (ajuste de alcance en `CHANGES.md` al archivar). Sin `vehiculo_id` en la salida (no está en el ejemplo).
- **S-06 — `falla`.** Recorte, 1–500 caracteres (la columna no tiene largo). Alternativa: sin máximo. **Recomendado** acotar, como los demás textos del proyecto.
- **S-07 — Ítems.** 1–50 ítems; `cantidad` entera 1–1000; `repuesto_id`/`vehiculo_id` 1–2147483647; `extra="forbid"` también dentro del ítem; los ítems se guardan y se devuelven en el orden del cuerpo. Alternativas: sin tope de ítems (cuerpo arbitrariamente grande) o cantidad hasta `CANTIDAD_MAXIMA_MOVIMIENTO` (100 000, C-11). **Recomendado** como está: topes realistas para un taller y que mantienen el total lejos del desborde.
- **S-08 — Repuesto repetido.** Opciones: (A) 422 en el contrato (RN10: «Garante: DTO»); (B) 409 en el servicio; (C) sumar las cantidades. **Recomendado A**: es un error de forma del pedido, no un choque con datos; `uq_item_orden_orden_id_repuesto_id` queda de red.
- **S-09 — Vehículo inexistente o dado de baja.** Opciones: (A) 409 con un mismo mensaje para ambos; (B) 404 (no está en la matriz para `POST /ordenes`); (C) 422. **Recomendado A**: la matriz validada sólo da 201/409/422; el id viaja en el cuerpo, no en la ruta, y el repuesto inexistente también es 409 (PDF C-10).
- **S-10 — Varios repuestos inválidos.** Opciones: (A) un 409 con todos los ids que fallan, ascendentes; (B) sólo el primero por id. **Recomendado A**: la recepción corrige todo de una vez; determinista.
- **S-11 — Estado inicial y catálogo vacío.** Opciones: (A) el servicio usa `CodigoEstado.PENDIENTE` y verifica con `get_por_codigo` que exista (vacío o sin PENDIENTE → mismo 409 propio); (B) contar el catálogo y tomar el de menor `posicion`; (C) dejar que la FK falle (409 genérico, no «mensaje propio» de RN19). **Recomendado A**: el modelo declara el enum como vocabulario del servicio; una consulta por PK.
- **S-12 — Quién y cuándo en el historial.** `usuario_id` = el actor (RECEPCION o ADMIN; el ejemplo de la consigna muestra el id de la recepción del seed); `mecanico_id` nulo hasta `iniciar` (C-14); `creada_en` y `cuando` con el **mismo** `datetime.now(UTC)`. Alternativa: dos instantes (los `default_factory`), como el ejemplo. **Recomendado** un instante: la línea registra exactamente la creación.
- **S-13 — Cálculo del total.** En Python con `Decimal` (precios ya leídos bajo `FOR SHARE`), cuantizado a centavos; total > 9999999999.99 → 422 propio. Alternativas: `SUM` en SQL (otra consulta, mismo resultado) o dejar que `NUMERIC(12,2)` desborde (422 genérico). **Recomendado** como está.
- **S-14 — `GET /estados-orden` y `EstadoOrdenRepository`.** Arreglo simple de `{codigo, descripcion, posicion, es_final}` por `posicion`, cualquier autenticado (sin `requiere_rol`), vacío → `[]`; repositorio propio con sólo `listar()` y `get_por_codigo()` (no hereda de `BaseRepository`, así no expone `add/update/delete`). Alternativa: paginado o sólo códigos. **Recomendado** como está (matriz: 200; KB 08: repositorio de sólo lectura).
- **S-15 — Routers y roles.** Dos `APIRouter` (`/ordenes` sin rol de router, rol por ruta con `requiere_rol(RECEPCION, ADMIN)` creado una vez; `/estados-orden` sin rol), montados al final de `rutas_protegidas`. Alternativa: rol a nivel de router en `/ordenes` (obligaría a C-14/C-15 a routers paralelos para cancelar, terminar y el detalle). **Recomendado** como está.
- **S-16 — Estado conocido de `test/ordenes.http`.** Encabezado `psql`: `TRUNCATE historial_estado_orden, item_orden, movimiento_stock, historial_precio_repuesto, orden_trabajo, repuesto RESTART IDENTITY;` (sin `CASCADE`: falla si otra tabla los referenciara; vacía todas las órdenes y repuestos de desarrollo), después borrado de vehículos `ZO%`, de las fichas `460000xx` y de los usuarios `@ordenes.example.com` (eventos, intentos, roles, ficha, usuario) y el catálogo con `INSERT … ON CONFLICT DO NOTHING`. Personal por `/auth/registro` + `INSERT` de rol; repuestos por la API de C-11 (ids 1… por `RESTART IDENTITY`); vehículos por la API de C-10; catálogo vacío por `DELETE FROM estado_orden` antes de crear la primera orden y restaurado después. Alternativas: rangos únicos por corrida sin borrar (los usuarios quedan referenciados por el historial y el registro daría 409 en la segunda corrida); `DISABLE TRIGGER` + `DELETE` (apaga la protección). **Recomendado** `TRUNCATE`, como `test/repuestos.http` (C-11 S-14) y `seed.py`.
- **S-17 — Stock al crear.** Opciones: (A) no se valida (sólo al terminar, RN13; IN-04); (B) 409 si alguna cantidad supera el stock actual. **Recomendado A**: la consigna sólo exige stock al terminar y el seed tiene a propósito una orden que pide más de lo que hay; B rompería el caso PDF C-11.

## Notas para otros changes

**Mati (dueño de `app/modules/repuestos/*`, revisa propose y apply)**
- S-01: confirmar que C-13 agrega `listar_vigentes_para_orden` al final de `RepuestoRepository` (D4/D11) o elegir la alternativa B. C-12 no lo usa ni lo cambia.

**C-14 (iniciar, terminar, cancelar — Nico)**
- Reutilizar `OrdenesUoW` y `OrdenesUoWDep` tal cual (ya cumple `ConStock`). Agregar en `OrdenTrabajoRepository` un `get_para_actualizar(id)` con `FOR UPDATE` + `populate_existing` y tomarlo **primero** en el bloque (paso 1 de D6); después, si corresponde, `aplicar_movimientos_stock(uow, …, incluir_bajas=True)` (paso 3, el punto único ordena por id). Nunca bloquear un vehículo ni un repuesto antes que la orden.
- Transiciones guiadas por `uow.estados.get_por_codigo(...).es_final` y `CodigoEstado`; cada transición agrega una línea con `uow.historial.add(HistorialEstadoOrden(desde_estado=<anterior>, hasta_estado=<nuevo>, usuario_id=actor, cuando=datetime.now(UTC)))` (nunca `UPDATE`: sólo agregado).
- La respuesta de las transiciones puede reutilizar `get_detalle` + `armar_detalle` (misma forma que el alta).
- Después de `aplicar_movimientos_stock` (`synchronize_session=False`) las entidades `Repuesto` ya cargadas quedan con stock viejo: armar la respuesta releyendo la orden con `get_detalle`, que usa `populate_existing`, y nunca desde entidades cargadas antes del descuento (revisión FINAL_DIFF de C-13).
- `router_ordenes` no tiene rol de router: `iniciar` usa su propio `requiere_rol(Rol.MECANICO)`; `terminar` y `cancelar` no llevan `requiere_rol` (permiso en el servicio, 403 antes que 409).

**C-15 (lecturas — Nico propone, Lauti implementa)**
- `GET /ordenes/{id}` reutiliza `OrdenTrabajoRepository.get_detalle` (3 consultas fijas, D4) y `service.armar_detalle`; agrega la comprobación de personal o dueño (`vehiculo.cliente.usuario_id`, ya precargado) → 403/404. La evidencia PDF C-15 (2 vs 4 ítems, `SQL_ECHO=true`) mide ese método.
- `GET /ordenes` y `/mis-ordenes` necesitan una salida de listado propia (sin ítems ni historial) o la misma precarga con `selectinload` por página; el filtro `estado` se valida con `CodigoEstado` (422).
- `get_detalle` carga el repuesto de cada ítem aunque esté dado de baja y el vehículo aunque esté dado de baja (RN16: conservan sus datos).

**C-06 (seed — Lauti)**
- El catálogo se carga primero (sin `PENDIENTE` no hay órdenes). Las órdenes del seed deben dejar `total = SUM(cantidad × precio_unitario)`, `precio_unitario` igual al precio del repuesto al crearlas y una línea `null → PENDIENTE` (y para la #2, además `PENDIENTE → EN_REPARACION` con `mecanico_id`). Opcional: crear las órdenes con `service.alta` sobre un `OrdenesUoW` de su sesión.

**C-16 (integración — Lauti)**
- Integrar `test/ordenes.http`; su encabezado vacía órdenes y repuestos: correrlo después de `test/repuestos.http` o antes de `python seed.py`.

## Notas para el archivo

- **S-05**: en `CHANGES.md`, el alcance de C-15 pasa a «`GET /ordenes/{id}` reutiliza `get_detalle`/`armar_detalle` de C-13 y agrega permiso y evidencia».
- **S-03/D6**: agregar a KB `07_flujos_principales.md` Flujo 4 el orden de bloqueo (vehículo `FOR UPDATE` → repuestos `FOR SHARE` ascendentes) y a `09_decisiones_y_supuestos.md` DD-11 que el alta se serializa con la baja de vehículos y de repuestos por bloqueos de fila en orden global.
- **S-09/S-10**: anotar en KB `06_funcionalidades.md` US-050 que vehículo y repuestos inválidos responden 409 con mensaje propio (sin 404).
