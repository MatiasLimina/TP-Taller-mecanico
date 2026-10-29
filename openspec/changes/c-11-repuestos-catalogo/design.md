# Design — C-11 repuestos-catalogo

## Context

Motivación en proposal.md — Why; requisitos en `specs/parts-catalog`, `specs/stock-movements` y `specs/price-history`. Estado actual relevante:

- **Modelos (C-03)**: `app/modules/repuestos/models.py` tiene `Repuesto(id, codigo, descripcion, precio: Decimal(10,2), stock: int = 0 [server_default 0], borrado_en)`, `MovimientoStock(id, repuesto_id, orden_id | None, usuario_id [NOT NULL], cantidad, motivo, cuando)` y `HistorialPrecioRepuesto(id, repuesto_id, usuario_id [NOT NULL], precio_anterior, precio_nuevo, cuando)`. Relaciones `lazy="raise"`; `cuando` con `default_factory=ahora_utc`. Columnas de texto sin largo (`VARCHAR`).
- **Esquema (migración 1)**: índice único parcial `uq_repuesto_codigo (codigo) WHERE borrado_en IS NULL`; `ck_repuesto_precio_positivo`, `ck_repuesto_stock_no_negativo`, `ck_movimiento_stock_cantidad_no_nula`, `ck_historial_precio_repuesto_precio_nuevo_positivo`, `ck_historial_precio_repuesto_precio_distinto`; FKs con índice (`ix_movimiento_stock_repuesto_id`, `…_usuario_id`, `…_orden_id`, `ix_historial_precio_repuesto_*`). Sin índice sobre `descripcion`. No hace falta migración (y no se puede crear: REPARTO §7.6).
- **Sólo agregado (migración 2)**: `trg_solo_agregado` rechaza `UPDATE`/`DELETE` por fila en `movimiento_stock` e `historial_precio_repuesto` (`P0001`, el manejador global lo responde 500). `TRUNCATE` no lo dispara (spec `append-only-history`, «Vaciado completo para recarga»). Consecuencia para los `.http`: una fila de prueba en esas tablas no se puede borrar, y por FK tampoco el repuesto ni el usuario que la referencian (S-14).
- **Errores (C-02)**: el manejador global traduce `IntegrityError` 23505/23503 → 409 genérico y **23514 (CHECK) → 422 genérico**: un stock que choca con `ck_repuesto_stock_no_negativo` daría 422, no el 409 que pide RN13. Por eso el 409 de stock insuficiente lo decide el punto único de escritura (D4), y el CHECK queda como red.
- **Core**: `SoftDeleteRepository` (`_consulta_base()` filtra `borrado_en IS NULL`, `get_by_id_including_deleted`, `soft_delete` con `datetime.now(UTC)` + `flush()`), `_contar`, `UnitOfWork` (no se abre dos veces; no se cierra la sesión), `PaginacionDep`/`Pagina`/`verificar_pagina`/`armar_pagina`, `IdRuta`, `EntradaBase`/`SalidaBase`, `NoEncontrado`/`Conflicto`, `restriccion_violada`, `requiere_rol`. `get_session` con `expire_on_commit=False`. Sólo Mati modifica `app/core/*` (REPARTO §9): este change no lo toca.
- **Patrón de referencia**: módulo `usuarios` (C-09: `requiere_rol` una vez a nivel de router, salida armada dentro del bloque, `IntegrityError` traducido fuera) y C-10 en su rama (`get_vigente_para_actualizar` con `FOR UPDATE` + `populate_existing` para la baja lógica).
- **Sin seed (C-06 sin mergear)**: los `.http` se preparan con `/auth/registro` + `INSERT` de roles por `psql`, como `test/personal.http`.
- **Consigna**: «el stock se escribe en un único punto (RN-14), que usan la reposición y la terminación de órdenes»; «no se evalúa la concurrencia (cap. 7)» (y KB DD-11 acepta la actualización perdida). El ejemplo de listado de la consigna muestra `"precio": "8500.00"` (texto).

## Goals / Non-Goals

**Goals:**

- Módulo `repuestos` completo con la estructura obligatoria y el patrón de C-09/C-10, sin tocar `core`, modelos, migraciones ni otros módulos (salvo el montaje en `main.py`).
- Un punto único de escritura de stock con contrato **cerrado y documentado** que C-12 y C-14 usan tal cual, sin anidar Unit of Work, sin interbloqueos y con 409 propio y rollback total cuando no alcanza.
- RN20 completo desde el primer PATCH que acepta precio (sin ventana sin historial).
- Búsqueda con parámetros ligados y comodines escapados; número fijo de consultas por listado.

**Non-Goals:**

- Rutas de C-12 (`reponer`, `movimientos`, `precios`), descuento por órdenes (C-14), `seed.py` (C-06).
- Reactivar repuestos, listar bajas, cambiar el código, búsqueda difusa o con índice trigram (exigiría migración).
- Serializar la alta de órdenes contra la baja de repuestos: lo resuelve C-13 con el bloqueo que se le deja anotado.

## Decisions

