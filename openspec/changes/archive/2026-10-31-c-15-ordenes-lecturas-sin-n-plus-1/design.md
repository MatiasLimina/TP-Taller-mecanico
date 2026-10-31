# Design — C-15 ordenes-lecturas-sin-n-plus-1

## Context

Motivación y alcance: ver `proposal.md`. Requisitos: `specs/work-orders/spec.md` (delta, sólo ADDED).

Estado de `main` (`e6f9afc`) que este change reutiliza sin modificar:

- `OrdenTrabajoRepository.get_detalle(id)` (C-13): **3 SELECT fijos** — 1) la orden con `joinedload(vehiculo).joinedload(cliente)`, 2) `selectinload(items).joinedload(repuesto)`, 3) `selectinload(historial)` — con `populate_existing`; carga vehículo y repuesto aunque estén dados de baja (RN16). Sin filas en el primer SELECT no emite los otros dos.
- `service.armar_detalle(orden) -> OrdenDetalleSalida` (C-13): la salida del alta y de las transiciones; sólo lee relaciones precargadas por `get_detalle`.
- `service._roles_vigentes(uow, usuario_id)` (C-14): roles vigentes leídos en la base dentro del bloque (RN04), 1 SELECT; `uow.asignaciones` ya está en `OrdenesUoW`.
- `router_ordenes` (`/ordenes`) **sin** rol de router (C-13 S-15): el rol va por ruta. Ya está montado en `main.py`; `router_estados` también.
- `app/core/paginacion.py` (C-09): `PaginacionDep`, `verificar_pagina`, `armar_pagina`, `Pagina[T]`; patrón de `repuestos/service.listar` (contar → verificar → listar → armar). `BaseRepository._contar` cuenta con los mismos filtros que la página.
- Modelos con `lazy="raise"`: leer una relación no precargada lanza (sería un 500), así que una salida que muestra `patente` o `cliente` exige la precarga en el método del repositorio (PDF Ej. 8: «toda respuesta que incluya datos de una relación los obtiene con carga anticipada declarada en el repositorio»).
- Índices existentes (migración 1): PK `orden_trabajo.id`, `ix_orden_trabajo_estado`, `ix_orden_trabajo_vehiculo_id`, `ix_vehiculo_cliente_id`, `uq_cliente_usuario_id` (UNIQUE: indexa `cliente.usuario_id`), PK de `vehiculo` y `cliente`. No se puede crear ninguno (REPARTO §7.6).
- `seed.py` (C-06): con `TRUNCATE … RESTART IDENTITY` los ids son deterministas (ver D8). Hay órdenes de 2 ítems (#1) y de 1 ítem (#2); ninguna de 4.
- FastAPI (comprobado en una app aislada con la versión instalada): un parámetro `estado: CodigoEstado | None` responde 422 `type: "enum"` sobre `["query", "estado"]` para `REABIERTA`, `pendiente` y `estado=` (vacío); repetido (`estado=A&estado=B`) toma el último. Una dependencia que lanza (sesión, cambio pendiente, rol) responde antes que los 422 de parámetros, porque FastAPI junta los errores de validación y los lanza al final.

## Goals / Non-Goals

**Goals:**
- Tres lecturas con forma, permisos y orden de rechazos cerrados, implementables tarea por tarea por un modelo chico copiando el código de este documento.
- Contrato de consultas medible por petición (D6) y evidencia C-15 reproducible y versionada para C-16.
- Cero cambios en código de C-13/C-14 y en `app/core/*`: sólo agregados al final de cada archivo.

**Non-Goals:**
- Optimizar `get_detalle` (3 SELECT) ni unificarlo con el listado.
- Paginación por cursor, `ORDER BY` configurable, filtros extra, `estado` en `/mis-ordenes`.
- Ocultar la existencia de una orden ajena (se responde 403, no 404: C-14 S-07).

## Decisions

### D1 — Archivos

| Archivo | Cambio (sólo agregados) |
|---------|-------------------------|
| `app/modules/ordenes/schemas.py` | `OrdenResumenSalida` al final; un párrafo en el docstring |
| `app/modules/ordenes/repository.py` | import de `contains_eager` y `SelectOfScalar`; seis miembros al final de `OrdenTrabajoRepository` (D4); un párrafo en el docstring |
| `app/modules/ordenes/service.py` | imports de paginación y `OrdenResumenSalida`; bloque «Lecturas (C-15)» al final del archivo (D5) |
| `app/modules/ordenes/router.py` | imports; `lectura_ordenes`, `FiltroEstado`, `router_mis_ordenes` y tres rutas al final (D2); un párrafo en el docstring |
| `main.py` | `router_mis_ordenes` en el import de órdenes y `rutas_protegidas.include_router(router_mis_ordenes)` después de la de `router_estados`; comentario «C-15: lecturas de órdenes y mis-órdenes» |
| `test/lecturas_ordenes.http` (nuevo) | casos numerados (D8) |
| `test/evidencia_c15.txt` (nuevo, generado) | evidencia del caso PDF C-15 (D9-a) |

No se tocan: `unit_of_work.py` (ya tiene `ordenes` y `asignaciones`), `models.py`, `get_detalle`, `get_para_actualizar`, `get_usuario_dueno`, `armar_detalle`, `alta`, las transiciones, `app/core/*`, migraciones, `seed.py`, otros módulos y `.http`.

### D2 — Rutas, permisos y orden de rechazos (S-06, S-07, S-10, S-16)

```python
# router.py — al final del archivo (los imports nuevos van arriba, con los existentes)
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from app.core.paginacion import Pagina, PaginacionDep
from app.modules.ordenes.models import CodigoEstado
from app.modules.ordenes.schemas import EstadoOrdenSalida, OrdenAltaEntrada, OrdenDetalleSalida, OrdenResumenSalida

lectura_ordenes = requiere_rol(Rol.RECEPCION, Rol.ADMIN, Rol.MECANICO)  # UNA función (C-15)
FiltroEstado = Annotated[CodigoEstado | None, Query()]

router_mis_ordenes = APIRouter(prefix="/mis-ordenes", tags=["ordenes"])


@router_ordenes.get("", dependencies=[Depends(lectura_ordenes)])
async def listar_ordenes(
    pag: PaginacionDep, uow: OrdenesUoWDep, estado: FiltroEstado = None
) -> Pagina[OrdenResumenSalida]:
    return await service.listar_ordenes(uow, pag, estado)


@router_ordenes.get("/{orden_id}")
async def detalle_orden(
    orden_id: IdRuta, actual: UsuarioActualDep, uow: OrdenesUoWDep
) -> OrdenDetalleSalida:
    return await service.detalle_orden(uow, orden_id, actual.id)


@router_mis_ordenes.get("")
async def mis_ordenes(
    pag: PaginacionDep, actual: UsuarioActualDep, uow: OrdenesUoWDep
) -> Pagina[OrdenResumenSalida]:
    return await service.mis_ordenes(uow, pag, actual.id)
```

- `GET /ordenes`: el handler no necesita al actor, por eso el rol va en `dependencies=` de la ruta. Orden: 401 → 403 (cambio pendiente, del grupo) → 403 (rol) → 422 (`estado`, `page`, `size`) → operación.
- `GET /ordenes/{orden_id}`: sin `requiere_rol` (el dueño no tiene rol de personal); el permiso lo decide el servicio con los roles vigentes. Orden: 401 → 403 (cambio pendiente) → 422 (`IdRuta`) → 404 → 403 (sin relación). Mismo criterio que `cancelar` (C-14 S-07).
- `GET /mis-ordenes`: router propio (prefijo distinto de `/ordenes`), montado en `rutas_protegidas` como `router_mis_vehiculos` (C-10). Orden: 401 → 403 (cambio pendiente) → 422 → operación. No declara `estado`: un `?estado=…` se ignora (FastAPI no rechaza parámetros no declarados).
- `exigir_password_al_dia` NO se repite: ya está en el grupo protegido.

Párrafo a agregar al final del docstring de `router.py` (texto literal):

> Lecturas (C-15): `GET /ordenes` exige RECEPCION, ADMIN o MECANICO vigentes con `lectura_ordenes` en `dependencies=` de la ruta (el handler no usa al actor): 401 -> 403 (cambio pendiente) -> 403 (rol) -> 422 (`estado`, `page`, `size`). `GET /ordenes/{orden_id}` no lleva `requiere_rol`: personal o dueño del vehículo lo decide el servicio, 401 -> 403 (cambio pendiente) -> 422 -> 404 -> 403. `GET /mis-ordenes` (`router_mis_ordenes`, montado en `main.py`) sólo pide sesión y filtra siempre por el usuario de la sesión (RN17).

### D3 — Contrato de salida del resumen (S-02)

```python
# schemas.py — al final
class OrdenResumenSalida(SalidaBase):
    id: int
    estado: str
    patente: str
    total: Decimal
    creada_en: datetime
    mecanico_id: int | None
    falla: str
    cliente: str
```

Mismos campos y mismo orden que `OrdenDetalleSalida` sin `items` ni `historial`: un elemento del listado se lee igual que la cabecera del detalle. `total` sale como texto (`"56500.00"`, Pydantic v2) y `creada_en` con zona. No se deriva de `OrdenDetalleSalida` ni al revés (no se toca C-13). Párrafo para el docstring del módulo (literal): «`OrdenResumenSalida` (C-15) es un elemento de `GET /ordenes` y `GET /mis-ordenes`: la cabecera del detalle, sin ítems ni historial; lo arma `service.armar_resumen` desde una orden con el vehículo y su cliente precargados.»

### D4 — Repositorio (S-03, S-04, S-09, S-10)

```python
# repository.py — imports
from sqlalchemy.orm import contains_eager, joinedload, selectinload
from sqlmodel.sql.expression import SelectOfScalar

# al final de OrdenTrabajoRepository (después de get_usuario_dueno)

    # -- Lecturas (C-15): sin bloqueo, la página en UNA consulta con vehículo y cliente --

    def _filtrada_por_estado(self, estado: str | None) -> SelectOfScalar[OrdenTrabajo]:
        """Todas las órdenes, o sólo las de `estado` (usa `ix_orden_trabajo_estado`)."""
        consulta = self._consulta_base()
        if estado is not None:
            consulta = consulta.where(col(OrdenTrabajo.estado) == estado)
        return consulta

    async def contar_por_estado(self, estado: str | None) -> int:
        """`total` del listado del personal, con el mismo filtro que la página."""
        return await self._contar(self._filtrada_por_estado(estado))

    async def listar_resumen(
        self, estado: str | None, *, offset: int, limit: int
    ) -> list[OrdenTrabajo]:
        """Página de órdenes de la más nueva a la más vieja (id descendente, por la PK).

        UNA sentencia para cualquier tamaño de página: el vehículo y su cliente llegan por JOIN
        (`joinedload`, relaciones muchos-a-uno), aunque el vehículo esté dado de baja (RN16).
        """
        consulta = (
            self._filtrada_por_estado(estado)
            .options(joinedload(OrdenTrabajo.vehiculo).joinedload(Vehiculo.cliente))
            .order_by(col(OrdenTrabajo.id).desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.exec(consulta)).unique().all())

    def _de_usuario(self, usuario_id: int) -> SelectOfScalar[OrdenTrabajo]:
        """Órdenes de los vehículos de la ficha del usuario, también los dados de baja (RN17)."""
        return (
            self._consulta_base()
            .join(Vehiculo, col(Vehiculo.id) == col(OrdenTrabajo.vehiculo_id))
            .join(Cliente, col(Cliente.id) == col(Vehiculo.cliente_id))
            .where(col(Cliente.usuario_id) == usuario_id)
        )

    async def contar_de_usuario(self, usuario_id: int) -> int:
        """`total` de `/mis-ordenes`, con el mismo filtro que la página."""
        return await self._contar(self._de_usuario(usuario_id))

    async def listar_resumen_de_usuario(
        self, usuario_id: int, *, offset: int, limit: int
    ) -> list[OrdenTrabajo]:
        """Página de `/mis-ordenes` en UNA sentencia: `contains_eager` llena vehículo y cliente
        con los mismos JOIN del filtro (sin un segundo JOIN con alias)."""
        consulta = (
            self._de_usuario(usuario_id)
            .options(contains_eager(OrdenTrabajo.vehiculo).contains_eager(Vehiculo.cliente))
            .order_by(col(OrdenTrabajo.id).desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.exec(consulta)).unique().all())
```

- SQL esperado (compilado con el dialecto de PostgreSQL y comprobado): `listar_resumen` → `FROM orden_trabajo LEFT OUTER JOIN vehiculo AS vehiculo_1 … LEFT OUTER JOIN cliente AS cliente_1 … [WHERE orden_trabajo.estado = $1] ORDER BY orden_trabajo.id DESC LIMIT … OFFSET …`; `listar_resumen_de_usuario` → `FROM orden_trabajo JOIN vehiculo ON … JOIN cliente ON … WHERE cliente.usuario_id = $1 ORDER BY orden_trabajo.id DESC …` (un solo `JOIN vehiculo`, sin `vehiculo_1`); `_contar` → `SELECT count(*) FROM (…) AS anon_1`.
- Sin `with_for_update` ni `populate_existing`: es sólo lectura en una sesión de petición que no tiene órdenes en el identity map (la de `autenticar` sólo cargó el usuario). `.unique()` por consistencia con `get_detalle` (no hace falta con muchos-a-uno, no cambia el resultado).
- Índices: PK (orden descendente), `ix_orden_trabajo_estado`, `uq_cliente_usuario_id`, `ix_vehiculo_cliente_id`, `ix_orden_trabajo_vehiculo_id`; PK de `vehiculo`/`cliente` para los JOIN. Ninguno nuevo.
- `get_detalle` se usa tal cual para el detalle. `get_usuario_dueno` no se usa (S-08).

Párrafo para el docstring del módulo (literal): «Lecturas (C-15): `listar_resumen` y `listar_resumen_de_usuario` traen la página con el vehículo y su cliente en UNA sentencia (muchos-a-uno), en orden de id descendente, y `contar_por_estado`/`contar_de_usuario` cuentan con el mismo filtro (`_contar`). Ninguna lectura bloquea filas. El detalle reutiliza `get_detalle`.»

### D5 — Servicio (S-05, S-07, S-08, S-11, S-15)

```python
# service.py — imports nuevos
from app.core.paginacion import Pagina, Paginacion, armar_pagina, verificar_pagina
from app.modules.ordenes.schemas import (..., OrdenResumenSalida)   # agregar al import existente

# -- Lecturas (C-15) — al final del archivo ---------------------------------------------------
# Personal que ve cualquier orden (matriz: «el personal»); además ve el detalle el dueño (RN17).
ROLES_DE_PERSONAL = frozenset({Rol.RECEPCION.value, Rol.ADMIN.value, Rol.MECANICO.value})
MENSAJE_SIN_PERMISO_VER = "Sólo el personal del taller o el dueño del vehículo puede ver la orden"


def armar_resumen(orden: OrdenTrabajo) -> OrdenResumenSalida:
    """Elemento de un listado desde una orden con el vehículo y su cliente precargados
    (`listar_resumen` o `listar_resumen_de_usuario`); no lee ítems ni historial."""
    return OrdenResumenSalida(
        id=orden.id,  # type: ignore[arg-type]
        estado=orden.estado,
        patente=orden.vehiculo.patente,
        total=orden.total,
        creada_en=orden.creada_en,
        mecanico_id=orden.mecanico_id,
        falla=orden.falla,
        cliente=orden.vehiculo.cliente.nombre,
    )


async def listar_ordenes(
    uow: OrdenesUoW, pag: Paginacion, estado: CodigoEstado | None
) -> Pagina[OrdenResumenSalida]:
    """Listado del personal (el rol lo exige el router), de la más nueva a la más vieja.
    Contar primero evita traer filas de una página que da 422."""
    filtro = estado.value if estado is not None else None
    async with uow:
        total = await uow.ordenes.contar_por_estado(filtro)
        verificar_pagina(pag, total)
        ordenes = await uow.ordenes.listar_resumen(filtro, offset=pag.offset, limit=pag.size)
        items = [armar_resumen(o) for o in ordenes]
    return armar_pagina(items, total, pag)


async def detalle_orden(uow: OrdenesUoW, orden_id: int, usuario_id: int) -> OrdenDetalleSalida:
    """Detalle para el personal o el dueño del vehículo: 404 antes que 403 (C-14 S-07).

    Reutiliza `get_detalle` (3 SELECT fijos) y `armar_detalle` de C-13. Los roles se leen en la
    base en el mismo bloque (RN04), siempre: 5 sentencias por petición con cualquier cantidad
    de ítems. El dueño es el usuario de la ficha del cliente del vehículo, ya precargada,
    también si el vehículo está dado de baja (C-14 S-08). Sólo lectura: sin bloqueos.
    """
    async with uow:
        orden = await uow.ordenes.get_detalle(orden_id)
        if orden is None:
            raise NoEncontrado(MENSAJE_ORDEN_INEXISTENTE)  # 404 antes que el permiso
        roles = await _roles_vigentes(uow, usuario_id)
        es_personal = not roles.isdisjoint(ROLES_DE_PERSONAL)
        if not es_personal and orden.vehiculo.cliente.usuario_id != usuario_id:
            raise SinPermiso(MENSAJE_SIN_PERMISO_VER)
        salida = armar_detalle(orden)  # dentro del bloque, con todo precargado
    return salida


async def mis_ordenes(
    uow: OrdenesUoW, pag: Paginacion, usuario_id: int
) -> Pagina[OrdenResumenSalida]:
    """Órdenes de los vehículos propios (RN17); el filtro es SIEMPRE el usuario de la sesión.
    Sin ficha o sin vehículos: página vacía."""
    async with uow:
        total = await uow.ordenes.contar_de_usuario(usuario_id)
        verificar_pagina(pag, total)
        ordenes = await uow.ordenes.listar_resumen_de_usuario(
            usuario_id, offset=pag.offset, limit=pag.size
        )
        items = [armar_resumen(o) for o in ordenes]
    return armar_pagina(items, total, pag)
```

- El servicio no conoce HTTP: lanza `NoEncontrado`/`SinPermiso` (ya importados) y recibe `usuario_id`, no `UsuarioActual`.
- `MENSAJE_ORDEN_INEXISTENTE` («La orden no existe») se reutiliza (C-14).
- La salida se arma **dentro** del bloque. No hay `IntegrityError` posible (no se escribe nada), así que no hay `try/except`.
- `verificar_pagina` lanza `EntradaInvalida` dentro del bloque: el Unit of Work revierte una transacción vacía y el 422 sale igual.

### D6 — Consultas por petición (S-17)

Sentencias SQL por petición (listener `before_cursor_execute`; `BEGIN`/`COMMIT` y el ping del pool no pasan por el cursor y no cuentan). «Sesión» = 1 SELECT de `autenticar`; «rol» = 1 SELECT de `requiere_rol`.

| Petición | Sesión | Rol | Servicio | **Total** |
|----------|--------|-----|----------|-----------|
| `GET /ordenes` (cualquier página válida, con o sin `estado`, 0…N órdenes) | 1 | 1 | `count` 1 + página 1 | **4** |
| `GET /ordenes?page=<inexistente>` | 1 | 1 | `count` 1 | 3 (422) |
| `GET /ordenes/{id}` existente (200 o 403), con N ítems | 1 | — | detalle 3 + roles 1 | **5** |
| `GET /ordenes/{id}` inexistente | 1 | — | detalle 1 (sin filas no hay precargas) | 2 (404) |
| `GET /mis-ordenes` (0…N órdenes) | 1 | — | `count` 1 + página 1 | **3** |

El contrato del PDF es la **igualdad** (2 vs 4 ítems; 1 vs N órdenes); los totales de la tabla son lo esperado. Ninguna sentencia de estas rutas es `INSERT`, `UPDATE`, `DELETE` ni lleva `FOR UPDATE`/`FOR SHARE`; los ids y el estado viajan como parámetros ligados.

### D7 — Mensajes (S-15)

| Caso | Código | `detail` |
|------|--------|----------|
| Orden inexistente | 404 | `La orden no existe` (existente, C-14) |
| Ni personal ni dueño | 403 | `Sólo el personal del taller o el dueño del vehículo puede ver la orden` (nuevo) |
| Sin rol en `GET /ordenes` | 403 | `No tiene permiso para realizar esta operación` (de `requiere_rol`) |
| Página inexistente | 422 | `La página N no existe: hay M` (de `verificar_pagina`) |
| `estado`, `page`, `size`, id inválidos | 422 | error de validación de FastAPI (lista con `loc`) |

### D8 — Estado conocido y casos `.http` (S-12)

`test/lecturas_ordenes.http` usa como estado conocido **`python seed.py` inmediatamente antes** (vacía las 13 tablas con `RESTART IDENTITY` y recarga): el archivo es re-ejecutable volviendo a correr el seed. Ids deterministas:

- Usuarios: 1 `admin@example.com` (ADMIN), 2 `admin2@`, 3 `recepcion@` (RECEPCION), 4 `mecanico@` (MECANICO), 5 `mecanico2@` (MECANICO), 6 `cliente@` (CLIENTE, ficha «Laura Martínez»), 7 `nuevo@` (MECANICO, cambio pendiente, contraseña `Provisoria1`); los demás `ClaveSegura1`.
- Fichas: 1 Laura (usuario 6), 2 «Jorge Pérez» (sin usuario). Vehículos: 1 `AB123CD` y 2 `AC456EF` (Laura), 3 `AD789GH` (Jorge).
- Repuestos: 1 `FIL-ACE-01` 8500, 2 `PAS-FRE-DEL` 32000, 3 `BUJ-01` 4500, 4 `ACE-5W30-1L` 12000.
- Órdenes: 1 (vehículo 1, `PENDIENTE`, ítems FIL-ACE-01 × 1 y ACE-5W30-1L × 4, total 56500.00, historial `null → PENDIENTE` por 3); 2 (vehículo 3, `EN_REPARACION`, mecánico 4, BUJ-01 × 4, total 18000.00, historial `null → PENDIENTE` por 3 y `PENDIENTE → EN_REPARACION` por 4).

El archivo agrega lo suyo con la API: un cliente ajeno `ajeno@lecturas.example.com` (documento `48000001`, ficha sin vehículos, usuario 8) y la orden 3 con **4 ítems** (vehículo 2, repuestos 1–4 × 1, total 57000.00) para el caso PDF C-15. Al final, la dueña cancela la orden 3 y la recepción da de baja el vehículo 2 para comprobar S-09. Secciones: A preparación, B acceso al listado, C listado y filtro, D caso PDF C-17, E detalle, F `/mis-ordenes`, G vehículo dado de baja. La lista exacta de casos está en `tasks.md` 1.1.

### D9 — Verificación sin pytest (Strict TDD adaptado, como C-14 D9) y evidencia C-15 (S-13)

- **RED**: `test/lecturas_ordenes.http` completo (tarea 1.1) se corre sobre `main` sin las rutas: la preparación responde como hoy, `GET /ordenes` → 405 `{"detail": "Method Not Allowed"}` (existe `POST /ordenes`), `GET /ordenes/{id}` y `GET /mis-ordenes` → 404 `{"detail": "Not Found"}`; los casos de `GET /estados-orden` (C-17) ya pasan. **GREEN**: cada tarea hace pasar los casos que cita. **TRIANGULATE**: cada regla con al menos dos casos. **Safety net**: `test/health.http`, `test/seed.http` (después de `python seed.py`), `test/clientes.http`, `test/ordenes.http`, `test/transiciones.http` (cada uno desde el estado conocido de su encabezado) y `test/verificar_security_core.py`, antes de tocar el módulo y al final.
- Lo que un `.http` no muestra va en **un** script temporal `$env:TEMP\verificar_c15.py` (no versionado). Se corre desde la raíz del repo (`.env`) con `.venv\Scripts\python.exe $env:TEMP\verificar_c15.py`, **inmediatamente después de `python seed.py`**. Arriba de todo: `os.environ["SQL_ECHO"] = "true"` y `sys.path.insert(0, os.getcwd())`, **antes** de `import main` (así el motor se crea con `echo=True`, igual que la consola del servidor). Usa `httpx.AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")` dentro de `async with main.lifespan(main.app):`, un cliente por usuario (`recepcion@example.com` y `cliente@example.com`, login con `ClaveSegura1`), un listener `event.listen(main.app.state.engine.sync_engine, "before_cursor_execute", …)` que guarda el texto de cada sentencia en una lista que se vacía antes de cada petición, y conexiones `asyncpg` propias (con los datos de `get_settings()`) para bloquear y contar filas. Hace una petición de calentamiento (`GET /ordenes` como recepción) antes de medir: la primera conexión del motor emite sentencias de inicialización del dialecto. Bloques, en este orden:
  - (b1) `GET /mis-ordenes` como cliente con **1** orden (la 1) → 3 sentencias; guardar la cantidad.
  - Preparación: `POST /ordenes` como recepción `{"vehiculo_id": 2, "falla": "Script C-15 con cuatro repuestos", "items": [{"repuesto_id": 1, "cantidad": 1}, {"repuesto_id": 2, "cantidad": 1}, {"repuesto_id": 3, "cantidad": 1}, {"repuesto_id": 4, "cantidad": 1}]}` → 201, id `N4` (será 3).
  - (a) **detalle 2 vs 4 ítems — evidencia PDF C-15**: un `logging.Handler` propio (nivel INFO, `Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")`) en `logging.getLogger("sqlalchemy.engine.Engine")` junta las líneas de `SQL_ECHO` **sólo** mientras dura cada una de estas dos peticiones: `GET /ordenes/1` (2 ítems) y `GET /ordenes/N4` (4 ítems), como recepción → ambas 200, 5 sentencias cada una, todas `SELECT`, ninguna con `FOR `, ids como parámetros (`$1`, nunca el número dentro del texto). Lo mismo como cliente (dueña) → 5 y 5. Escribe `test/evidencia_c15.txt` (UTF-8) con: una línea de título «Evidencia del caso PDF C-15 — detalle de una orden con 2 ítems y con 4 ítems», una línea «Generada por verificar_c15.py con SQL_ECHO=true el <fecha ISO> sobre la base recién cargada con `python seed.py`; son las mismas líneas que muestra la consola de uvicorn con SQL_ECHO=true», y dos secciones `=== GET /ordenes/1 (orden con 2 ítems): 5 sentencias SQL ===` y `=== GET /ordenes/3 (orden con 4 ítems): 5 sentencias SQL ===`, cada una con las líneas juntadas (cantidades reales, no fijas en el código).
  - (b2) **listados**: `GET /ordenes?size=1` (1 orden en la página) y `GET /ordenes?size=20` (3) → 4 y 4; `GET /ordenes?estado=PENDIENTE` → 4; `GET /mis-ordenes` como cliente con **2** órdenes → 3, igual que (b1). En el SQL de la página de `/mis-ordenes`: exactamente un `JOIN vehiculo` y ningún `vehiculo_1`; en ambas páginas `ORDER BY orden_trabajo.id DESC`.
  - (c) **sin escrituras**: con `asyncpg`, `SELECT count(*)` de las 13 tablas antes y después de: los GET de (a)/(b2), `GET /ordenes/999999` (404, 2 sentencias), `GET /ordenes/2` como cliente (403, 5 sentencias), `GET /ordenes?estado=REABIERTA` (422) y `GET /ordenes?page=9` (422, 3 sentencias) → cuentas iguales; ninguna sentencia capturada empieza con `INSERT`, `UPDATE` o `DELETE`.
  - (d) **sin bloqueos**: otra conexión `asyncpg` hace `BEGIN` y `SELECT id FROM orden_trabajo WHERE id = 1 FOR UPDATE`; `GET /ordenes/1`, `GET /ordenes` y `GET /mis-ordenes` con `asyncio.wait_for(…, timeout=2)` → los tres 200 mientras el bloqueo sigue; después `ROLLBACK`.
  - (e) **OpenAPI** (`GET /openapi.json`): `GET /ordenes` con parámetros `estado` (enum de los cuatro códigos, opcional), `page`, `size`, y respuesta `Pagina_OrdenResumenSalida_` cuyos `items` tienen exactamente los ocho campos de D3; `GET /ordenes/{orden_id}` con `orden_id` entero 1…2147483647 y respuesta `OrdenDetalleSalida`; `GET /mis-ordenes` con `page` y `size` y **sin** `estado`; ninguna de las tres respuestas contiene `password_hash`, `borrado_en`, `documento` ni `telefono`.
  - Imprime `OK`/`FALLA` por bloque y sale con código distinto de 0 si algo falla. Si sólo difiere un total absoluto de D6 pero la igualdad se cumple, **no** cambiar código: avisar a Nico (puede ser una sentencia de sesión que D6 no previó).
- `test/evidencia_c15.txt` se versiona (lo regenera cada corrida del script; diferirán las horas y las marcas `[cached since …]`). C-16 lo copia o lo enlaza en el README como «Evidencia del caso C-15».

## Risks / Trade-offs

- [El detalle cuesta 5 sentencias aunque el que pide sea el dueño] → leer los roles siempre deja el conteo fijo por petición y el código sin ramas; ahorrar 1 SELECT al dueño no vale una regla más para un modelo chico.
- [`joinedload` vs `contains_eager` en dos métodos parecidos] → el listado del personal no tiene JOIN propio (un `joinedload` agrega los suyos con alias); `/mis-ordenes` ya hace los JOIN para filtrar y `contains_eager` los reutiliza. El script (b2) comprueba que no quede un JOIN duplicado.
- [`OFFSET` en páginas lejanas] → con `size ≤ 100` y los volúmenes de un taller es despreciable; paginación por cursor queda fuera.
- [Un MECANICO ve el nombre del cliente de todas las órdenes] → la matriz da el detalle a «el personal» sin distinguir; el detalle de C-13 ya lo muestra. Si se quisiera acotar, sería un change de permisos.
- [La evidencia sale del script y no de `uvicorn`] → las líneas son las del mismo logger (`sqlalchemy.engine.Engine`) con `echo=True`; el archivo lo dice. Alternativa manual en S-13.
- [Conflictos de merge en `ordenes/*` y `main.py`] → todo es agregado al final; C-14 ya está mergeado y C-16 no toca estos archivos.
- [`seed.py` cambia sus datos] → los ids y montos de D8 dejarían de coincidir; la tarea 1.2 los comprueba con `psql` antes de escribir código.

## Migration Plan

Sin migraciones ni datos nuevos. Despliegue = mergear; rollback = revertir el merge (las rutas desaparecen; no queda estado).

## Open Questions / Supuestos

Todos **confirmados por el usuario el 2026-10-31**, cada uno con la recomendación indicada (la que asume el resto del change).

- **S-01 — Capacidad.** (A) agregar los requisitos a `work-orders` (su propósito ya dice «C-15 agrega las lecturas»); (B) capacidad nueva `order-queries`. **Recomendado A**.
- **S-02 — Forma del listado.** (A) `OrdenResumenSalida`: los campos del detalle sin `items` ni `historial` (`id, estado, patente, total, creada_en, mecanico_id, falla, cliente`), la misma para `/ordenes` y `/mis-ordenes`; (B) el detalle completo por orden (precarga de ítems e historial por página: 4–5 sentencias por página y respuestas grandes); (C) sólo `{id, estado, total}` (obliga al cliente a pedir cada detalle). **Recomendado A**.
- **S-03 — Sin N+1 en el listado.** (A) la página en UNA sentencia con vehículo y cliente por JOIN (muchos-a-uno) + el `count`; (B) `selectinload` del vehículo y del cliente (3–4 sentencias). **Recomendado A**.
- **S-04 — Orden.** (A) id descendente (más nueva primero; PK, estable); (B) `creada_en` descendente (sin índice y con empates: el seed crea las dos órdenes en la misma transacción); (C) id ascendente como `/repuestos`. **Recomendado A**.
- **S-05 — Filtro `estado`.** Códigos exactos de `CodigoEstado` (mayúsculas); minúsculas, vacío o desconocido → 422 de FastAPI sin consultar; repetido → el último (comportamiento de FastAPI); no se valida contra las filas del catálogo (un código del enum ausente del catálogo da página vacía). **Recomendado** como está.
- **S-06 — Alcance del MECANICO.** (A) ve todas las órdenes en el listado y en el detalle (matriz: «el personal»); (B) sólo las asignadas. **Recomendado A**.
- **S-07 — Rechazos del detalle.** 401 → 403 cambio → 422 → 404 → 403, con roles vigentes leídos en la base; «personal» = RECEPCION, ADMIN o MECANICO vigente. Alternativa: 404 también para quien no tiene relación (oculta la existencia). **Recomendado** como está (C-14 S-07, PDF «ajena → 403»).
- **S-08 — Comprobación de dueño.** (A) `orden.vehiculo.cliente.usuario_id` ya precargado por `get_detalle` (0 sentencias extra) y roles siempre (5 fijas); (B) `get_usuario_dueno` (1 más); (C) roles sólo si no es el dueño (4 o 5 según quién). **Recomendado A**.
- **S-09 — Vehículos dados de baja.** Sus órdenes siguen visibles para el personal (listado y detalle) y para el dueño (detalle y `/mis-ordenes`) (RN16, C-14 S-08). **Recomendado** como está.
- **S-10 — `/mis-ordenes`.** Filtra por `cliente.usuario_id` del usuario de la sesión; sin ficha o sin vehículos → 200 página vacía; sin parámetro `estado` (la matriz sólo da `page`/`size`; uno enviado se ignora); paginada (la matriz da 422, a diferencia de `/mis-vehiculos`). **Recomendado** como está.
- **S-11 — Sólo lectura.** Sin bloqueos, sin escrituras y sin eventos de seguridad también en 403/404. **Recomendado** como está.
- **S-12 — Estado conocido del `.http`.** (A) `python seed.py` antes + datos propios por la API (`@lecturas.example.com`, documento `48000001`, la orden de 4 ítems); (B) encabezado `TRUNCATE` + datos propios como `transiciones.http`. **Recomendado A**: el seed da las órdenes de 2 y 1 ítems, los siete usuarios y una ficha sin usuario.
- **S-13 — Evidencia C-15.** (A) el script la genera con `SQL_ECHO=true` y un handler del logger `sqlalchemy.engine.Engine` en `test/evidencia_c15.txt` (versionado); (B) copiar a mano el fragmento de la consola de uvicorn (`$env:SQL_ECHO="true"`, `… uvicorn main:app *>&1 | Tee-Object $env:TEMP\c15.log`) entre los dos `GET`. **Recomendado A** (reproducible y sin edición manual).
- **S-14 — Numeración de casos PDF.** `CHANGES.md` asocia `/mis-ordenes` al «caso PDF C17», pero en el PDF C-17 es «catálogo de estados; filtrar órdenes por un estado que el contrato no declara → los cuatro por posición, con TERMINADA y CANCELADA finales; sin sesión, 401; 422». El `.http` cubre C-17 en su sección D y `/mis-ordenes` por RN17. **Recomendado**: corregir `CHANGES.md` al archivar.
- **S-15 — Mensaje del 403.** «Sólo el personal del taller o el dueño del vehículo puede ver la orden» (estilo de los 403 de C-14); el 404 reutiliza «La orden no existe». **Recomendado** como está.
- **S-16 — Montaje.** Rol de `GET /ordenes` en `dependencies=` de la ruta con `lectura_ordenes` creada una vez; `/mis-ordenes` en su propio `APIRouter` dentro de `ordenes/router.py`, montado en `main.py` después de `router_estados`. **Recomendado** como está.
- **S-17 — Contrato de consultas.** Totales por petición de D6 (listado 4, detalle 5, `/mis-ordenes` 3) además de la igualdad; si sólo difiere el total, se avisa en vez de cambiar código. **Recomendado** como está.

## Notas para otros changes

**C-16 (integración — Lauti)**
- Integrar `test/lecturas_ordenes.http`: correrlo **inmediatamente después** de `python seed.py` (escribe la orden 3, cancela y da de baja el vehículo 2). `verificar_c15.py` también parte del seed recién cargado.
- README: sección «Evidencia del caso C-15» con el contenido de `test/evidencia_c15.txt` (o un enlace) y el comando para regenerarlo.

**Mati (revisa el PR)**
- C-15 no modifica archivos de Mati: usa `PaginacionDep`, `verificar_pagina`, `armar_pagina`, `Pagina`, `requiere_rol` y `UsuarioActualDep` tal cual.

## Notas para el archivo

- `CHANGES.md` C-15: reemplazar «Caso PDF C17» de `/mis-ordenes` por «RN17» y agregar «caso PDF C-17: `GET /estados-orden` + `GET /ordenes?estado=<no declarado>` → 422» (S-14).
- KB `06_funcionalidades.md` US-052: `GET /estados-orden` ya lo implementó C-13; anotar el orden id descendente y la forma de resumen de los listados (S-02, S-04).
- KB `03_actores_y_roles.md`: anotar que `GET /ordenes/{id}` da además 422 por id inválido, con 404 antes que 403, y que «el personal» incluye a cualquier MECANICO vigente (S-06, S-07).
