# Design — C-12 repuestos-stock-precios

## Context

Motivación en proposal.md — Why; requisitos en `specs/parts-catalog` (acceso), `specs/stock-movements` (reposición y consulta de movimientos) y `specs/price-history` (consulta del historial). Estado actual relevante (C-11 archivado el 2026-10-29, design D1–D12 y S-01…S-16 confirmados):

- **Punto único (C-11 D4)**: `aplicar_movimientos_stock(uow: ConStock, movimientos: Sequence[MovimientoPedido], *, usuario_id: int, incluir_bajas: bool = False) -> dict[int, int]` en `app/modules/repuestos/service.py`. Se llama dentro de un `async with uow` ya abierto; por pedido hace `RepuestoRepository.sumar_stock` (`UPDATE … SET stock = stock + :delta WHERE id = :id AND borrado_en IS NULL AND stock + :delta >= 0 RETURNING stock`, `synchronize_session=False`) y el `INSERT` de `MovimientoStock`; si `sumar_stock` devuelve `None`, `leer_stock` decide `NoEncontrado` (404 `El repuesto no existe`) o `StockInsuficiente` (409). `_validar_pedidos` lanza `ValueError` ante cantidad 0, motivo vacío, lista vacía o repuesto repetido. Devuelve el stock resultante: la entidad `Repuesto` cargada **no** se actualiza.
- **Contratos (C-11 D3)**: `CANTIDAD_MAXIMA_MOVIMIENTO = 100_000` («C-12 lo reutiliza en `reponer`»), `RepuestoSalida(id, codigo, descripcion, precio: Decimal → "8500.00", stock)`, `EntradaBase` (`extra="forbid"`), `SalidaBase` (rechaza modelos de tabla y `password_hash`), `IdRuta` (1…INT4).
- **Repositorios (C-11 D5)**: `MovimientoStockRepository` e `HistorialPrecioRepository` sólo tienen constructor (`add()` heredado); el docstring del módulo dice «C-12 les agrega el listado». `RepuestoRepository.get_by_id` (de `SoftDeleteRepository`) lee sólo vigentes con `SELECT`, sin identity map.
- **UoW**: `RepuestosUoW` ya compone `repuestos`, `movimientos`, `historial_precios` sobre la misma sesión; `RepuestosUoWDep`. No cambia.
- **Router (C-11 D2, S-13)**: `router_admin_repuestos = APIRouter(prefix="/repuestos", dependencies=[Depends(solo_admin)])`, `AdminDep`; montado en `rutas_protegidas` por `main.py`. Las rutas nuevas se declaran en el mismo `router.py`, antes de que `main.py` lo importe e incluya: **`main.py` no cambia**. Starlette no confunde `/repuestos/{id}/movimientos` con `/repuestos/{id}` (un parámetro de ruta no cruza `/`).
- **Esquema**: `movimiento_stock` (`ix_movimiento_stock_repuesto_id`, `…_usuario_id`, `…_orden_id`; CHECK `cantidad <> 0`) e `historial_precio_repuesto` (`ix_historial_precio_repuesto_repuesto_id`, `…_usuario_id`) con disparador de sólo agregado (migración 2: `UPDATE`/`DELETE` → `P0001`; `TRUNCATE` no lo dispara). `repuesto.stock` es `INTEGER` con `ck_repuesto_stock_no_negativo`. Sin migraciones nuevas (REPARTO §7.6).
- **Errores (C-02)**: un `DBAPIError` con SQLSTATE `22xxx` (p. ej. `22003`, desborde de `INTEGER`) → 422 genérico `Algún valor está fuera del rango o del formato permitido`; nunca 500.
- **Referencia de listado**: `GET /eventos` (C-09) usa `PaginacionDep` + `Pagina[EventoSalida]` porque la consigna le da `(page, size)`; la consigna **no** se los da a `/movimientos` ni a `/precios`, y la matriz validada (KB 03) les da sólo 200/404 (`/eventos` lista 422).
- **Reparto**: `app/modules/repuestos/*` es de Mati (apply de C-12); `app/core/*` sólo lo toca Mati y este change no lo necesita. Nadie escribe `stock` fuera del punto único (REPARTO §9).

## Goals / Non-Goals

**Goals:**

- La reposición usa el punto único **tal cual** (sin cambiar su firma ni su cuerpo) y deja `stock = SUM(movimientos)`.
- Lecturas de historial con número fijo de consultas (sin N+1, sin carga perezosa), sólo con columnas de las propias tablas.
- Ningún cambio en `editar()`, `alta()`, `baja()`, `aplicar_movimientos_stock`, `sumar_stock`, `leer_stock`, `RepuestosUoW`, `main.py`, modelos, migraciones ni `app/core/*`.

