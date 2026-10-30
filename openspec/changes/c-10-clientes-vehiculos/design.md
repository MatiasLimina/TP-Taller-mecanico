# Design — C-10 clientes-vehiculos

## Context

Estado actual (motivación en proposal.md — Why; requisitos en `specs/customer-records` y `specs/customer-vehicles`):

- **Modelos (C-03)**: `app/modules/clientes/models.py` ya tiene `Cliente(id, usuario_id, nombre, documento, telefono)` — **sin** baja lógica — con `vehiculos: list[Vehiculo]`, y `Vehiculo(id, cliente_id, patente, marca, modelo, anio, borrado_en)` con `cliente` y `ordenes`. Todas las relaciones son `lazy="raise"`: leer una relación no precargada lanza error. Ninguna relación tiene `order_by`.
- **Esquema (migración 1)**: `uq_cliente_documento`, `uq_cliente_usuario_id`, `fk_vehiculo_cliente_id_cliente`, `ix_vehiculo_cliente_id`, índice único parcial `uq_vehiculo_patente (patente) WHERE borrado_en IS NULL`, `ck_vehiculo_anio_rango` (`anio BETWEEN 1950 AND 2100`); `orden_trabajo.vehiculo_id` con `ix_orden_trabajo_vehiculo_id` y `orden_trabajo.estado` FK a `estado_orden.codigo` (PK). Columnas de texto sin largo (`VARCHAR`). No hace falta migración.
- **Órdenes**: `app/modules/ordenes/` sólo tiene `models.py` (`OrdenTrabajo`, `EstadoOrden` con `es_final`, `CodigoEstado`). Repositorio, servicio y rutas son de C-13 (Nico). El catálogo `estado_orden` nace vacío; lo carga C-06 (no mergeado).
- **Core (C-02/C-08)**: `BaseRepository`/`SoftDeleteRepository` (`_consulta_base()` ya filtra `borrado_en IS NULL`; `soft_delete()` escribe `datetime.now(UTC)` y hace `flush()`), `UnitOfWork` (patrón por módulo en su docstring, ejemplo literal `ClientesUoW`), `requiere_rol(*roles)`, `UsuarioActualDep`, `IdRuta` (1..2147483647), `NoEncontrado`/`Conflicto`, `restriccion_violada`, `EntradaBase`/`SalidaBase`. Sólo Mati modifica `app/core/*` (REPARTO §9): este change no lo toca.
- **Usuarios (C-07/C-09)**: el registro escribe la ficha con `BaseRepository(session, Cliente)` dentro de `UsuariosUoW` para no adelantar este módulo; `schemas.py` define `Nombre`, `Documento`, `Telefono` (recorte + 1..100/20/30). `router.py` es la referencia de estilo: `requiere_rol` creado una vez y usado a nivel de `APIRouter`.
- **Petición protegida**: `get_session` se resuelve una vez por petición; `get_usuario_actual` y `requiere_rol` abren y cierran bloques sucesivos del `UsuariosUoW` sobre esa sesión **antes** del handler; el `ClientesUoW` del handler abre su propio bloque sobre la misma sesión (sucesivo, nunca anidado). `expire_on_commit=False`.

## Goals / Non-Goals

**Goals:**

- Módulo `clientes` completo con la estructura obligatoria y el patrón de C-09, sin tocar `core`, `usuarios`, `ordenes` ni modelos.
- Unicidad (documento, patente vigente) decidida por la base sin consulta previa, traducida a 409 propio fuera del bloque.
- RN16 decidido con el catálogo (`es_final`), sin depender de código de C-13, y sin carrera con la futura alta de órdenes.
- Detalle con vehículos en un número fijo de consultas (precarga declarada en el repositorio).

**Non-Goals:**

- Editar o borrar fichas, vincular fichas a usuarios, editar vehículos, listar clientes, buscar por documento o patente.
- Mostrar vehículos dados de baja en alguna ruta (historial de un vehículo vendido).
- Cualquier ruta de órdenes o `seed.py`.

