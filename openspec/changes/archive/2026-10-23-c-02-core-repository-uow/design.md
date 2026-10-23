# Design — C-02 core-repository-uow

## Context

Motivación en proposal.md (Why); requisitos en `specs/`. Estado actual y restricciones que moldean el diseño:

- **Código de C-01** (se respeta, no se rediseña): `create_session_factory` usa `AsyncSession` **de SQLModel** (`sqlmodel.ext.asyncio.session`, da `session.exec()`) con `expire_on_commit=False`; `get_session(request)` abre la sesión con `async with request.app.state.session_factory()` y **no** hace commit/rollback ("la transacción es del UoW"); alias `SessionDep`. `main.py` tiene `lifespan` y `rutas_abiertas`; C-05 y C-08 también tocan `main.py`.
- **Versiones instaladas en `.venv`**: FastAPI 0.161.1, SQLAlchemy 2.0.55, SQLModel 0.0.48, asyncpg 0.32.0, Pydantic 2.14.1.
- **Consigna Ej.6** (20 %): `BaseRepository[T]` con sesión + clase del modelo en el constructor "porque los genéricos se borran en tiempo de ejecución"; `SoftDeleteRepository[T]` hereda y agrega `get_by_id_including_deleted` y `soft_delete`; `flush()` y nunca `commit()`; precarga declarada en el método que la necesita; UoW confirma al salir, revierte con excepción, no cierra la sesión; el router construye el UoW con una dependencia y el servicio lo abre con `async with` y nunca lo construye; el catálogo `estado_orden` tiene repo de sólo lectura que **no** hereda de `BaseRepository` (C-13, no acá).
- **Consigna Ej.3 / RN18**: `extra="forbid"`, sin `password_hash`, envoltorio `{items,total,page,size,pages}`, «La página 3 no existe: hay 2», ninguna entrada inválida → 500, nunca texto de la base.
- **Reglas duras de CLAUDE.md**: las de "Código" aplican todas a este change. Sin pytest: verificación ejecutable por comandos.
- **Hallazgo en el código de SQLAlchemy 2.0.55** (`dialects/postgresql/asyncpg.py`): las excepciones de asyncpg se traducen por MRO: `IntegrityConstraintViolationError → IntegrityError`, `PostgresError → Error` (→ `DBAPIError`), `InterfaceError → InterfaceError`; la traducida lleva `pgcode`/`sqlstate` y la original queda en `__cause__` (con `constraint_name`). El error de **codificación del lado cliente** (`asyncpg.exceptions._base.DataError`, p. ej. `value out of int32 range`) es subclase de `InterfaceError` y **no trae sqlstate** → hoy un `GET /x/99999999999` daría 500.
- **Sin tablas todavía**: los modelos llegan en C-03, así que la verificación de C-02 necesita entidades propias descartables (D10).

## Goals / Non-Goals

**Goals:**
- Que C-03, C-07, C-10… sólo tengan que declarar modelos, subclases de repo y su UoW; ninguna decisión transaccional ni de errores se repite por módulo.
- Que las violaciones de las reglas duras sean difíciles de cometer por accidente (UoW anidado, `password_hash` en salida, id fuera de rango) y fáciles de detectar por grep en la corrección.
- Dejar evidencia ejecutable de cada escenario de las specs sin pytest.

**Non-Goals:**
- Modelos, restricciones con nombre y `naming_convention` (C-03); UoW y repos de cada módulo (C-07, C-10, C-11, C-13); `EstadoOrdenRepository` (C-13); sesión propia de `intento_acceso` (C-07); dependencias de auth y 401/403 (C-08); validación de 72 bytes (C-05/C-07).
- Traducir al español los mensajes de validación de Pydantic (se mantiene `msg` de Pydantic; ver Open Questions).
- Concurrencia / bloqueo optimista (DD-11, cap. 7).

## Decisions