### D1 — Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/modules/repuestos/schemas.py` (nuevo) | constantes de contrato, tipos `Codigo`, `Descripcion`, `Precio`, `CantidadInicial`; `RepuestoAltaEntrada`, `RepuestoEdicionEntrada`, `RepuestoSalida` |
| `app/modules/repuestos/repository.py` (nuevo) | `RepuestoRepository(SoftDeleteRepository[Repuesto])`, `FilaStock`, `MovimientoStockRepository`, `HistorialPrecioRepository` |
| `app/modules/repuestos/unit_of_work.py` (nuevo) | `RepuestosUoW`, `get_repuestos_uow`, `RepuestosUoWDep` |
| `app/modules/repuestos/service.py` (nuevo) | **punto único** (`MovimientoPedido`, `StockInsuficiente`, `ConStock`, `aplicar_movimientos_stock`); `listar`, `detalle`, `alta`, `editar`, `baja`; mensajes |
| `app/modules/repuestos/router.py` (nuevo) | `router_catalogo` (lectura) y `router_admin_repuestos` (escritura) |
| `main.py` | import y `rutas_protegidas.include_router(...)` de los dos routers **antes** de `app.include_router(rutas_protegidas)` |
| `test/repuestos.http` (nuevo) | casos del change (D12) |

### D2 — Rutas, roles y montaje (S-13)

```python
# router.py
personal_repuestos = requiere_rol(Rol.ADMIN, Rol.RECEPCION, Rol.MECANICO)   # UNA función
solo_admin = requiere_rol(Rol.ADMIN)                                        # UNA función
AdminDep = Annotated[UsuarioActual, Depends(solo_admin)]
Busqueda = Annotated[str | None, Query(max_length=LARGO_MAXIMO_BUSQUEDA)]

router_catalogo = APIRouter(prefix="/repuestos", tags=["repuestos"], dependencies=[Depends(personal_repuestos)])
router_admin_repuestos = APIRouter(prefix="/repuestos", tags=["repuestos"], dependencies=[Depends(solo_admin)])

@router_catalogo.get("")
async def listar(pag: PaginacionDep, uow: RepuestosUoWDep, q: Busqueda = None) -> Pagina[RepuestoSalida]
@router_catalogo.get("/{repuesto_id}")
async def detalle(repuesto_id: IdRuta, uow: RepuestosUoWDep) -> RepuestoSalida
@router_admin_repuestos.post("", status_code=201)
async def alta(datos: RepuestoAltaEntrada, actual: AdminDep, uow: RepuestosUoWDep) -> RepuestoSalida
@router_admin_repuestos.patch("/{repuesto_id}")
async def editar(repuesto_id: IdRuta, datos: RepuestoEdicionEntrada, actual: AdminDep, uow: RepuestosUoWDep) -> RepuestoSalida
@router_admin_repuestos.delete("/{repuesto_id}", status_code=204)
async def baja(repuesto_id: IdRuta, uow: RepuestosUoWDep) -> None
```

- Dos `APIRouter` con el mismo prefijo: cada petición pasa por **una sola** consulta de roles (una ruta de escritura no paga `personal_repuestos` + `solo_admin`). Starlette, ante `PATCH /repuestos/{id}`, encuentra primero la coincidencia parcial del `GET` y sigue hasta la ruta `PATCH` del segundo router: no hay conflicto. C-12 cuelga sus rutas de `router_admin_repuestos`.
- Los servicios reciben `actual.id` (`usuario_id: int`), no `UsuarioActual` (como C-10): `repuestos.service` no depende de `usuarios.service`.
- Orden de rechazos heredado (`access-control`): 401 → 403 cambio → 403 rol → 422 → 404 → 409.

### D3 — Contratos (S-04, S-05, S-06, S-07, S-12)

```python
LARGO_MAXIMO_CODIGO = 30
LARGO_MAXIMO_DESCRIPCION = 200
LARGO_MAXIMO_BUSQUEDA = 100
CANTIDAD_MAXIMA_MOVIMIENTO = 100_000            # tope por movimiento; C-12 lo reutiliza en reponer
PATRON_CODIGO = r"^[A-Z0-9]+(-[A-Z0-9]+)*$"     # FIL-ACE-01, BUJ-01, ACE-5W30-1L, FRE-010
CENTAVO = Decimal("0.01")

def _a_centavos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO)              # 8500 -> 8500.00: la salida del alta = la del GET

Codigo = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1,
                                          max_length=LARGO_MAXIMO_CODIGO, pattern=PATRON_CODIGO)]
Descripcion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LARGO_MAXIMO_DESCRIPCION)]
Precio = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2), AfterValidator(_a_centavos)]
CantidadInicial = Annotated[int, Field(ge=0, le=CANTIDAD_MAXIMA_MOVIMIENTO)]

class RepuestoAltaEntrada(EntradaBase):
    codigo: Codigo
    descripcion: Descripcion
    precio: Precio
    stock_inicial: CantidadInicial = 0

class RepuestoEdicionEntrada(EntradaBase):
    descripcion: Descripcion | None = None
    precio: Precio | None = None

    @field_validator("descripcion", "precio", mode="before")
    @classmethod
    def _no_nulo(cls, valor: object) -> object:
        # Sólo corre si el campo vino en el cuerpo: `null` explícito -> 422 sobre ese campo;
        # ausente -> no está en model_fields_set y `exclude_unset` lo omite.
        if valor is None:
            raise ValueError("El campo no puede ser nulo")
        return valor

class RepuestoSalida(SalidaBase):
    id: int
    codigo: str
    descripcion: str
    precio: Decimal          # Pydantic v2 lo serializa como texto: "8500.00"
    stock: int
```