## Decisions

### D1 — Archivos

| Archivo | Contenido |
|---------|-----------|
| `app/modules/clientes/schemas.py` (nuevo) | `ClienteAltaEntrada`, `ClienteSalida`, `ClienteDetalleSalida`, `VehiculoAltaEntrada` (+ tipos `Patente`, `Marca`, `Modelo`, `Anio`), `VehiculoSalida` |
| `app/modules/clientes/repository.py` (nuevo) | `ClienteRepository(BaseRepository[Cliente])`, `VehiculoRepository(SoftDeleteRepository[Vehiculo])` |
| `app/modules/clientes/unit_of_work.py` (nuevo) | `ClientesUoW`, `get_clientes_uow`, `ClientesUoWDep` |
| `app/modules/clientes/service.py` (nuevo) | `alta_cliente`, `detalle_cliente`, `alta_vehiculo`, `baja_vehiculo`, `mis_vehiculos`; mensajes |
| `app/modules/clientes/router.py` (nuevo) | `personal_clientes`, `router_clientes`, `router_vehiculos`, `router_mis_vehiculos` |
| `main.py` | import de los tres routers y `rutas_protegidas.include_router(...)` de cada uno **antes** de `app.include_router(rutas_protegidas)` |
| `test/clientes.http` (nuevo) | casos del change (D11) |

### D2 — Rutas, roles y montaje (S-15)

```python
# router.py
personal_clientes = requiere_rol(Rol.RECEPCION, Rol.ADMIN)   # UNA función para los dos routers

router_clientes = APIRouter(prefix="/clientes", tags=["clientes"], dependencies=[Depends(personal_clientes)])
router_vehiculos = APIRouter(prefix="/vehiculos", tags=["vehiculos"], dependencies=[Depends(personal_clientes)])
router_mis_vehiculos = APIRouter(prefix="/mis-vehiculos", tags=["mis-vehiculos"])   # sin rol: RN17

@router_clientes.post("", status_code=201)
async def alta_cliente(datos: ClienteAltaEntrada, uow: ClientesUoWDep) -> ClienteSalida
@router_clientes.get("/{cliente_id}")
async def detalle_cliente(cliente_id: IdRuta, uow: ClientesUoWDep) -> ClienteDetalleSalida
@router_clientes.post("/{cliente_id}/vehiculos", status_code=201)
async def alta_vehiculo(cliente_id: IdRuta, datos: VehiculoAltaEntrada, uow: ClientesUoWDep) -> VehiculoSalida
@router_vehiculos.delete("/{vehiculo_id}", status_code=204)
async def baja_vehiculo(vehiculo_id: IdRuta, uow: ClientesUoWDep) -> None
@router_mis_vehiculos.get("")
async def mis_vehiculos(actual: UsuarioActualDep, uow: ClientesUoWDep) -> list[VehiculoSalida]
```

- El rol va a nivel de router: ninguna ruta nueva de `/clientes` o `/vehiculos` lo olvida, y como la dependencia corre antes de resolver la ruta contra la base, un usuario sin rol recibe 403 exista o no el id (S-08). Ningún handler necesita al actor (no hay eventos de seguridad en este módulo), así que no hay `RecepcionDep`.
- `/mis-vehiculos` sólo depende del grupo (`exigir_password_al_dia` → 401/403 cambio) y de `UsuarioActualDep` (la misma instancia cacheada), y pasa `actual.id` al servicio: el servicio no conoce `UsuarioActual` (sin dependencia `clientes → usuarios.service`).
- 204: `status_code=204` con `-> None`; FastAPI no envía cuerpo para 204.
- Orden de rechazos heredado (spec `access-control`): 401 → 403 cambio → 403 rol → 422 (ruta/cuerpo) → 404 → 409.

### D3 — Contratos (S-09, S-10, S-11, S-13)