### D1 — `BaseRepository[T]`: genérico PEP 695 con consulta base reutilizable
```
class BaseRepository[T: SQLModel]:
    def __init__(self, session: AsyncSession, model: type[T]) -> None
    def _consulta_base(self) -> SelectOfScalar[T]          # select(model); hook de filtros
    async def get_by_id(self, id: int) -> T | None
    async def get_all(self, *, offset: int = 0, limit: int | None = None) -> list[T]
    async def count(self) -> int
    async def add(self, entidad: T) -> T                    # session.add + flush
    async def update(self, entidad: T, datos: Mapping[str, Any]) -> T   # setattr + flush
    async def delete(self, entidad: T) -> None              # session.delete + flush
    async def _contar(self, consulta) -> int                # SELECT count(*) FROM (consulta) sub
```
- Las subclases de cada módulo pasan su modelo en `super().__init__(session, Cliente)` y escriben métodos nombrados por lo que traen (`get_by_documento`, `get_detalle_by_id` con `selectinload`), partiendo de `self._consulta_base()` y contando con `self._contar(...)` → `total` siempre con los mismos filtros que la página (spec list-pagination) y las bajas lógicas excluidas sin repetir el filtro.
- `get_by_id` usa `select ... where id == :id` sobre `_consulta_base()` y **no** `session.get()`: `get()` devuelve del identity map sin pasar por el filtro de bajas.
- `get_all` ordena por `id` ascendente (paginación determinista); `limit=None` = sin límite.
- `update` recibe el dict de `dto.model_dump(exclude_unset=True)` (PATCH parcial lo arma el servicio); rechaza con `ValueError` claves que no son campos del modelo o `id` (error de programación → 500 genérico; el `extra="forbid"` del DTO hace que nunca lo dispare una entrada del usuario).
- `delete` también hace `flush()` (no lo exige la consigna) para que una FK que impida el borrado falle dentro del bloque con el error correcto.
- Lecturas con `session.exec(...)` de SQLModel (C-01 D7: `execute` de SQLModel emite `DeprecationWarning`).
- *Alternativas*: `Generic[T]` + `TypeVar` (equivalente; PEP 695 es la sintaxis de 3.12, versión mínima del stack — si el equipo prefiere la forma clásica, es intercambiable); inferir el modelo con `__orig_bases__` — descartado, la consigna pide explícitamente la clase en el constructor.

### D2 — `add` sin `refresh()`: defaults de servidor vía RETURNING
SQLAlchemy 2.0 usa `eager_defaults="auto"`: en PostgreSQL el INSERT trae con `RETURNING` la PK y los defaults de servidor, así que tras `flush()` la entidad está completa sin un SELECT extra y sin carga perezosa. **Riesgo documentado para C-03**: un `server_onupdate` o un default calculado en UPDATE dejaría el atributo expirado → acceso perezoso → `MissingGreenlet`. Regla para C-03: no usar `server_onupdate`; si hace falta, el repo hace `await session.refresh(entidad, ["campo"])` dentro del método.

### D3 — `SoftDeleteRepository[T]`
- Hereda de `BaseRepository[T]`; sobrescribe `_consulta_base()` agregando `where(model.borrado_en.is_(None))` → `get_by_id`, `get_all`, `count` y todos los métodos de las subclases excluyen bajas automáticamente.
- `get_by_id_including_deleted(id)` consulta `select(model)` sin el filtro.
- `soft_delete(entidad)` asigna `datetime.now(UTC)` (valor Python con zona, no `func.now()`: una expresión SQL deja el atributo expirado y su lectura posterior sería perezosa) y hace `flush()`. Si ya tenía baja, no la pisa (conserva la fecha original). Las reglas de negocio (RN16: vehículo con órdenes abiertas → 409) las decide el servicio antes de llamar.
- El constructor verifica que el modelo tenga `borrado_en` (falla al construir, no en la primera consulta).
- `delete` (físico) se hereda tal cual; los servicios de vehículos/repuestos usan `soft_delete`.