- `extra="forbid"` (de `EntradaBase`) da el 422 de `stock` en el alta y de `stock`/`codigo` en el PATCH sin código propio (RN14, PDF C-16).
- `StringConstraints` aplica recorte y mayúsculas **antes** de largo y patrón (se verifica en la tarea 2.1; si no fuera así, `BeforeValidator` con `strip().upper()`).
- `NaN`/`Infinity` se rechazan (Pydantic no los admite en `Decimal` por defecto); un precio fuera de `NUMERIC(10,2)` no llega a la base. Los CHECK quedan de red (422 genérico, nunca 500).

### D4 — Punto único de escritura de stock (RN14) (S-01, S-02, S-15, S-16)

**Dónde**: `app/modules/repuestos/service.py`, función `aplicar_movimientos_stock`, sobre dos métodos de repositorio. Es el **único** código de `app/` que escribe `repuesto.stock` (`RepuestoRepository.sumar_stock`) y el único que inserta en `movimiento_stock`.

```python
# service.py
MOTIVO_STOCK_INICIAL = "Stock inicial"      # mismo texto que seed.py (C-06)

@dataclass(frozen=True, slots=True)
class MovimientoPedido:
    repuesto_id: int
    cantidad: int                 # con signo, != 0: positivo entra, negativo sale (SU-04)
    motivo: str
    orden_id: int | None = None   # C-14: la orden que termina

class StockInsuficiente(Conflicto):           # 409 por el manejador global (ErrorDeAplicacion)
    def __init__(self, codigo: str, disponible: int, requerido: int) -> None:
        super().__init__(MENSAJE_STOCK_INSUFICIENTE.format(codigo=codigo, disponible=disponible, requerido=requerido))
        self.codigo, self.disponible, self.requerido = codigo, disponible, requerido

class ConStock(Protocol):                     # lo cumplen RepuestosUoW y el OrdenesUoW de C-13/C-14
    repuestos: RepuestoRepository
    movimientos: MovimientoStockRepository

async def aplicar_movimientos_stock(
    uow: ConStock,
    movimientos: Sequence[MovimientoPedido],
    *,
    usuario_id: int,
    incluir_bajas: bool = False,
) -> dict[int, int]:                          # repuesto_id -> stock resultante
    """PUNTO ÚNICO DE ESCRITURA DE STOCK (RN14). Ver design C-11 D4.

    Se llama DENTRO de un `async with uow` que abrió el servicio llamador; nunca abre,
    confirma ni revierte. Si lanza, el llamador deja salir la excepción del bloque y el UoW
    revierte TODO (stock, movimientos y cualquier otra escritura de esa transacción).
    """
    _validar_pedidos(movimientos)             # ValueError: lista vacía, cantidad 0, motivo vacío, repuesto repetido
    resultado: dict[int, int] = {}
    for pedido in sorted(movimientos, key=lambda m: m.repuesto_id):     # orden de bloqueo fijo
        stock = await uow.repuestos.sumar_stock(pedido.repuesto_id, pedido.cantidad, incluir_bajas=incluir_bajas)
        if stock is None:
            fila = await uow.repuestos.leer_stock(pedido.repuesto_id)
            if fila is None or (fila.borrado_en is not None and not incluir_bajas):
                raise NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)
            raise StockInsuficiente(fila.codigo, fila.stock, -pedido.cantidad)
        await uow.movimientos.add(MovimientoStock(
            repuesto_id=pedido.repuesto_id, orden_id=pedido.orden_id, usuario_id=usuario_id,
            cantidad=pedido.cantidad, motivo=pedido.motivo))
        resultado[pedido.repuesto_id] = stock
    return resultado
```

```python
# repository.py — RepuestoRepository
async def sumar_stock(self, repuesto_id: int, delta: int, *, incluir_bajas: bool = False) -> int | None:
    """ÚNICA escritura de `repuesto.stock` en app/ (la llama sólo `aplicar_movimientos_stock`).

    UPDATE repuesto SET stock = stock + :delta
     WHERE id = :id [AND borrado_en IS NULL] AND stock + :delta >= 0
    RETURNING stock
    None = ninguna fila (no existe, dada de baja sin `incluir_bajas`, o no alcanza).
    synchronize_session=False: una entidad Repuesto ya cargada en la sesión queda con el
    stock viejo; usar el valor devuelto o releer con populate_existing.
    """

async def leer_stock(self, repuesto_id: int) -> FilaStock | None:
    """SELECT codigo, stock, borrado_en (columnas, no entidad: sin identity map ni bajas filtradas)."""
```

Contrato (lo que C-12 y C-14 pueden asumir):