**Non-Goals:**

- Salidas de stock por la API (ajustes negativos): sólo C-14, al terminar órdenes.
- Paginación, filtros por fecha o por motivo, correo o nombre del actor en los historiales.
- Historiales de repuestos dados de baja por la API (los datos siguen en la base: RN16).
- Evidencia completa del caso PDF C-12 (reponer **y terminar**): la terminación es de C-14.

## Decisions

### D1 — Archivos

| Archivo | Cambio |
|---------|--------|
| `app/modules/repuestos/schemas.py` | `LARGO_MAXIMO_MOTIVO`, `MOTIVO_REPOSICION`, tipos `CantidadReposicion`, `Motivo`; `ReposicionEntrada`, `MovimientoSalida`, `PrecioHistorialSalida`; docstring del módulo (S-01…S-03, S-08, S-09) |
| `app/modules/repuestos/repository.py` | `MovimientoStockRepository.listar_de_repuesto`, `HistorialPrecioRepository.listar_de_repuesto`; docstring del módulo («C-12 les agrega el listado» → hecho) |
| `app/modules/repuestos/service.py` | `_exigir_vigente`, `reponer`, `listar_movimientos`, `listar_precios` (al final del archivo; nada existente se modifica) |
| `app/modules/repuestos/router.py` | tres handlers en `router_admin_repuestos`; docstring del módulo |
| `test/stock.http` (nuevo) | casos del change (D7) |

### D2 — Rutas (S-12)

```python
# router.py — todas en router_admin_repuestos (solo_admin a nivel de router: una consulta de roles)
@router_admin_repuestos.post("/{repuesto_id}/reponer", status_code=200)
async def reponer(repuesto_id: IdRuta, datos: ReposicionEntrada, actual: AdminDep,
                  uow: RepuestosUoWDep) -> RepuestoSalida:
    return await service.reponer(uow, repuesto_id, datos, actual.id)

@router_admin_repuestos.get("/{repuesto_id}/movimientos")
async def listar_movimientos(repuesto_id: IdRuta, uow: RepuestosUoWDep) -> list[MovimientoSalida]:
    return await service.listar_movimientos(uow, repuesto_id)

@router_admin_repuestos.get("/{repuesto_id}/precios")
async def listar_precios(repuesto_id: IdRuta, uow: RepuestosUoWDep) -> list[PrecioHistorialSalida]:
    return await service.listar_precios(uow, repuesto_id)
```

- `status_code=200` explícito en el `POST` (la matriz da 200: no se crea un recurso direccionable, se modifica el repuesto).
- Orden de rechazos heredado (`access-control`): 401 → 403 cambio → 403 rol → 422 (ruta y cuerpo) → 404. Así un cuerpo inválido sobre un id inexistente da 422 y RECEPCION sobre un id inexistente da 403.

### D3 — Contratos (S-01, S-02, S-03, S-08, S-09)

```python
# schemas.py
LARGO_MAXIMO_MOTIVO = 200
MOTIVO_REPOSICION = "Reposición"          # motivo por defecto del movimiento de reposición

CantidadReposicion = Annotated[int, Field(ge=1, le=CANTIDAD_MAXIMA_MOVIMIENTO)]
Motivo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=LARGO_MAXIMO_MOTIVO)]

class ReposicionEntrada(EntradaBase):
    cantidad: CantidadReposicion
    motivo: Motivo = MOTIVO_REPOSICION     # ausente -> "Reposición"; null -> 422 (str no admite None)

class MovimientoSalida(SalidaBase):
    id: int
    cantidad: int                          # con signo: + entra, - sale (C-14)
    motivo: str
    orden_id: int | None
    usuario_id: int
    cuando: datetime                       # timestamptz -> ISO 8601 con zona

class PrecioHistorialSalida(SalidaBase):
    id: int
    precio_anterior: Decimal               # "8500.00" (NUMERIC(10,2) devuelve Decimal con 2 decimales)
    precio_nuevo: Decimal
    usuario_id: int
    cuando: datetime
```