```python
from app.modules.usuarios.schemas import Documento, Nombre, Telefono   # mismas reglas que el registro

ANIO_MINIMO, ANIO_MAXIMO = 1950, 2100            # = ck_vehiculo_anio_rango
PATRON_PATENTE = re.compile(r"[A-Z0-9]{6,8}")

def _normalizar_patente(valor: str) -> str:
    patente = "".join(valor.split()).replace("-", "").upper()
    if not PATRON_PATENTE.fullmatch(patente):
        raise ValueError("La patente debe tener de 6 a 8 letras o dígitos, sin contar espacios ni guiones")
    return patente

Patente = Annotated[str, AfterValidator(_normalizar_patente)]
Marca = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Modelo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Anio = Annotated[int, Field(ge=ANIO_MINIMO, le=ANIO_MAXIMO)]

class ClienteAltaEntrada(EntradaBase):   nombre: Nombre; documento: Documento; telefono: Telefono
class VehiculoAltaEntrada(EntradaBase):  patente: Patente; marca: Marca; modelo: Modelo; anio: Anio

class VehiculoSalida(SalidaBase):        id: int; cliente_id: int; patente: str; marca: str; modelo: str; anio: int
class ClienteSalida(SalidaBase):         id: int; usuario_id: int | None; nombre: str; documento: str; telefono: str
class ClienteDetalleSalida(ClienteSalida): vehiculos: list[VehiculoSalida]
```

- `VehiculoSalida` se define **antes** que `ClienteDetalleSalida` (la revisión de `SalidaBase` no resuelve referencias en texto).
- `VehiculoSalida` no tiene `borrado_en`: toda ruta devuelve sólo vigentes. `ClienteSalida.model_validate(cliente)` lee sólo columnas (no `vehiculos`), así que no dispara la relación `lazy="raise"`.
- El CHECK `ck_vehiculo_anio_rango` queda como respaldo: si algo lo saltea, el manejador global responde 422 genérico, nunca 500.

### D4 — Repositorios (S-01, S-02, S-03, S-17)

```python
class ClienteRepository(BaseRepository[Cliente]):
    async def get_con_vehiculos(self, id: int) -> Cliente | None:
        # Precarga declarada acá, con criterio: sólo vehículos vigentes (RN16). 2 SELECT fijos.
        consulta = (self._consulta_base().where(col(Cliente.id) == id)
                    .options(selectinload(Cliente.vehiculos.and_(col(Vehiculo.borrado_en).is_(None)))))  # type: ignore[attr-defined]
        return (await self.session.exec(consulta)).first()

class VehiculoRepository(SoftDeleteRepository[Vehiculo]):
    async def listar_de_usuario(self, usuario_id: int) -> list[Vehiculo]:
        # Vigentes (_consulta_base) JOIN cliente ON cliente.id = vehiculo.cliente_id
        # WHERE cliente.usuario_id = :usuario_id ORDER BY vehiculo.id   — 1 SELECT, sin relaciones.
    async def get_vigente_para_actualizar(self, id: int) -> Vehiculo | None:
        # _consulta_base().where(id == :id).with_for_update().execution_options(populate_existing=True)
    async def tiene_ordenes_abiertas(self, vehiculo_id: int) -> bool:
        # SELECT orden_trabajo.id FROM orden_trabajo JOIN estado_orden ON estado_orden.codigo = orden_trabajo.estado
        # WHERE orden_trabajo.vehiculo_id = :id AND estado_orden.es_final IS false LIMIT 1   → is not None
```