1. **Firma**: `await aplicar_movimientos_stock(uow, [MovimientoPedido(...), ...], usuario_id=actor.id, incluir_bajas=False) -> dict[int, int]`.
2. **Reutilización sin anidar**: recibe cualquier UoW **ya abierto** que exponga `repuestos: RepuestoRepository` y `movimientos: MovimientoStockRepository` sobre su misma sesión. El `OrdenesUoW` de C-13/C-14 declara esos dos atributos; no construye ni abre un `RepuestosUoW`.
3. **Atomicidad**: por cada pedido, un `UPDATE` condicional + un `INSERT` de `movimiento_stock` (siempre, en la misma transacción). Ante el primer pedido que no alcanza lanza `StockInsuficiente` (409 `Stock insuficiente para el repuesto <CODIGO>: hay <N> y se necesitan <M>`); repuesto inexistente (o dado de baja con `incluir_bajas=False`) → `NoEncontrado` (404 `El repuesto no existe`). El llamador **no** captura esas excepciones dentro del bloque: salen y el UoW revierte todo.
4. **Concurrencia**: el `UPDATE … WHERE stock + :delta >= 0` toma el bloqueo de la fila y, en READ COMMITTED, si otra transacción la cambió, PostgreSQL reevalúa la condición sobre la versión confirmada: no hay actualización perdida ni stock negativo, sin `SELECT … FOR UPDATE` previo ni reintentos.
5. **Orden de bloqueo**: los pedidos se aplican en orden ascendente de `repuesto_id` (dentro de la función), así dos terminaciones con los mismos repuestos en distinto orden no se interbloquean. Un llamador que además bloquee otras filas (C-14: la orden) las bloquea **antes** de llamar.
6. **Validaciones de programación** (`ValueError`, nunca llegan del cliente porque los contratos ya las filtran): lista vacía, `cantidad == 0` (lo rechazaría `ck_movimiento_stock_cantidad_no_nula`), `motivo` vacío, el mismo `repuesto_id` dos veces en una llamada.
7. **`incluir_bajas`**: `False` (alta, reposición) exige repuesto vigente; `True` lo usa sólo C-14 para terminar órdenes creadas antes de la baja del repuesto (S-11).

- *Alternativa descartada*: `SELECT … FOR UPDATE` de los repuestos en orden de id + comparar en Python + `stock = nuevo`. Correcto, pero dos sentencias por repuesto y la carga de entidades en el identity map; el `UPDATE` condicional hace lo mismo en una.
- *Alternativa descartada*: no proteger (DD-11: «se acepta la actualización perdida»). La consigna no evalúa la concurrencia, pero el `UPDATE` condicional cuesta lo mismo que el ingenuo y, además, es lo que convierte la falta de stock en 409 propio en lugar del 422 genérico del CHECK.
- *Alternativa descartada*: método en el repositorio que también lance el 409 — un repositorio no conoce errores de aplicación ni mensajes (convención de `errores.py`).
- *Alternativa descartada*: archivo nuevo `stock.py` — se aparta de la estructura obligatoria del módulo.

### D5 — Repositorios (S-08, S-09)

```python
class FilaStock(NamedTuple):
    codigo: str
    stock: int
    borrado_en: datetime | None

class RepuestoRepository(SoftDeleteRepository[Repuesto]):
    def _filtrada(self, q: str | None) -> SelectOfScalar[Repuesto]:
        consulta = self._consulta_base()                          # vigentes
        if q:
            patron = f"%{_escapar_like(q)}%"                      # valor ligado, nunca SQL
            consulta = consulta.where(or_(col(Repuesto.descripcion).ilike(patron, escape="\\"),
                                          col(Repuesto.codigo).ilike(patron, escape="\\")))
        return consulta
    async def contar(self, q: str | None) -> int:                 # self._contar(self._filtrada(q))
    async def listar(self, q: str | None, *, offset: int, limit: int) -> list[Repuesto]:
        # self._filtrada(q).order_by(col(Repuesto.id)).offset(offset).limit(limit)
    async def get_vigente_para_actualizar(self, id: int) -> Repuesto | None:
        # _consulta_base().where(id == :id).with_for_update().execution_options(populate_existing=True)
    async def sumar_stock(...) -> int | None                      # D4
    async def leer_stock(self, id: int) -> FilaStock | None       # D4

def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

class MovimientoStockRepository(BaseRepository[MovimientoStock]): ...      # add(); C-12 agrega el listado
class HistorialPrecioRepository(BaseRepository[HistorialPrecioRepuesto]): ...  # add(); C-12 agrega el listado
```

- Índices: PK de `repuesto` (detalle, bloqueo, `UPDATE`); el filtro `ILIKE '%…%'` recorre la tabla (catálogo chico, sin migraciones; Riesgos). `uq_repuesto_codigo` decide la unicidad.
- Las entidades se leen sin relaciones: ninguna salida toca `items`, `movimientos` ni `historial_precios` (sin carga perezosa).
- `RepuestosUoW(UnitOfWork)`: `self.repuestos`, `self.movimientos`, `self.historial_precios`, todos con la misma sesión; `get_repuestos_uow(session: SessionDep)`; `RepuestosUoWDep`. Cumple `ConStock`.

### D6 — `POST /repuestos` (S-04)

```python
try:
    async with uow:
        repuesto = await uow.repuestos.add(Repuesto(codigo=datos.codigo, descripcion=datos.descripcion, precio=datos.precio))
        assert repuesto.id is not None
        stock = 0
        if datos.stock_inicial > 0:      # 0 no deja movimiento (ck cantidad <> 0; SUM = 0 = stock)
            stock = (await aplicar_movimientos_stock(
                uow, [MovimientoPedido(repuesto.id, datos.stock_inicial, MOTIVO_STOCK_INICIAL)],
                usuario_id=usuario_id))[repuesto.id]
        salida = _salida(repuesto, stock=stock)      # stock devuelto, no el atributo (synchronize_session=False)
except IntegrityError as exc:
    if restriccion_violada(exc) == "uq_repuesto_codigo":
        raise Conflicto(MENSAJE_CODIGO_REPETIDO.format(codigo=datos.codigo)) from None   # del DTO, no de la entidad
    raise
return salida
```