- `cantidad` es entero en modo laxo, igual que `stock_inicial` de C-11 (`1.5`, `"abc"`, `null` → 422; `"5"` → 5). El tope reutiliza `CANTIDAD_MAXIMA_MOVIMIENTO`: no se duplica la constante.
- `extra="forbid"` da el 422 de `stock`, `orden_id` o `usuario_id` en el cuerpo sin código propio (RN14: no se fija stock por el cuerpo ni se simula una salida de orden).
- La cantidad siempre es positiva por contrato: el `ValueError` de `_validar_pedidos` (cantidad 0, motivo vacío) es inalcanzable desde el cliente.
- `repuesto_id` no va en las salidas de historial (está en la ruta) y `borrado_en` no aparece en ninguna.

### D4 — `POST /repuestos/{id}/reponer` (S-01, S-04)

```python
async def reponer(uow: RepuestosUoW, repuesto_id: int, datos: ReposicionEntrada,
                  usuario_id: int) -> RepuestoSalida:
    """Reposición (RN14): entrada positiva por el PUNTO ÚNICO; nunca escribe stock por su cuenta."""
    async with uow:
        stock = (await aplicar_movimientos_stock(
            uow, [MovimientoPedido(repuesto_id, datos.cantidad, datos.motivo)],
            usuario_id=usuario_id,                    # incluir_bajas=False: baja -> 404
        ))[repuesto_id]
        repuesto = await uow.repuestos.get_by_id(repuesto_id)   # fila ya bloqueada por el UPDATE
        if repuesto is None:                                    # defensivo: inalcanzable
            raise NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)
        salida = RepuestoSalida(id=repuesto_id, codigo=repuesto.codigo,
                                descripcion=repuesto.descripcion, precio=repuesto.precio,
                                stock=stock)                    # el stock DEVUELTO (C-11 Riesgos)
    return salida
```

- **Primero el punto único, después la lectura**: el 404 lo decide un solo lugar (el punto único con `incluir_bajas=False`, que ya distingue inexistente/dado de baja) y la lectura posterior encuentra la fila vigente porque el `UPDATE` la dejó bloqueada hasta el commit (una baja simultánea espera). Consultas: 2 de autorización + `UPDATE … RETURNING` + `INSERT` + `SELECT` (camino feliz); 2 + `UPDATE` (0 filas) + `leer_stock` (404).
- El `stock` de la salida es el devuelto por el punto único, no `repuesto.stock` (aunque aquí coinciden, porque la entidad se lee después del `UPDATE`, se sigue la regla de C-11 para no depender del identity map).
- No se captura nada dentro del bloque: `NoEncontrado` sale y el UoW revierte. `StockInsuficiente` es imposible con delta positivo.
- Concurrencia (heredada de C-11 D4.4): N reposiciones simultáneas se encolan en el bloqueo de la fila y se suman todas; reposición vs `PATCH` (que toma `FOR UPDATE` sobre la misma fila) o vs `DELETE` se serializan sin interbloqueo (una sola fila por transacción). Si la baja confirma primero, el `UPDATE` reevalúa `borrado_en IS NULL` → 0 filas → 404.
- *Alternativa descartada*: `get_vigente_para_actualizar` (FOR UPDATE) antes del punto único — una sentencia más en cada reposición y dos lugares que deciden el 404.
- *Alternativa descartada*: devolver el movimiento creado — el cliente tendría que pedir `GET /repuestos/{id}` para ver el stock, que es lo que importa al reponer (PDF C-12: reponer para poder terminar).

### D5 — Lecturas de historial (S-05, S-06, S-07)

```python
# repository.py
class MovimientoStockRepository(BaseRepository[MovimientoStock]):
    async def listar_de_repuesto(self, repuesto_id: int) -> list[MovimientoStock]:
        """Movimientos de un repuesto en orden de registro (id ascendente). Sin relaciones."""
        consulta = (self._consulta_base()
                    .where(col(MovimientoStock.repuesto_id) == repuesto_id)
                    .order_by(col(MovimientoStock.id)))
        return list((await self.session.exec(consulta)).all())

class HistorialPrecioRepository(BaseRepository[HistorialPrecioRepuesto]):
    async def listar_de_repuesto(self, repuesto_id: int) -> list[HistorialPrecioRepuesto]:
        # ídem sobre historial_precio_repuesto

# service.py
async def _exigir_vigente(uow: RepuestosUoW, repuesto_id: int) -> None:
    if await uow.repuestos.get_by_id(repuesto_id) is None:
        raise NoEncontrado(MENSAJE_REPUESTO_INEXISTENTE)

async def listar_movimientos(uow: RepuestosUoW, repuesto_id: int) -> list[MovimientoSalida]:
    async with uow:
        await _exigir_vigente(uow, repuesto_id)
        movimientos = await uow.movimientos.listar_de_repuesto(repuesto_id)
        salida = [MovimientoSalida.model_validate(m) for m in movimientos]
    return salida
# listar_precios: idem con uow.historial_precios y PrecioHistorialSalida
```