- Índices que usan: PK de `cliente`; `ix_vehiculo_cliente_id` (precarga y `/mis-vehiculos`); `uq_cliente_usuario_id` (filtro por usuario); PK de `vehiculo`; `ix_orden_trabajo_vehiculo_id` + PK de `estado_orden`. No se crea ninguno.
- **S-01**: la consulta de órdenes abiertas vive en `VehiculoRepository` (módulo clientes) e importa sólo **modelos** de `ordenes` (existen desde C-03). Pregunta "¿se puede dar de baja este vehículo?", no adelanta `ordenes/repository.py` (C-13) y no lista estados en el código: decide `es_final`.
- **S-02**: `get_vigente_para_actualizar` bloquea la fila del vehículo (`FOR UPDATE`) durante la verificación y la baja. Con C-13 bloqueando la misma fila al verificar "vehículo vigente", alta de orden y baja se serializan: la baja que espera ve la orden confirmada (READ COMMITTED: cada sentencia toma una foto nueva) → 409; el alta de orden que espera vuelve a evaluar `borrado_en IS NULL` y no encuentra el vehículo. Dos bajas simultáneas: la segunda no encuentra la fila → 404. `populate_existing` evita usar una versión vieja del identity map.
- Orden de los vehículos: por id; la precarga no tiene `order_by` (la relación no lo declara y los modelos no se tocan, S-17), así que el servicio ordena la colección por `id` al armar la salida.

### D5 — `POST /clientes`

```
try:
    async with uow:
        cliente = await uow.clientes.add(Cliente(nombre=datos.nombre, documento=datos.documento, telefono=datos.telefono))
        salida = ClienteSalida.model_validate(cliente)            # adentro, con valores cargados
except IntegrityError as exc:
    if restriccion_violada(exc) == "uq_cliente_documento": raise Conflicto(MENSAJE_DOCUMENTO_REPETIDO) from None
    raise
return salida
```

Sin consulta previa (RN01); dos altas simultáneas → el índice decide (201 + 409). `usuario_id` queda nulo (S-04).

### D6 — `GET /clientes/{id}`

```
async with uow:
    cliente = await uow.clientes.get_con_vehiculos(cliente_id)
    if cliente is None: raise NoEncontrado(MENSAJE_CLIENTE_INEXISTENTE)
    vehiculos = sorted(cliente.vehiculos, key=lambda v: v.id or 0)
    salida = ClienteDetalleSalida(id=cliente.id, usuario_id=cliente.usuario_id, nombre=..., documento=..., telefono=...,
                                  vehiculos=[VehiculoSalida.model_validate(v) for v in vehiculos])
return salida
```

### D7 — `POST /clientes/{id}/vehiculos`

```
try:
    async with uow:
        if await uow.clientes.get_by_id(cliente_id) is None: raise NoEncontrado(MENSAJE_CLIENTE_INEXISTENTE)
        vehiculo = await uow.vehiculos.add(Vehiculo(cliente_id=cliente_id, patente=datos.patente, marca=datos.marca,
                                                    modelo=datos.modelo, anio=datos.anio))
        salida = VehiculoSalida.model_validate(vehiculo)
except IntegrityError as exc:
    if restriccion_violada(exc) == "uq_vehiculo_patente":
        raise Conflicto(MENSAJE_PATENTE_REPETIDA.format(patente=datos.patente)) from None   # dato del contrato, no de la entidad
    raise
return salida
```

- 404 antes que 409: la ficha se busca primero. `cliente` no tiene baja ni borrado, así que no hay carrera con la FK.
- El mensaje usa `datos.patente` (ya normalizada), nunca atributos de la entidad expirada por el rollback.

### D8 — `DELETE /vehiculos/{id}` (RN16)

```
async with uow:
    vehiculo = await uow.vehiculos.get_vigente_para_actualizar(vehiculo_id)    # FOR UPDATE (S-02)
    if vehiculo is None: raise NoEncontrado(MENSAJE_VEHICULO_INEXISTENTE)      # inexistente o ya dado de baja (S-18)
    if await uow.vehiculos.tiene_ordenes_abiertas(vehiculo_id): raise Conflicto(MENSAJE_VEHICULO_CON_ORDENES)
    await uow.vehiculos.soft_delete(vehiculo)
```

Con catálogo vacío no puede haber órdenes (FK), así que la baja procede. Las órdenes cerradas y la fila del vehículo se conservan.

### D9 — `GET /mis-vehiculos` (RN17, S-05, S-06, S-07)