El repuesto nace con `stock` 0 y el stock inicial entra por el punto único: el `INSERT` nunca fija stock. Sin consulta previa del código (RN01): dos altas simultáneas → el índice decide (201 + 409).

### D7 — `GET /repuestos` (S-08, S-09)

Flujo de `paginacion.py`: `q = q.strip() or None` si vino → `total = contar(q)` → `verificar_pagina` → `listar(q, offset, limit)` → `armar_pagina([RepuestoSalida.model_validate(r) …])`, todo en un bloque. `PaginacionDep` y `Query(max_length=100)` dan el 422 sin consultar la base. Consultas: 2 de autorización + 2 (conteo y página), fijas.

### D8 — `GET /repuestos/{id}` (S-10)

Un bloque: `get_by_id` (de `SoftDeleteRepository`, sólo vigentes) → `None` → `NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)`; salida dentro del bloque.

### D9 — `PATCH /repuestos/{id}` con historial de precios (S-03, S-12)

```python
async with uow:
    repuesto = await uow.repuestos.get_vigente_para_actualizar(repuesto_id)   # FOR UPDATE + populate_existing
    if repuesto is None:
        raise NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)
    cambios = datos.model_dump(exclude_unset=True)
    precio_anterior = repuesto.precio
    if "precio" in cambios and cambios["precio"] == precio_anterior:
        del cambios["precio"]                     # mismo precio: sin línea (RN20; CHECK precio_distinto de red)
    if cambios:
        await uow.repuestos.update(repuesto, cambios)
    if "precio" in cambios:
        assert repuesto.id is not None
        await uow.historial_precios.add(HistorialPrecioRepuesto(
            repuesto_id=repuesto.id, usuario_id=usuario_id,
            precio_anterior=precio_anterior, precio_nuevo=cambios["precio"]))
    salida = RepuestoSalida.model_validate(repuesto)
return salida
```

- El bloqueo serializa dos PATCH de precio simultáneos (el segundo lee el precio que confirmó el primero: historial encadenado) y un PATCH contra una baja simultánea (el que espera reevalúa `borrado_en IS NULL` → 404). `populate_existing` evita usar una versión vieja del identity map.
- El bloqueo de la fila no interbloquea con el punto único: ambos toman **una** fila de `repuesto` en la transacción del PATCH.
- `BaseRepository.update` rechaza claves que no son campos (`ValueError`): `exclude_unset` sólo trae `descripcion`/`precio`.

### D10 — `DELETE /repuestos/{id}` (S-11)

Un bloque: `get_vigente_para_actualizar` → `None` → 404 → `soft_delete(repuesto)`. Sin regla de órdenes abiertas ni de stock (la matriz da 204/404). Dos bajas simultáneas: la segunda espera el bloqueo, reevalúa y no encuentra la fila → 404.

### D11 — Mensajes

| Situación | Código | `detail` |
|-----------|--------|----------|
| Repuesto de la ruta inexistente o dado de baja | 404 | `El repuesto no existe` |
| Código vigente repetido (también por la carrera del índice) | 409 | `Ya existe un repuesto vigente con el código <CODIGO>` |
| Stock insuficiente (punto único; C-11 no lo expone por HTTP) | 409 | `Stock insuficiente para el repuesto <CODIGO>: hay <N> y se necesitan <M>` |
| Campo `null` en el PATCH | 422 | lista por campo con `El campo no puede ser nulo` |
| Sin sesión / cambio pendiente / sin rol | 401 / 403 / 403 | mensajes de C-08 |

### D12 — Verificación sin pytest (Strict TDD adaptado, como C-09 D9)

- **RED**: `test/repuestos.http` completo se escribe primero (tarea 1.1) y se corre contra el servidor actual: toda ruta `/repuestos…` → 404. Se anota la línea de base.
- **GREEN**: cada grupo de tareas hace pasar su sección del `.http`. **TRIANGULATE**: cada regla con al menos dos casos (acepta / rechaza, o dos motivos de rechazo). **Safety net**: `test/health.http`, `test/auth.http`, `test/sesion.http`, `test/personal.http` y `test/verificar_security_core.py` antes de tocar `main.py` y al final.
- Lo que un `.http` no muestra se comprueba con **un** script temporal `$env:TEMP\verificar_c11.py` (no versionado), con `httpx.AsyncClient(transport=ASGITransport(main.app))` dentro de `async with main.lifespan(main.app)` y sesiones propias de `app.state.session_factory`. Precondición: correr después de `test/repuestos.http` (usa a `jefa@repuestos.example.com` como `usuario_id`), con códigos `SCRIPT-C11-…`. Bloques: (a) punto único, dos salidas simultáneas de 3 sobre stock 5, forzando la superposición (otra conexión toma `SELECT … FOR UPDATE` de la fila, se lanzan las dos transacciones, se suelta) → una confirma y otra `StockInsuficiente`, stock 2, un movimiento -3; repetido 20 veces sin forzar → nunca stock negativo, nunca 500; (b) dos entradas simultáneas +4/+6 → 10 y dos movimientos; (c) dos transacciones con `[A:-1, B:-1]` y `[B:-1, A:-1]` repetidas 20 veces → nunca `40P01`; (d) `[A:-1, B:-999]` → `StockInsuficiente` con el código de B, A sin cambios y sin movimientos tras el rollback; (e) `ValueError` para lista vacía, cantidad 0, motivo vacío y repuesto repetido; `incluir_bajas`: sobre un repuesto dado de baja, `False` → `NoEncontrado`, `True` → aplica; (f) alta atómica: con un `RepuestosUoW` cuyo `movimientos.add` lanza, no queda el repuesto; PATCH atómico: con `historial_precios.add` que lanza, el precio no cambia; (g) dos `POST` simultáneos del mismo código → 201 + 409; dos `PATCH` de precio simultáneos → historial encadenado; dos `DELETE` simultáneos → 204 + 404; (h) con `SQL_ECHO=true` (o listener `before_cursor_execute`): `GET /repuestos?q=…` emite 2 consultas de autorización + conteo + página con el texto como parámetro ligado (nunca dentro del SQL); (i) `/openapi.json`: ninguna respuesta de `/repuestos` declara `borrado_en`; el cuerpo del alta no declara `stock` y el del PATCH sólo `descripcion`/`precio`; (j) invariante: para todo repuesto, `stock = COALESCE(SUM(cantidad), 0)`.