- Consultas fijas: 2 de autorización + existencia + lista, con 0 o con N filas. `WHERE repuesto_id = :id` usa `ix_movimiento_stock_repuesto_id` / `ix_historial_precio_repuesto_repuesto_id`; el `ORDER BY id` ordena pocas filas por repuesto. Parámetros ligados.
- Salida armada dentro del bloque; las entidades no tocan `repuesto` (relación `lazy="raise"`): sin carga perezosa.
- La existencia se verifica aparte para distinguir 404 (repuesto inexistente o dado de baja) de 200 `[]` (vigente sin filas). Ambas lecturas en la misma transacción.
- *Alternativa descartada*: una sola consulta con `JOIN repuesto` — no distingue «sin filas» de «no existe» sin una segunda lectura.
- *Alternativa descartada*: `Pagina[...]` con `PaginacionDep` como `/eventos` — agrega un 422 que la matriz no lista y la consigna no le da `(page, size)`; el historial de un repuesto es acotado en este dominio (Riesgos).

### D6 — Mensajes

Sin mensajes nuevos: 404 `El repuesto no existe` (`MENSAJE_REPUESTO_INEXISTENTE`), 401/403 de C-08, 422 de validación de Pydantic por campo y 422 genérico de rango (C-02).

### D7 — Verificación sin pytest (Strict TDD adaptado, como C-11 D12)

- **RED**: `test/stock.http` completo se escribe primero (tarea 1.1) y se corre contra el servidor actual: los casos de preparación y de `PATCH` (C-11) pasan; toda petición a `/reponer`, `/movimientos` y `/precios` → 404 `Not Found` (ruta inexistente). Se anota la línea de base.
- **GREEN**: cada tarea hace pasar su sección. **TRIANGULATE**: cada regla con al menos dos casos (acepta / rechaza, o dos motivos de rechazo). **Safety net**: `test/health.http`, `test/auth.http`, `test/sesion.http`, `test/personal.http`, `test/clientes.http`, `test/repuestos.http` y `test/verificar_security_core.py` antes de tocar código y al final.
- **Estado conocido de `test/stock.http` (S-10)**: el mismo encabezado `psql` que `test/repuestos.http` (`TRUNCATE item_orden, movimiento_stock, historial_precio_repuesto, repuesto RESTART IDENTITY;` y borrado de los usuarios del archivo), con correos `@stock.example.com`, documentos `45000001`–`45000004` (C-10 usa `430000xx`, C-11 `440000xx`) y códigos `STK-…`.
- Lo que un `.http` no muestra se comprueba con **un** script temporal `$env:TEMP\verificar_c12.py` (no versionado), con `httpx.AsyncClient(transport=ASGITransport(main.app))` dentro de `async with main.lifespan(main.app)` y sesiones propias de `app.state.session_factory`. Precondición: correr después de `test/stock.http` (login de `jefa@stock.example.com`), con repuestos propios `SCRIPT-C12-…` dados de alta por la API. Bloques:
  - (a) 20 `POST /reponer` simultáneos con cantidades 1…20 sobre un repuesto con stock 0 → 20 × 200, stock 210, 20 movimientos, nunca 500.
  - (b) `POST /reponer` y `DELETE` del mismo repuesto a la vez, 10 repuestos → cada par es (200, 204) o (404, 204); nunca 500; si 404, el repuesto no tiene movimiento de reposición.
  - (c) `POST /reponer` y `PATCH` de precio del mismo repuesto a la vez, 10 veces → ambos 200, nunca `40P01` ni 500; quedan el stock y el precio nuevos y una línea de historial por PATCH.
  - (d) Atomicidad: `service.reponer` con un `RepuestosUoW` (sesión propia) cuyo `movimientos.add` lanza `RuntimeError` → la excepción sale y el stock del repuesto no cambió (leído con otra sesión).
  - (e) Consultas emitidas (listener `before_cursor_execute`): `reponer` feliz = 2 de autorización + `UPDATE … RETURNING` + `INSERT INTO movimiento_stock` + `SELECT … FROM repuesto`; `reponer` 404 = 2 + `UPDATE` + `SELECT` de `leer_stock`, sin `INSERT`; `GET /movimientos` de un repuesto con 1 y con 5 movimientos → misma cantidad de sentencias (2 + 2); ídem `GET /precios` con 1 y con 3 líneas; el id viaja como parámetro ligado.
  - (f) Desborde: con una sesión propia se lleva el stock de `SCRIPT-C12-MAX` a 2 147 480 000 por `UPDATE` directo (excluido del invariante) y `POST /reponer` con 100 000 → 422 `Algún valor está fuera del rango o del formato permitido`, nunca 500, stock y movimientos sin cambios.
  - (g) `/openapi.json`: el cuerpo de `reponer` declara sólo `cantidad` (requerido, 1…100000) y `motivo` (opcional, por defecto «Reposición») y `additionalProperties: false`; la respuesta 200 de `reponer` es `RepuestoSalida`; las de `/movimientos` y `/precios` son arreglos de `MovimientoSalida` / `PrecioHistorialSalida` con exactamente los campos de D3; ninguna declara `borrado_en`.
  - (h) Invariante: para todo repuesto salvo `SCRIPT-C12-MAX`, `stock = COALESCE(SUM(cantidad), 0)`, y la suma de `GET /movimientos` coincide con el `stock` de `GET /repuestos/{id}`.