```
async with uow:
    vehiculos = await uow.vehiculos.listar_de_usuario(usuario_id)
    salida = [VehiculoSalida.model_validate(v) for v in vehiculos]
return salida
```

Arreglo JSON simple. Sin ficha vinculada → `[]`. Un usuario del personal con ficha (registrado y después con rol) ve sus propios vehículos: "lo propio" es por usuario, no por rol.

### D10 — Mensajes

| Situación | Código | `detail` |
|-----------|--------|----------|
| Ficha de la ruta inexistente (`GET /clientes/{id}`, `POST …/vehiculos`) | 404 | `El cliente no existe` |
| Documento repetido | 409 | `El documento ya pertenece a un cliente del taller` (mismo texto que C-07, constante propia del módulo, S-14) |
| Patente de otro vehículo vigente | 409 | `Ya hay un vehículo vigente con la patente <PATENTE>` |
| Vehículo inexistente o ya dado de baja | 404 | `El vehículo no existe` |
| Vehículo con alguna orden en estado no final | 409 | `El vehículo tiene órdenes abiertas y no se puede dar de baja` |
| Patente con formato inválido | 422 | lista por campo con `La patente debe tener de 6 a 8 letras o dígitos, sin contar espacios ni guiones` |

Constantes en `service.py`: `MENSAJE_CLIENTE_INEXISTENTE`, `MENSAJE_DOCUMENTO_REPETIDO`, `MENSAJE_PATENTE_REPETIDA` (con `{patente}`), `MENSAJE_VEHICULO_INEXISTENTE`, `MENSAJE_VEHICULO_CON_ORDENES`.

### D11 — Verificación sin pytest (Strict TDD adaptado, como C-09 D9)

- **RED**: `test/clientes.http` completo se escribe primero (tarea 1.1) y se corre contra el servidor actual: toda ruta `/clientes…`, `/vehiculos…` y `/mis-vehiculos` → 404 `Not Found`. Se anota la línea de base.
- **GREEN**: cada tarea de rutas hace pasar los casos numerados que cita.
- **TRIANGULATE**: cada regla con al menos dos casos (acepta / rechaza, o dos motivos de rechazo).
- **Safety net**: `test/health.http`, `test/auth.http`, `test/sesion.http`, `test/personal.http` y `test/verificar_security_core.py` antes de tocar `main.py` y al final.
- **Estado conocido sin C-06 ni C-13 (S-16)**: correos `@clientes.example.com`, documentos `430000xx`, patentes `ZC…`. Personal: `/auth/registro` + `INSERT` en `asignacion_rol` por `psql` (como C-09). Usuario sin ficha: se registra un mecánico y se borra su ficha por `psql`. Cambio pendiente: `UPDATE usuario SET debe_cambiar_password = true` por `psql`. Catálogo: `INSERT … ON CONFLICT DO NOTHING` de los cuatro estados en el encabezado. Órdenes de prueba: `INSERT`/`UPDATE` en `orden_trabajo` por `psql` en el comentario del caso (sin `historial_estado_orden`, así la limpieza puede borrarlas).
- Lo que un `.http` no muestra va en **un** script temporal `$env:TEMP\verificar_c10.py` (no versionado), con `httpx.AsyncClient(transport=ASGITransport(app=main.app))` dentro de `async with main.lifespan(main.app)`, usando las sesiones de `recepcion@clientes.example.com` (precondición: `test/clientes.http` corrido): (a) consultas constantes del detalle (listener `before_cursor_execute` sobre `main.app.state.engine.sync_engine`): misma cantidad de sentencias para una ficha con 1 vehículo y otra con 3; (b) dos `POST /clientes` simultáneos con el mismo documento → 201 + 409, nunca 500; (c) dos altas simultáneas de la misma patente → 201 + 409; (d) baja contra alta de orden: otra conexión `asyncpg` hace `BEGIN; SELECT … FROM vehiculo WHERE id = X FOR UPDATE; INSERT INTO orden_trabajo (… 'PENDIENTE' …)`, se lanza el `DELETE`, se comprueba que sigue esperando a los 0,5 s, se confirma la otra conexión → el `DELETE` responde 409 y el vehículo queda vigente; (e) `/openapi.json`: ninguna respuesta de las cinco rutas tiene `borrado_en` ni `password_hash`. Datos del script: documentos `43000090`–`43000099` y patentes `ZC09…` (las limpia el encabezado del `.http`).