## Risks / Trade-offs

- [Búsqueda `ILIKE '%…%'` sin índice] → recorre la tabla; el catálogo de un taller es chico. Un índice trigram exigiría una migración (prohibida). Se acepta.
- [Entidad con stock viejo tras `sumar_stock`] → `synchronize_session=False` deja una instancia ya cargada con el valor anterior. Mitigación: el punto único devuelve el stock resultante y el docstring lo advierte; C-11 arma la salida del alta con ese valor; C-12 debe hacer lo mismo en `reponer`.
- [Terminar órdenes con repuestos dados de baja] → con `incluir_bajas=True` C-14 descuenta stock de un repuesto que ya no está en el catálogo. Es lo buscado (la orden se creó cuando estaba vigente y RN16 dice que la baja conserva los datos); si se prefiere impedirlo, C-14 pasa `False` y responde 404/409 (S-11).
- [Carrera alta de orden vs baja de repuesto] → sin bloqueo en C-13, una orden podría crearse con un repuesto dado de baja en el mismo instante. Mitigación anotada para C-13: leer los repuestos de la orden con `FOR SHARE` en orden de id (la baja toma `FOR UPDATE`).
- [`BaseRepository.update/delete` disponibles en los repositorios de sólo agregado] → nadie los llama; si alguien lo hiciera, el disparador responde `P0001` (500). Se acepta (mismo criterio que C-04).
- [Datos de prueba que no se pueden borrar] → `movimiento_stock` e `historial_precio_repuesto` no admiten `DELETE`; el encabezado de `test/repuestos.http` usa `TRUNCATE` del dominio repuestos (S-14), que vacía también los repuestos de otros datos de desarrollo. Mismo criterio que `seed.py` («vacía la base antes de cada archivo de pruebas»).
- [`CANTIDAD_MAXIMA_MOVIMIENTO` arbitrario] → 100 000 por movimiento evita desbordes de `INTEGER` por la API; si se desbordara igual, el manejador global responde 422 genérico (dato fuera de rango), nunca 500.

## Migration Plan

Sin cambios de esquema ni de datos. Despliegue: archivos nuevos del módulo + `main.py` + `test/repuestos.http`; reiniciar uvicorn. Rollback: revertir `main.py` y borrar los cinco archivos del módulo; las filas de prueba se limpian con el bloque `psql` del encabezado de `test/repuestos.http` o con `python seed.py` (C-06).

## Open Questions / Supuestos

Todos los supuestos fueron **confirmados por el usuario el 2026-10-29**, cada uno con la recomendación indicada. Cada uno con opciones, recomendación y por qué.