### D4 — `UnitOfWork` base
```
class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None   # recibe, no crea
    async def __aenter__(self) -> Self                  # RuntimeError si ya está abierto
    async def __aexit__(self, exc_type, exc, tb) -> None:
        sin excepción → commit(); si commit falla → rollback() y re-raise
        con excepción → rollback(); la excepción se propaga (no se suprime)
        nunca close()
```
- Flag `_abierto` contra la apertura anidada (spec "Sin apertura anidada"): un `async with uow` interno confirmaría a mitad de la operación del externo.
- Bloques sucesivos en la misma petición son transacciones independientes (autobegin de la sesión). Las lecturas también van dentro del bloque (el commit de un bloque sólo-lectura es inocuo).
- No expone `commit()` público: confirmar es salir del bloque.
- **UoW por módulo** (patrón que siguen C-07, C-10…; no se implementa ninguno acá):
```
class ClientesUoW(UnitOfWork):
    def __init__(self, session):
        super().__init__(session)
        self.clientes = ClienteRepository(session)
        self.vehiculos = VehiculoRepository(session)

def get_clientes_uow(session: SessionDep) -> ClientesUoW: return ClientesUoW(session)
ClientesUoWDep = Annotated[ClientesUoW, Depends(get_clientes_uow)]
# router: async def alta(datos: ClienteAlta, uow: ClientesUoWDep) -> ClienteSalida:
#             return await servicio.alta(uow, datos)
# servicio: async with uow: ...
```
  El docstring de `unit_of_work.py` deja este patrón escrito para B y C.
- `intento_acceso` (C-07) no usa este UoW: abre `request.app.state.session_factory()` propia, con comentario de la excepción (RN08/DD-07). C-02 sólo lo deja en la spec.
- *Alternativa*: que el UoW cree la sesión desde la fábrica — descartada: la consigna dice que no la cierra "porque no la creó", y C-01 ya cierra la sesión en `get_session`.

### D5 — Paginación (`app/core/paginacion.py`)
- `Paginacion` (dataclass congelada `page`, `size`, propiedad `offset`) construida por la dependencia `parametros_paginacion(page: Annotated[int, Query(ge=1)] = 1, size: Annotated[int, Query(ge=1, le=100)] = 20)`; alias `PaginacionDep`. Las restricciones `Query` dan 422 antes del handler (spec "Tamaño excesivo").
- `Pagina[T]` modelo Pydantic genérico `{items: list[T], total, page, size, pages}` con `extra="forbid"`.
- `calcular_paginas(total, size) = max(1, ceil(total / size))` → 0 resultados = 1 página vacía.
- Flujo en el servicio: `total = await repo.contar_x(...)` → `verificar_pagina(pag, total)` (lanza `EntradaInvalida(f"La página {page} no existe: hay {pages}")`) → `items = await repo.listar_x(offset=pag.offset, limit=pag.size)` → `armar_pagina(items, total, pag)`. Contar primero evita traer filas de una página que igual da 422.
- *Alternativa descartada*: modelo de query params (`Annotated[Modelo, Query()]` con `extra="forbid"`): rechazaría cualquier filtro no declarado en el mismo modelo y obliga a cada módulo a heredarlo; la dependencia simple compone mejor con filtros propios (`q`, `estado`).

### D6 — Contrato de DTOs (`app/core/schemas.py`, nombre a confirmar)
- `EntradaBase(BaseModel)`: `ConfigDict(extra="forbid")`. Todo cuerpo de entrada hereda de ella (PATCH incluidos).
- `SalidaBase(BaseModel)`: `ConfigDict(from_attributes=True)`; `__pydantic_init_subclass__` revisa cada subclase con `rechazar_salida_insegura(cls)` y lanza `TypeError` si expone `password_hash` (campo, alias o `computed_field`) **a cualquier profundidad** — recorre modelos anidados, dataclasses y TypedDict a través de `Optional`/`list`/`dict`/`tuple`/uniones/`Annotated`/alias `type` — o si alcanza un modelo de tabla (`table=True`); una referencia adelantada sin resolver también se rechaza (falla cerrado) → falla al importar (spec api-contracts). `Pagina[X]` aplica la misma función en su propio `__pydantic_init_subclass__` (Pagina es un `BaseModel` plano; sus parametrizaciones son subclases). Convención: handlers declaran tipo de retorno con un `*Salida`; nunca devuelven el modelo de tabla.
- `IdRuta = Annotated[int, Path(ge=1, le=2_147_483_647)]`: tope de `INTEGER` de PostgreSQL (los `id: int` de SQLModel autogeneran `INTEGER`). Evita el 500 del hallazgo de Context en el caso normal.
- *Alternativa*: un test que recorra `/openapi.json` buscando `password_hash` — se hace igual como verificación, pero el guard al importar lo vuelve imposible de olvidar.