## Risks / Trade-offs

- [C-13 no bloquea la fila del vehículo] → la baja y el alta de una orden sobre el mismo vehículo podrían cruzarse y dejar una orden PENDIENTE sobre un vehículo dado de baja. Mitigación: nota explícita para C-13 (abajo) y caso (d) del script, que prueba el lado de la baja.
- [Normalización de la patente] → `AB 123 CD` y `AB-123-CD` se guardan como `AB123CD`; una patente extranjera de 5 o de más de 8 caracteres no se puede cargar. Se acepta (S-09); ampliar el rango es cambiar una constante.
- [`clientes` importa de `usuarios.schemas` y de `ordenes.models`] → acoplamiento entre módulos. Se elige para no duplicar reglas (documento) ni adelantar código de C-13; no hay ciclos de import (`ordenes.models` y `usuarios.models` referencian a `clientes` sólo bajo `TYPE_CHECKING`).
- [Precarga con criterio y identity map] → `selectinload(... .and_(...))` no recarga una colección ya cargada en la misma sesión; en una petición nadie cargó antes la ficha, así que no aplica. Si un uso futuro la lee dos veces en la misma sesión, agregar `populate_existing`.
- [`/mis-vehiculos` sin paginar] → un cliente con muchísimos vehículos recibe todo; en un taller es irrelevante y la matriz no prevé 422 (S-05).
- [Ficha creada por la recepción con un documento mal tipeado] → bloquea el auto-registro de esa persona (RN02, 409) y no hay ruta para corregirla; se corrige por `psql` hasta que exista una edición de fichas (fuera de alcance).

## Migration Plan

Sin cambios de esquema ni de datos. Despliegue: archivos nuevos del módulo + `main.py` + `test/clientes.http`, reiniciar uvicorn. Rollback: revertir `main.py` (las rutas desaparecen) y borrar los archivos nuevos; las filas de prueba se limpian con el bloque `psql` del encabezado de `test/clientes.http`.

## Open Questions / Supuestos

Todos los supuestos fueron **confirmados por el usuario el 2026-10-29**, cada uno con la recomendación indicada. Cada uno con la pregunta, las opciones y la recomendación.