- **S-01 — Ubicación y forma del punto único de escritura.** Opciones: (A) función de servicio `aplicar_movimientos_stock(uow: ConStock, pedidos, *, usuario_id, incluir_bajas)` sobre `RepuestoRepository.sumar_stock` + `MovimientoStockRepository.add` (D4); (B) método de repositorio que actualiza y registra el movimiento (no puede lanzar el 409 propio sin conocer errores de aplicación); (C) servicio que abre su propio `RepuestosUoW` (anidaría UoW cuando lo llame C-14). **Recomendado A**: un solo lugar escribe stock y movimientos, se reutiliza desde el UoW abierto de otro módulo sin anidar, y el 409 vive en la capa de servicio.
- **S-02 — Estrategia de concurrencia y orden de bloqueo.** Opciones: (A) `UPDATE` atómico condicional `stock + :delta >= 0 … RETURNING`, pedidos en orden ascendente de `repuesto_id`; (B) `SELECT … FOR UPDATE` en orden de id + cálculo en Python; (C) sin protección (DD-11). **Recomendado A**: una sentencia, sin actualización perdida ni negativos, sin interbloqueos con el orden fijo; la consigna no evalúa concurrencia, pero A no cuesta más que C y además da el 409 propio (el CHECK daría 422 genérico). Implica actualizar DD-11 en la KB al archivar.
- **S-03 — Historial de precios en el PATCH de C-11.** Opciones: (A) C-11 ya escribe `historial_precio_repuesto` cuando el precio cambia (D9) y C-12 sólo agrega `GET /repuestos/{id}/precios`; (B) C-11 acepta el precio sin historial y C-12 lo agrega (ventana en la que un cambio de precio no deja línea, viola RN20); (C) C-11 rechaza `precio` hasta C-12 (contradice el alcance de C-11 y PDF C-16). **Recomendado A**: no hay ventana sin historial, RN20 queda en un solo bloque desde el primer día y C-12 no reabre `editar()` (menos conflictos en `service.py`). Exige quitar «Extensión del PATCH» del alcance de C-12 en `CHANGES.md` (lo hace quien archiva; ambos los implementa Mati).
- **S-04 — `stock_inicial`.** Opcional, por defecto 0, entero 0–100 000 (`CANTIDAD_MAXIMA_MOVIMIENTO`, compartido con `reponer` de C-12); con 0 no hay movimiento (el CHECK `cantidad <> 0` lo impide y `SUM = 0 = stock`); `motivo` «Stock inicial» (= `MOTIVO_STOCK_INICIAL` del seed); `usuario_id` = el ADMIN. Alternativa: obligatorio y ≥ 1 (todo repuesto nace con movimiento) — impide catalogar un repuesto sin existencias. **Recomendado** como está.
- **S-05 — Código.** Recorte + mayúsculas; 1–30 caracteres `^[A-Z0-9]+(-[A-Z0-9]+)*$` (admite los códigos del seed y de la consigna: `FIL-ACE-01`, `ACE-5W30-1L`, `FRE-010`); el código no se edita (no está en el PATCH). Alternativa: texto libre sin normalizar — `fil-ace-01` y `FIL-ACE-01` serían dos repuestos distintos para `uq_repuesto_codigo`. **Recomendado** normalizar.
- **S-06 — Precio.** `Decimal` > 0, hasta 10 dígitos y 2 decimales (= `NUMERIC(10,2)`), cuantizado a centavos; en JSON se acepta número o texto y se devuelve texto `"8500.00"` (como el ejemplo de la consigna y el `total` de C-13). Alternativa: devolver número (`PlainSerializer(float)`) — pierde exactitud. **Recomendado** texto.
- **S-07 — Descripción.** Recorte, 1–200 caracteres. Sin unicidad. **Recomendado**.
- **S-08 — Búsqueda `q`.** Contiene, sin distinguir mayúsculas, sobre `descripcion` **o** `codigo` (la consigna y US-040 dicen «por descripción»); `%`, `_` y `\` escapados (`ESCAPE '\'`); recorte; vacío → sin filtro; > 100 caracteres → 422. Alternativa: sólo descripción (literal de la consigna). **Recomendado** ambos: el código es lo que se busca en un mostrador y no cambia ningún caso de la consigna (`' OR '1'='1` sigue vacío porque ningún código admite espacios ni comillas).
- **S-09 — Orden del listado.** `id` ascendente (default de `data-repositories`, estable para paginar, como el ejemplo de la consigna). Alternativa: por `codigo` o `descripcion`. **Recomendado** id.
- **S-10 — Visibilidad.** Los tres roles ven la misma salida, con `stock` (el mecánico necesita saber si puede terminar; recepción, si conviene abrir la orden); `borrado_en` nunca se expone; un repuesto dado de baja da 404 en el detalle (RN16: «deja de aparecer»). **Recomendado**.
- **S-11 — Baja de un repuesto con stock u órdenes.** La matriz validada da sólo 204/404: la baja se acepta con stock y aunque haya órdenes PENDIENTE/EN_REPARACION que lo usan; conserva stock, movimientos e historial; el código queda libre. Esas órdenes se pueden terminar: C-14 llama al punto único con `incluir_bajas=True`. C-13 rechaza repuestos dados de baja en órdenes nuevas (RN16). Alternativa: 409 si hay órdenes abiertas (como vehículos) — no está en la matriz. **Recomendado** como está.
- **S-12 — Semántica del PATCH.** `{}` → 200 sin cambios ni historial; `null` explícito → 422 por campo; mismo precio → 200 sin línea; `FOR UPDATE` + `populate_existing`. Alternativa: `{}` → 422 («nada para actualizar») — más estricto, pero el PATCH vacío es idempotente y la matriz lo admite como 200. **Recomendado** 200.
- **S-13 — Routers y roles.** Dos `APIRouter` con prefijo `/repuestos` (lectura: ADMIN/RECEPCION/MECANICO; escritura: ADMIN), cada `requiere_rol` creado una vez; una sola consulta de roles por petición. Alternativa: un router con el rol de lectura y `AdminDep` por ruta — consulta roles dos veces en las escrituras. **Recomendado** dos routers.
- **S-14 — Preparación de `test/repuestos.http`.** Encabezado `psql`: `TRUNCATE item_orden, movimiento_stock, historial_precio_repuesto, repuesto RESTART IDENTITY;` (sin `CASCADE`: falla si otra tabla los referenciara) y después el borrado de los usuarios `@repuestos.example.com` (eventos, intentos, roles, ficha, usuario); personal por `/auth/registro` + `INSERT` de rol (jefa ADMIN, recepción RECEPCION, mecánico MECANICO), documentos `44000001`–`44000004` (C-10 usa `43…`). Alternativas: códigos únicos por corrida (`{{$timestamp}}`) sin borrar nada — los usuarios no se podrían borrar (FK desde `movimiento_stock`) y el registro daría 409 en la segunda corrida; `DISABLE TRIGGER` + `DELETE` — apaga la protección. **Recomendado** `TRUNCATE`, mismo mecanismo que `seed.py` y que la spec `append-only-history` reserva para recargar el estado inicial.
- **S-15 — Mensaje y tipo del stock insuficiente.** `StockInsuficiente(Conflicto)` en `repuestos/service.py` con `codigo`, `disponible`, `requerido` (C-14 puede reutilizar el mensaje o capturarla **fuera** del bloque para uno propio); texto `Stock insuficiente para el repuesto <CODIGO>: hay <N> y se necesitan <M>`. Alternativa: `Conflicto` genérico — C-14 no podría distinguirlo de otros 409. **Recomendado**.
- **S-16 — Alcance de la implementación del punto único en C-11.** C-11 implementa el contrato **completo** (orden, varios pedidos, `incluir_bajas`, 404/409) aunque por HTTP sólo use «Stock inicial», y lo verifica con el script (D12 a–e). Alternativa: sólo lo necesario para el alta y que C-12/C-14 completen — dejaría el contrato sin probar y repartido entre tres changes. **Recomendado** completo.