### D7 — Excepciones de aplicación (`app/core/errores.py`, nombre a confirmar)
- `ErrorDeAplicacion(Exception)` con `mensaje` y `status_code`; subclases `NoEncontrado` (404), `Conflicto` (409), `EntradaInvalida` (422). Los **servicios** las lanzan (no conocen HTTP); un manejador global las traduce a `{"detail": mensaje}`. Los routers quedan finos: construyen UoW, llaman al servicio, y sólo atrapan algo si necesitan una traducción propia.
- *Alternativa*: servicios lanzando `HTTPException` (compact rule fastapi-python: "HTTPException for expected errors") — más corto, pero acopla la capa de negocio a HTTP. **Checkpoint**: convención que heredan B y C (Q1).

### D8 — Traducción de errores de base
- `sqlstate(exc: DBAPIError) -> str | None` = `exc.orig.pgcode` (o `sqlstate` de `exc.orig.__cause__`); `restriccion_violada(exc: IntegrityError) -> str | None` = `exc.orig.__cause__.constraint_name`. Ambas defensivas (`getattr`), nunca lanzan.
- **Traducción específica en el servicio** (conoce el dominio), fuera del bloque:
```
try:
    async with uow: ...
except IntegrityError as exc:
    if restriccion_violada(exc) == "uq_usuario_email":
        raise Conflicto("El correo ya está registrado") from None
    raise
```
  Depende de que C-03 nombre las restricciones de forma estable (`naming_convention` en `SQLModel.metadata` o `name=` explícito) — se anota como requisito para C-03.
- **Manejadores globales** (fallback, `registrar_manejadores(app)` llamado en `main.py`):

| Excepción | Código | `detail` |
|---|---|---|
| `ErrorDeAplicacion` | su `status_code` | su mensaje |
| `IntegrityError` sqlstate `23505` (unique) / `23503` (FK) | 409 | «La operación choca con datos ya registrados» |
| `IntegrityError` sqlstate `23514` (check) / `23502` (not null) / otro `23xxx` | 422 | «Los datos no cumplen las restricciones del sistema» |
| `DBAPIError` sqlstate `22xxx`, o `InterfaceError` cuyo `__cause__` es `asyncpg…_base.DataError` | 422 | «Algún valor está fuera del rango o del formato permitido» |
| `RequestValidationError` | 422 | lista con `loc`, `msg`, `type` por error (**sin** `input`, `ctx`, `url`) |
| `Exception` (resto) | 500 | «Error interno del servidor» |
- Log del servidor: para 409/422 de base, sólo `sqlstate` + nombre de restricción (no el texto del driver, que puede traer valores del usuario); para 500, `logger.exception` (traza sólo en el log, nunca en la respuesta).
- `RequestValidationError` se sobrescribe porque el 422 por defecto de FastAPI incluye `input` → reflejaría contraseñas; y `ctx` puede contener objetos de excepción.
- `HTTPException` (401/403 de C-08) sigue con el manejador por defecto de FastAPI, que ya da `{"detail": ...}`: misma forma.
- El manejador de `Exception` lo atiende `ServerErrorMiddleware` (la excepción igual se registra); se usa sólo para garantizar cuerpo JSON propio.
- Mapeo de CHECK a 422 (no 409): un CHECK que la base rechaza es un dato que no cumple la regla (p. ej. `precio > 0`); los conflictos de estado (stock insuficiente, RN13) los detecta el servicio antes y lanza `Conflicto`. **Checkpoint** Q2.

### D9 — Ubicación de los archivos nuevos
La estructura obligatoria lista en `app/core/` sólo `config, database, security, dependencies, repository, paginacion, unit_of_work`. Propuesta: agregar `schemas.py` (D6) y `errores.py` (D7–D8); `main.py` sólo suma `registrar_manejadores(app)`. *Alternativa*: meter DTO base en `paginacion.py`/`repository.py` y manejadores en `main.py` — no agrega archivos pero mezcla responsabilidades y hace crecer `main.py`, que tocan A, B y C. **Checkpoint** Q3.