- **S-01 — Dónde vive la comprobación de órdenes abiertas.** Opciones: (A) `VehiculoRepository.tiene_ordenes_abiertas` en `clientes`, leyendo los modelos de `ordenes` con un join a `estado_orden.es_final`; (B) crear ahora `ordenes/repository.py` con un `OrdenTrabajoRepository` mínimo; (C) consulta directa en el servicio; (D) comparar con una lista de códigos (`PENDIENTE`, `EN_REPARACION`). **Recomendación: A** — sólo depende de modelos que existen, la pregunta es del vehículo, no choca con el archivo que C-13 (Nico) va a crear. B genera conflicto de merge con C-13; C rompe las capas; D contradice RN16 ("según catálogo").
- **S-02 — Carrera entre la baja y el alta de una orden.** Opciones: (A) `SELECT … FOR UPDATE` de la fila del vehículo en la baja, y C-13 bloquea la misma fila al verificar "vehículo vigente"; (B) sin bloqueo; (C) `SERIALIZABLE`; (D) `pg_advisory_xact_lock`. **Recomendación: A** — un bloqueo de una fila, sin migraciones; B puede dejar una orden abierta sobre un vehículo dado de baja; C exige reintentos que el UoW no tiene (500); D usa una clave que el esquema no documenta.
- **S-03 — Qué vehículos muestra `GET /clientes/{id}`.** Opciones: (A) sólo vigentes, con precarga filtrada (`selectinload(... .and_(borrado_en IS NULL))`); (B) todos, con `borrado_en` en la salida; (C) precargar todos y filtrar en Python; (D) dos consultas explícitas sin relación. **Recomendación: A** — RN16 dice que el dado de baja "deja de aparecer"; la precarga declarada en el repositorio es lo que pide la KB; C trae filas de más; D no muestra la carga ansiosa que pide el scope.
- **S-04 — Forma de las salidas de fichas.** Opciones: (A) `{id, usuario_id, nombre, documento, telefono}` y el detalle con `vehiculos`; (B) agregar el correo del usuario vinculado; (C) ocultar `usuario_id`. **Recomendación: A** — sin join extra a `usuario`, la recepción sabe si la ficha tiene cuenta y no expone datos de la cuenta.
- **S-05 — `/mis-vehiculos` paginado o no.** Opciones: (A) arreglo simple; (B) `Pagina[VehiculoSalida]` con `page`/`size`; (C) objeto `{items}`. **Recomendación: A** — la matriz sólo lista 200 (a diferencia de `/mis-ordenes`, que lista 422 por `page`/`size`) y `list-pagination` rige para colecciones que reciben `page`/`size`.
- **S-06 — Usuario autenticado sin ficha en `/mis-vehiculos`.** Opciones: (A) 200 `[]`; (B) 404; (C) 403. **Recomendación: A** — la matriz sólo lista 200 y "no tengo vehículos" es una respuesta válida.
- **S-07 — Personal con ficha en `/mis-vehiculos`.** Opciones: (A) ve los vehículos de su propia ficha; (B) 403 si no tiene rol `CLIENTE`. **Recomendación: A** — la matriz dice "Autenticado", no `CLIENTE`; lo propio es por usuario.
- **S-08 — 403 antes que 404 para quien no es personal.** Opciones: (A) el rol se controla a nivel de router antes de buscar el recurso: un `CLIENTE` recibe 403 en `/clientes/{id}` y `/vehiculos/{id}` exista o no el id, también para su propia ficha; (B) permitir a un `CLIENTE` leer su propia ficha por `GET /clientes/{id}` (403 si es ajena). **Recomendación: A** — la matriz da esas rutas sólo a RECEPCION/ADMIN y no revela qué ids existen; lo propio va por `/mis-vehiculos`.
- **S-09 — Normalización y formato de la patente.** Opciones: (A) quitar espacios y guiones, mayúsculas, y exigir 6–8 caracteres `[A-Z0-9]`; (B) sólo recortar y pasar a mayúsculas, sin formato; (C) regex estricta de patentes argentinas (`ABC123` / `AB123CD`); (D) guardar tal cual. **Recomendación: A** — `ab123cd`, `AB 123 CD` y `AB-123-CD` chocan como la misma patente en el índice exacto; admite autos viejos, Mercosur y motos; C rechaza motos y extranjeras; D permite duplicados que difieren en mayúsculas. C-06 debe cargar patentes ya normalizadas (`AC456EF`).
- **S-10 — Dónde se valida `anio`.** Opciones: (A) en el contrato (`Field(ge=1950, le=2100)`, 422 por campo) con el CHECK como respaldo; (B) sólo el CHECK (422 genérico sin campo); (C) en el servicio con `EntradaInvalida`. **Recomendación: A** — error por campo como el resto de la validación; constantes iguales al CHECK.
- **S-11 — Reglas de `nombre`/`documento`/`telefono` del alta de ficha.** Opciones: (A) importar `Nombre`, `Documento`, `Telefono` de `usuarios/schemas.py`; (B) copiarlos en `clientes/schemas.py`; (C) moverlos a `app/core/schemas.py`. **Recomendación: A** — el documento se normaliza igual en el registro y en el alta de ficha (importa para `uq_cliente_documento`) sin duplicar; C toca `core` (de Mati) y `usuarios`.
- **S-12 — El registro de C-07 sigue con `BaseRepository(session, Cliente)`.** Opciones: (A) no tocar `usuarios`; (B) cambiar `UsuariosUoW.clientes` a `ClienteRepository`. **Recomendación: A** — sin cambio de comportamiento; B toca código ajeno al change (y a su responsable) sólo por prolijidad.
- **S-13 — Largos de `marca` y `modelo`.** Opciones: (A) 1–50 caracteres tras recortar; (B) sin máximo (la columna no tiene largo). **Recomendación: A** — acota la entrada como hacen los demás textos del proyecto.
- **S-14 — Mensajes de 409.** Opciones: (A) constantes propias en `clientes/service.py`, la de documento con el mismo texto que C-07, la de patente con la patente normalizada; (B) importar `MENSAJE_DOCUMENTO_REPETIDO` de `usuarios.service`; (C) mensaje genérico. **Recomendación: A** — sin dependencia entre servicios; el mensaje de patente dice cuál choca y sale del contrato, no de la base.
- **S-15 — Ubicación y montaje de las rutas.** Opciones: (A) tres `APIRouter` en `clientes/router.py`, `requiere_rol(Rol.RECEPCION, Rol.ADMIN)` creado una vez y usado a nivel de router en `/clientes` y `/vehiculos`, `/mis-vehiculos` sin rol, los tres en `rutas_protegidas`; (B) `requiere_rol` por ruta; (C) `DELETE /vehiculos` en otro módulo. **Recomendación: A** — mismo patrón que C-09 (S-12 de C-09); `Vehiculo` vive en `clientes` (KB 08).
- **S-16 — Estado conocido de `test/clientes.http` sin seed ni órdenes.** Opciones: (A) limpieza `psql` propia + catálogo por `INSERT … ON CONFLICT DO NOTHING` + órdenes de prueba por `psql` + personal por registro y `INSERT` de rol + usuario sin ficha borrando la ficha de un registrado + script temporal; (B) usuario sin ficha con `POST /usuarios` como ADMIN (exige cambiar la contraseña provisoria: tres peticiones más); (C) esperar a C-06/C-13. **Recomendación: A** — mismo método que C-07/C-09, el archivo se corre solo; C bloquea el change.
- **S-17 — Orden de los vehículos en las salidas.** Opciones: (A) por id ascendente, ordenando en el servicio la colección precargada y con `ORDER BY` en `/mis-vehiculos`; (B) agregar `order_by` a la relación en `models.py`; (C) sin orden garantizado. **Recomendación: A** — determinista sin tocar modelos; B cambia un archivo de C-03 sin necesidad.
- **S-18 — Segunda baja de un vehículo.** Opciones: (A) 404 `El vehículo no existe` (el dado de baja "deja de aparecer"); (B) 204 idempotente; (C) 409. **Recomendación: A** — coherente con RN16 y con `SoftDeleteRepository.get_by_id`; la matriz lista 404.

## Notas para otros changes

- **C-13**: al verificar "vehículo vigente" en `POST /ordenes`, leer el vehículo con `VehiculoRepository.get_vigente_para_actualizar` (o un `FOR SHARE` equivalente) dentro del UoW de la orden, para serializar con la baja (S-02). `ClientesUoW` no se reutiliza: el UoW de órdenes instancia su propio `VehiculoRepository(session)`.
- **C-15**: la comprobación de dueño de `GET /ordenes/{id}` y `/mis-ordenes` usa `vehiculo.cliente_id → cliente.usuario_id` con la misma idea que `listar_de_usuario`; decidir allí si las órdenes de vehículos dados de baja siguen visibles para el dueño (el vehículo conserva sus datos, RN16).
- **C-06**: cargar a Laura (con `cliente@example.com`) y Jorge (sin usuario) con patentes normalizadas (`AC456EF`); el seed puede usar `ClienteRepository`/`VehiculoRepository`.
- **C-16**: integrar `test/clientes.http`; cuando exista `seed.py`, el encabezado sigue sirviendo (limpia sólo sus filas y el catálogo no se pisa).