## Risks / Trade-offs

- [Historiales sin paginar] → un repuesto muy usado acumularía muchas filas en una respuesta. Mitigación: en un taller son decenas por repuesto; si creciera, se agrega `PaginacionDep` + `Pagina[...]` sin romper la ruta (cambio de contrato a documentar). Se acepta (S-05).
- [Desborde de `INTEGER` por reposiciones repetidas] → con 100 000 por llamada hacen falta ~21 000 reposiciones para desbordar; si ocurre, el manejador global responde 422 genérico y el UoW revierte (bloque f). Se acepta.
- [Historial de un repuesto dado de baja no visible por la API] → la auditoría de un repuesto discontinuado exige `psql`. Coherente con RN16 y con `GET /repuestos/{id}` → 404; si se necesitara, se cambia `_exigir_vigente` por `get_by_id_including_deleted` (S-07).
- [`usuario_id` sin correo] → quien lee el historial ve un id. Mitigación: `GET /usuarios/{id}/roles` (C-09) lo resuelve; agregar el correo exige un `JOIN` con una tabla de otro módulo (S-08).
- [`TRUNCATE` en el encabezado de `test/stock.http`] → vacía también los repuestos de `test/repuestos.http` y de cualquier dato de desarrollo; cada archivo es de una sola pasada sobre su propio estado conocido (mismo criterio que C-11 S-14). Correr uno después del otro exige su encabezado.
- [Script con `UPDATE` directo de `stock` (bloque f)] → rompe a propósito el invariante de un repuesto del script; queda fuera de `app/` y se limpia con el encabezado del `.http` (`TRUNCATE`).

## Migration Plan

Sin cambios de esquema ni de datos. Despliegue: los cuatro archivos del módulo + `test/stock.http`; reiniciar uvicorn. Rollback: revertir los cuatro archivos (los cambios son sólo agregados al final de cada uno) y borrar `test/stock.http`; las filas de prueba se limpian con el bloque `psql` de su encabezado o con `python seed.py` (C-06).

## Open Questions / Supuestos

Todos **confirmados por el usuario el 2026-10-30**, cada uno con la recomendación indicada. Cada uno con opciones, recomendación y por qué.