## Notas para otros changes

**C-12 (reponer, movimientos, precios — Mati)**
- `POST /repuestos/{id}/reponer` en `router_admin_repuestos`: dentro de un `async with uow` del `RepuestosUoW`, `stock = (await aplicar_movimientos_stock(uow, [MovimientoPedido(id, +cantidad, motivo)], usuario_id=actual.id))[id]`; `incluir_bajas=False` da el 404 de un repuesto dado de baja; la cantidad del contrato va de 1 a `CANTIDAD_MAXIMA_MOVIMIENTO`. La salida usa el `stock` devuelto (no `repuesto.stock`, que puede estar viejo). Nunca escribir `stock` por otra vía.
- `GET /repuestos/{id}/movimientos` y `/precios`: agregar el listado a `MovimientoStockRepository` / `HistorialPrecioRepository` (los historiales usan `movimientos`/`historial_precios` del UoW ya existente).
- Con S-03 confirmado, el PATCH ya escribe el historial: C-12 no toca `editar()`; su caso PDF C-18 sólo agrega la lectura de `/precios`.

**C-13 (alta de orden — Nico)**
- `OrdenesUoW` compone `self.repuestos = RepuestoRepository(session)` y `self.movimientos = MovimientoStockRepository(session)` (cumple `ConStock` para C-14). Para validar repuestos vigentes y copiar `precio`, agregar a `RepuestoRepository` (coordinar con Mati, dueño del archivo) un método que lea los repuestos pedidos **vigentes** en una consulta, en orden de id y con `FOR SHARE`: serializa con la baja (`FOR UPDATE`, D10) y sigue el mismo orden de bloqueo que el punto único.

**C-14 (terminar — Nico)**
- En el `async with uow` de terminar: bloquear primero la orden (`FOR UPDATE`), validar permiso (403) y estado (409), y luego `await aplicar_movimientos_stock(uow, [MovimientoPedido(i.repuesto_id, -i.cantidad, f"Orden #{orden.id} terminada", orden_id=orden.id) for i in items], usuario_id=actual.id, incluir_bajas=True)`. No capturar `StockInsuficiente` dentro del bloque: el UoW revierte stock, movimientos y cualquier cambio de estado (RN13, PDF C-11). `BackgroundTasks` se agenda después del bloque.
- PDF C-11 (orden #2: 4 bujías con stock 2) responde 409 `Stock insuficiente para el repuesto <código de la bujía>: hay 2 y se necesitan 4`.
- Nunca `repuesto.stock = …`, `uow.repuestos.update(…, {"stock": …})` ni `MovimientoStock(...)` fuera del punto único (REPARTO §9).
- El «hay N» del 409 sale de `leer_stock`, una lectura aparte del `UPDATE` fallido: con concurrencia puede mostrar el stock que dejó otra transacción, o volverse 404 si el repuesto se dio de baja en el medio. No afecta el rollback. Si C-14 necesita el número exacto, `leer_stock` puede leer con `FOR SHARE`.

**C-06 (seed — Lauti)**
- El seed escribe filas directamente (no pasa por servicios): su stock inicial debe dejar `stock = SUM(cantidad)` con `motivo` «Stock inicial» (= `MOTIVO_STOCK_INICIAL`). Opcional: usar `aplicar_movimientos_stock` con un `RepuestosUoW` sobre su sesión para no duplicar la regla.

## Notas para el archivo

- **S-02**: actualizar KB `09_decisiones_y_supuestos.md` DD-11: la actualización perdida de stock queda evitada por el `UPDATE` condicional del punto único (sin bloqueo explícito ni reintentos).
- **S-03**: quitar «Extensión del PATCH… historial» del alcance de C-12 en `CHANGES.md` (queda «`GET /repuestos/{id}/precios`»); KB `07` Flujo 7 sigue valiendo.
- **S-08**: KB `06` US-040 dice «búsqueda por descripción»: anotar que también busca por código.