### D10 — Verificación sin pytest: script descartable contra base descartable
- No hay modelos ni endpoints de dominio todavía y `create_all` está prohibido en la app. Se verifica con `verificar_c02.py` en el **scratchpad de la sesión** (no se versiona, no va en `test/`, que es sólo `.http`/`.sql`), que:
  1. Se conecta a una base **descartable** `taller_verif_c02` (creada con `createdb` y borrada con `dropdb` al final; nunca la base de desarrollo).
  2. Crea con **DDL SQL explícito** (no `create_all`) dos tablas de prueba: `verif_item` (`id`, `nombre` UNIQUE con nombre `uq_verif_item_nombre`, `cantidad` con CHECK `> 0`, `borrado_en timestamptz`) y `verif_hijo` (FK a `verif_item`), y define sus modelos SQLModel sólo dentro del script.
  3. Ejercita repositorios y UoW directamente contra la fábrica de `app.core.database` y verifica cada escenario de `data-repositories` y `unit-of-work` con `assert` y mensajes legibles (visibilidad desde otra conexión incluida).
  4. Monta una `FastAPI()` de prueba con `registrar_manejadores(app)` y rutas de prueba (id de ruta, cuerpo `EntradaBase`, listado paginado, operaciones que violan unique/FK/CHECK, error inesperado) y las llama con `httpx.AsyncClient(transport=ASGITransport(app))` (httpx viene con `fastapi[standard]`), verificando `list-pagination`, `api-contracts` y `error-translation`, incluido que ningún cuerpo contenga `duplicate key`/`violates`/`asyncpg`/`sqlalchemy`/`Traceback`/nombre de restricción.
- La app real se verifica además con `uvicorn main:app` (arranca, `/health/*` sigue igual, `/openapi.json` sin `password_hash`).
- Evidencia: salida del script pegada en el resumen del apply. Strict TDD global no aplica tal cual (sin runner, decisión del TP, igual que C-01 D11); el script hace de RED→GREEN: se escribe la verificación de cada grupo antes de su código y se corre hasta pasar. **Checkpoint** Q4 (crear/borrar la base descartable).

## Risks / Trade-offs

- [Mensaje específico depende del nombre de la restricción definido en C-03] → requisito explícito para C-03 (`naming_convention`); sin nombre estable cae al genérico (sigue sin filtrar, sólo menos preciso).
- [`IntegrityError` lanzado en `flush()` dentro del bloque deja la sesión en estado fallido] → el UoW revierte al salir; el servicio sólo traduce **fuera** del `async with`, nunca reintenta dentro.
- [Mapear todo `22xxx` a 422 puede ocultar un bug del servidor (p. ej. división por cero en SQL)] → se loguea `sqlstate`; el contrato y `IdRuta` atajan lo previsible antes de la base.
- [Acceder a una relación de una entidad recién agregada dispara carga perezosa → `MissingGreenlet`] → regla en el docstring: tras `add`, releer con el método del repo que precarga. Recomendación para C-03: `sa_relationship_kwargs={"lazy": "raise"}` para que el error sea explícito.
- [El guard revisa nombre, alias y alias de serialización `password_hash`, pero no lo declarado como `Any`/`object` ni un renombrado arbitrario] → suficiente para la consigna; además se verifica `/openapi.json` de la app real.
- [`rollback()` puede fallar (conexión caída) y, lanzado dentro de `__aexit__`, taparía la excepción original] → `UnitOfWork._revertir()` lo captura (`Exception`, no `BaseException`), lo registra con `logger.exception` y deja propagar la original.
- [Leer un atributo de una entidad tras el rollback dispara carga perezosa → `MissingGreenlet` → 500 en lugar de 409/422] → el docstring del UoW indica capturar los valores necesarios antes de salir del bloque.
- [El handler de `Exception` no evita que `uvicorn` imprima la traza] → esperado: la traza va al log del servidor, no a la respuesta.
- [PEP 695 puede no ser familiar para B y C] → docstrings con ejemplo; intercambiable por `Generic[T]` sin cambiar la API.

## Migration Plan

Sin migraciones ni cambios de esquema. Despliegue = merge de la rama `feat/C-02-core-repository-uow`. Rollback: revertir los archivos nuevos y la línea de `main.py`; la base de desarrollo no se toca (la de verificación se borra al terminar).

## Open Questions

Ninguna diferible: las cuatro preguntas abiertas afectan lo que se construye y están como checkpoints bloqueantes al inicio de tasks (Q1 convención de excepciones, Q2 CHECK→422, Q3 archivos nuevos en `app/core/`, Q4 base descartable de verificación). Diferible sin impacto: traducir al español los `msg` de validación de Pydantic (se puede sumar después en el mismo manejador sin cambiar la forma de la respuesta).