- **S-01 — Respuesta de `reponer`.** Opciones: (A) 200 con `RepuestoSalida` (mismo contrato del catálogo) y el stock resultante; (B) 200 con el movimiento creado (`MovimientoSalida`); (C) 200 con `{repuesto, movimiento}`; (D) 201. **Recomendado A**: lo que interesa al reponer es el stock nuevo (PDF C-12: reponer para poder terminar), no se inventa un tercer contrato y la matriz dice 200 (no se crea un recurso direccionable).
- **S-02 — Rango de `cantidad`.** Entero de 1 a `CANTIDAD_MAXIMA_MOVIMIENTO` (100 000, la constante de C-11), modo laxo como `stock_inicial`. Alternativa: sin tope (sólo `ge=1`) — el desborde de `INTEGER` llegaría antes por una sola llamada. **Recomendado** como está.
- **S-03 — `motivo`.** Opcional; por defecto «Reposición»; si viene, recortado, 1–200 caracteres; `null` → 422. Alternativa: obligatorio (la KB dice «con motivo») — más fricción para el caso PDF C-12 sin ganar nada: el movimiento siempre queda con motivo. **Recomendado** opcional con valor por defecto.
- **S-04 — Reponer un repuesto dado de baja.** 404 `El repuesto no existe` (`incluir_bajas=False`, como dejó anotado C-11). Alternativa: permitirlo — un repuesto fuera del catálogo con stock que sube no tiene uso (RN16: no se usa en órdenes nuevas). **Recomendado** 404.
- **S-05 — Paginación de `/movimientos` y `/precios`.** Lista JSON simple, completa, sin `page`/`size`. Alternativa: `Pagina[...]` como `/eventos` — la consigna sólo marca `(page, size)` en `/eventos`, `/repuestos`, `/ordenes` y `/mis-ordenes`, y la matriz validada no les da 422. **Recomendado** sin paginar.
- **S-06 — Orden.** Cronológico (`id` ascendente): se lee como un libro de movimientos (la suma acumulada llega al stock actual) y las líneas de precio quedan encadenadas `anterior → nuevo`. Alternativa: más reciente primero, como `/eventos` — natural en un listado paginado, pero aquí la lista es completa. **Recomendado** ascendente.
- **S-07 — Historiales de un repuesto dado de baja.** 404, igual que `GET /repuestos/{id}` (RN16: «deja de aparecer»); los datos se conservan en la base. Alternativa: visibles (auditoría) con `get_by_id_including_deleted`. **Recomendado** 404 por coherencia con el detalle y con `reponer`.
- **S-08 — Campos de `MovimientoSalida`.** `id`, `cantidad` (con signo), `motivo`, `orden_id` (nulo), `usuario_id`, `cuando`. Sin `repuesto_id` (está en la ruta) ni correo del actor (exigiría `JOIN` con `usuario`, de otro módulo; no hay N+1 que evitar si sólo se devuelve el id). Alternativa: agregar `usuario_email` con un `JOIN` en la misma consulta. **Recomendado** sin correo.
- **S-09 — Campos de `PrecioHistorialSalida`.** `id`, `precio_anterior`, `precio_nuevo` (texto `"8500.00"`, como `precio` del catálogo), `usuario_id`, `cuando`. **Recomendado**.
- **S-10 — Archivo de casos.** Nuevo `test/stock.http` (correos `@stock.example.com`, documentos `45000001`–`45000004`, códigos `STK-…`, encabezado `TRUNCATE` como `test/repuestos.http`). Alternativa: extender `test/repuestos.http` — más conflictos de merge y renumerar sus 91 casos. **Recomendado** archivo nuevo.
- **S-11 — Sin ajustes negativos por la API.** `reponer` sólo suma; las salidas son de C-14 (terminar). Alternativa: `cantidad` con signo o `POST /ajustar` — no están en la matriz ni en la consigna. **Recomendado** sólo positiva.
- **S-12 — Montaje.** Las tres rutas en `router_admin_repuestos` (una consulta de roles por petición, `main.py` sin cambios), `status_code=200` explícito en el `POST`. Alternativa: router propio `/repuestos/{id}/…` montado en `main.py` — otra línea en un archivo compartido sin beneficio. **Recomendado**.

## Notas para otros changes

**C-14 (terminar — Nico)**
- Las salidas que registre `aplicar_movimientos_stock` con cantidad negativa y `orden_id` aparecen en `GET /repuestos/{id}/movimientos` sin cambios en C-12 (`MovimientoSalida.cantidad` con signo, `orden_id` no nulo).
- Caso PDF C-12 en el `.http` de C-14: `POST /repuestos/{bujía}/reponer` `{"cantidad": 2}` (stock 2 → 4) y después terminar la orden #2 → 200; `GET /repuestos/{bujía}/movimientos` muestra la reposición (+2) y la salida (-4, `orden_id` 2).

**C-06 (seed — Lauti)**
- `MOTIVO_REPOSICION = "Reposición"` vive en `repuestos/schemas.py` si el seed quiere dejar reposiciones de ejemplo (siempre con `stock = SUM(cantidad)`).

## Notas para el archivo

- KB `06_funcionalidades.md` US-041 y US-042: marcar como cubiertos (US-042 se completa con C-11 + C-12).
- KB `03_actores_y_roles.md`: sin cambios (la matriz ya dice 200/404/422, 200/404, 200/404).
- Si se confirma S-05/S-06, anotar en KB `09_decisiones_y_supuestos.md` que los historiales por repuesto no se paginan y van en orden cronológico.
