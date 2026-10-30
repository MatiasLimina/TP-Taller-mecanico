# Design — C-06 seed-script

## Context

Motivación en proposal.md — Why; requisitos en `specs/seed-data` y `specs/security-events`. Estado actual relevante:

- **Esquema (C-03/C-04)**: 13 tablas registradas en `app/modules/modelos.py` (importarlo carga `SQLModel.metadata` completo y resuelve las relaciones). La migración 2 (`9141e6428bad_solo_agregado.py`) instala `trg_solo_agregado` **`BEFORE UPDATE OR DELETE … FOR EACH ROW`** sobre `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`: un `DELETE` del seed fallaría con `P0001`, pero `TRUNCATE` no dispara triggers por fila. Su docstring y la spec `append-only-history` («Vaciado completo para recarga») ya reservan `TRUNCATE … RESTART IDENTITY CASCADE` para el seed. `estado_orden` nace vacío (spec `schema-migrations`).
- **Columnas que obligan a elegir un usuario**: `movimiento_stock.usuario_id`, `historial_precio_repuesto.usuario_id` e `historial_estado_orden.usuario_id` son NOT NULL con FK a `usuario`. `asignacion_rol.otorgada_por` admite nulo. `evento_seguridad.actor` es texto libre.
- **Infraestructura reutilizable**: `get_settings()` (lee `.env`; falla si falta `POSTGRES_PASSWORD` o `SECRET_KEY`), `create_engine(settings)` / `create_session_factory(engine)` de `app/core/database.py`, `UnitOfWork(session)` de `app/core/unit_of_work.py` (único lugar que confirma; rollback ante excepción), `BaseRepository(session, Model).add()` (hace `flush()`, nunca confirma), `hash_password()` de `app/core/security.py` (`to_thread` + semáforo, costo `BCRYPT_COST`), `CorreoNormalizado` de `app/modules/usuarios/schemas.py` (`EmailStr` + recorte + minúsculas: lo mismo que valida el login), `ahora_utc()` de `app/core/modelo_base.py`, enums `Rol` y `CodigoEstado`.
- **Archivos `.http` existentes**: preparan su estado con bloques `psql` porque no había seed. `test/auth.http` limpia con `LIKE '%@example.com'` (coincide con los correos del seed, y los `DELETE` fallarían por FK contra órdenes y movimientos) e inserta a "Jorge Sin Usuario" con documento `20111222`. `test/personal.http` (caso 62) exige que `jefa` sea el **único** ADMIN vigente sin vencimiento. Documentos usados por los `.http`: `20111222`, `30123456`, `40123456`, `41000001-2`, `42000001-2`, `50000001-3`, `60000001`, `70000001-8`, `80000001`.

## Goals / Non-Goals

**Goals:**

- Un único comando reproducible (`python seed.py`) que deja la base en un estado conocido con ids deterministas, apto para escribir `.http` con ids fijos.
- Reutilizar las piezas de `app/` (configuración, motor, UoW, repositorio genérico, hashing, tipo de correo, modelos y enums) en lugar de duplicarlas: el seed falla si los modelos y el esquema se desincronizan.
- Respetar las reglas duras aun siendo un script: sin `commit()` fuera del UoW, bcrypt fuera de la transacción, sin SQL armado con datos externos, `Decimal` para dinero, fechas con zona.

**Non-Goals:**

- Ejercer las reglas de negocio de la API: el seed escribe filas directamente (no llama a servicios ni endpoints), así que no deja eventos por alta/asignación ni pasa por los controles de C-10…C-15. La coherencia de los datos la garantiza el propio seed (D7) y la verifica `test/seed.sql`.
- Modo parcial, "sin vaciar", parámetros de línea de comandos o datos aleatorios.
- Proteger contra correrlo sobre una base con datos reales (ver Riesgos).

## Decisions

### D1 — Estructura de `seed.py` (raíz del proyecto)

KB 08 lo ubica en la raíz (`seed.py  # estado inicial conocido (vacía y carga)`). Un solo archivo, sin clases de servicio; funciones chicas con firma fija para que la implementación sea mecánica:

```python
import app.modules.modelos  # registra las 13 tablas antes de usar metadata o relaciones

CONTRASENA_PRUEBA = "ClaveSegura1"        # de mentira; sólo acá (y como dato en los .http)
CONTRASENA_PROVISORIA = "Provisoria1"     # nuevo@example.com, con cambio obligatorio
ACTOR_SISTEMA = "SISTEMA"
ACCION_CARGA = "Carga de los datos iniciales"
MOTIVO_STOCK_INICIAL = "Stock inicial"
CANTIDAD_TABLAS = 13

@dataclass(frozen=True, slots=True)
class UsuarioSeed:
    email: str
    nombre: str
    password: str
    rol: Rol
    debe_cambiar_password: bool = False

USUARIOS: tuple[UsuarioSeed, ...]                      # orden fijo = ids 1..7 (D6)
ESTADOS: dict[CodigoEstado, tuple[str, int, bool]]    # descripcion, posicion, es_final

def verificar_correos(correos: Iterable[str]) -> None                       # D3; ValueError
async def calcular_hashes(usuarios: Sequence[UsuarioSeed]) -> list[str]     # D4; antes del UoW
async def vaciar_tablas(session: AsyncSession) -> None                      # D2
async def _agregar[T: SQLModel](session: AsyncSession, entidad: T) -> T     # BaseRepository(...).add
async def cargar_catalogo(session: AsyncSession) -> None
async def cargar_usuarios(session: AsyncSession, hashes: Sequence[str]) -> dict[str, int]   # email -> id
async def cargar_clientes(session: AsyncSession, ids: Mapping[str, int]) -> list[int]       # ids de vehículos
async def cargar_repuestos(session: AsyncSession, ids: Mapping[str, int]) -> dict[str, Repuesto]  # por código
async def cargar_ordenes(session: AsyncSession, ids: Mapping[str, int],
                         vehiculos: Sequence[int], repuestos: Mapping[str, Repuesto]) -> None
async def cargar_evento_sistema(session: AsyncSession) -> None
async def contar_filas(session: AsyncSession) -> dict[str, int]             # tabla -> count(*)
async def sembrar(session_factory: async_sessionmaker[AsyncSession],
                  hashes: Sequence[str]) -> dict[str, int]          # conteo por tabla
async def main() -> int                                                      # código de salida

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

Flujo de `main()`: `verificar_correos` → `get_settings()` → `calcular_hashes` → `create_engine` + `create_session_factory` → `sembrar` → imprimir resumen → `engine.dispose()` en `finally`. `ValueError` de correos y `pydantic.ValidationError` de configuración se imprimen en `stderr` (sin valores: `Settings` usa `hide_input_in_errors`) y devuelven 1 sin crear el motor. Cualquier otra excepción se propaga (traza y código 1).

Flujo de `sembrar()` (una transacción, D5):

```python
async with session_factory() as session:
    async with UnitOfWork(session):
        await vaciar_tablas(session)
        await cargar_catalogo(session)
        ids = await cargar_usuarios(session, hashes)
        vehiculos = await cargar_clientes(session, ids)
        repuestos = await cargar_repuestos(session, ids)
        await cargar_ordenes(session, ids, vehiculos, repuestos)
        await cargar_evento_sistema(session)
        conteo = await contar_filas(session)
return conteo
```

- *Alternativa descartada*: paquete `app/seed/` o módulos por tabla — más estructura de la que pide un script de ~250 líneas y se aparta de la KB.
- *Alternativa descartada*: cargar por la API (`httpx` contra los endpoints) — dejaría eventos por cada alta, exigiría un primer ADMIN previo y endpoints que todavía no existen (C-10…C-15).

### D2 — Vaciado: un `TRUNCATE … RESTART IDENTITY CASCADE` de las 13 tablas

```python
tablas = [t.name for t in SQLModel.metadata.sorted_tables]
assert len(tablas) == CANTIDAD_TABLAS
# Nombres de la metadata del código (constantes), nunca datos externos.
await session.exec(text(f"TRUNCATE TABLE {', '.join(tablas)} RESTART IDENTITY CASCADE"))  # type: ignore[call-overload]
```

- `TRUNCATE` no dispara los triggers `FOR EACH ROW` de sólo agregado (no hay `ON TRUNCATE`), es transaccional en PostgreSQL y reinicia las identidades → ids 1..n en cada corrida (idempotencia observable).
- `alembic_version` no está en la metadata: no se toca. Una sola sentencia con todas las tablas resuelve el orden de FKs; `CASCADE` queda como red por si una tabla nueva referenciara a otra.
- *Alternativas descartadas*: `DELETE FROM` (el trigger lo rechaza con `P0001` en las tres tablas de sólo agregado); `ALTER TABLE … DISABLE TRIGGER` + `DELETE` (apaga la protección, aunque sea dentro de la transacción, y no reinicia identidades); `alembic downgrade base` + `upgrade head` (lento, mezcla datos con migraciones y exige permisos de DDL completos); `DROP SCHEMA` (borra también `alembic_version`).

### D3 — Correos: verificar y fallar, no normalizar (S-03)

```python
_ADAPTADOR_CORREO = TypeAdapter(CorreoNormalizado)

def verificar_correos(correos: Iterable[str]) -> None:
    for correo in correos:
        try:
            normalizado = _ADAPTADOR_CORREO.validate_python(correo)
        except ValidationError:
            raise ValueError(f"Correo inválido en seed.py: {correo!r}") from None
        if normalizado != correo:
            raise ValueError(f"Correo no normalizado en seed.py: {correo!r} (se esperaba {normalizado!r})")
```

Se usa el **mismo tipo** que el login, así que lo que acepta el seed es exactamente lo que el login acepta: rechaza mayúsculas, espacios y los dominios de uso especial (`.local`, `.test`, `.localhost`) que `EmailStr` no admite (revisión de C-07). Corre antes de leer la configuración y de conectarse.

- *Alternativa descartada*: normalizar en silencio — el correo escrito en `seed.py` y el de la base diferirían, y un `.http` copiado de `seed.py` fallaría sin explicación. Los correos son constantes del código: un error ahí es un bug que debe verse.
- *Alternativa descartada*: imponerlo en la base (CHECK `email = lower(email)`) — exigiría una tercera migración (la consigna fija dos; S-01 de C-07).

### D4 — Contraseñas y hashes (S-05)

- `ClaveSegura1` para los seis usuarios sin cambio pendiente (la misma convención de `test/auth.http` y `test/sesion.http`) y `Provisoria1` para `nuevo@example.com`. Cumplen el contrato de `PasswordRegistro` (≥ 8 caracteres, ≤ 72 bytes).
- `calcular_hashes` hace `await asyncio.gather(*(hash_password(u.password) for u in usuarios))` **antes** de abrir la conexión: un hash por usuario (sal distinta), con el costo de `BCRYPT_COST`; el semáforo de `security.py` limita la concurrencia. Nunca se imprimen.
- *Alternativa descartada*: una contraseña distinta por usuario — no agrega nada a un dato de prueba y complica cada `.http`. *Alternativa descartada*: un solo hash reutilizado — más rápido, pero el seed debe producir lo mismo que la API (un hash por cuenta).

### D5 — Una transacción para vaciar y cargar (atomicidad)

El `UnitOfWork` base de `app/core` confirma al salir del bloque y revierte ante cualquier excepción; como `TRUNCATE` es transaccional, una falla a mitad de la carga deja la base como estaba (spec «Recarga atómica»). Todas las inserciones usan `BaseRepository(session, type(entidad)).add(entidad)` (flush, ids disponibles, sin `commit()`), envuelto en `_agregar`. `TRUNCATE` toma `ACCESS EXCLUSIVE` sobre las tablas: las peticiones de un uvicorn abierto esperan hasta el final del seed (ver Riesgos).

### D6 — Datos exactos (KB 04 + supuestos S-06…S-08)

Orden de inserción fijo (los ids salen de él, con identidades reiniciadas):

| Tabla | Filas (id → datos) |
|-------|--------------------|
| `estado_orden` | `PENDIENTE` (1, no final, "Orden registrada, a la espera de un mecánico"), `EN_REPARACION` (2, no final, "Un mecánico está trabajando en el vehículo"), `TERMINADA` (3, final, "Reparación terminada; repuestos descontados del stock"), `CANCELADA` (4, final, "Orden cancelada sin reparación"). Se itera `CodigoEstado`; `set(ESTADOS) == set(CodigoEstado)` se comprueba al cargar. |
| `usuario` | 1 `admin@example.com` "Adriana Admin"; 2 `admin2@example.com` "Alberto Admin"; 3 `recepcion@example.com` "Rita Recepción"; 4 `mecanico@example.com` "Mario Mecánico"; 5 `mecanico2@example.com` "Marta Mecánica"; 6 `cliente@example.com` "Laura Martínez"; 7 `nuevo@example.com` "Nicolás Nuevo" (`debe_cambiar_password = true`). Todos `activo = true`, `password_cambiada_en` nulo. |
| `asignacion_rol` | Una por usuario, en el mismo orden (ids 1..7): ADMIN, ADMIN, RECEPCION, MECANICO, MECANICO, CLIENTE, MECANICO; `vence_en`, `revocada_en` y `otorgada_por` nulos. |
| `cliente` | 1 "Laura Martínez", `usuario_id` 6, documento `28111222`, teléfono `1144440001`; 2 "Jorge Pérez", sin usuario, documento `25111333`, teléfono `1144440002`. |
| `vehiculo` | 1 `AB123CD` Toyota Corolla 2019 (Laura); 2 `AC456EF` Volkswagen Gol 2015 (Laura); 3 `AD789GH` Ford Fiesta 2012 (Jorge). |
| `repuesto` | 1 `FIL-ACE-01` "Filtro de aceite" 8500.00, stock 10; 2 `PAS-FRE-DEL` "Pastillas de freno delanteras" 32000.00, 4; 3 `BUJ-01` "Bujía" 4500.00, 2; 4 `ACE-5W30-1L` "Aceite 5W30 por litro" 12000.00, 20. Precios con `Decimal("…")`. |
| `movimiento_stock` | 1..4: un `+stock` por repuesto, motivo `Stock inicial`, `orden_id` nulo, `usuario_id` 1. |
| `historial_precio_repuesto` | 1: repuesto 1, `usuario_id` 1, `8000.00 → 8500.00`. |
| `orden_trabajo` | 1: vehículo 1, sin mecánico, `PENDIENTE`, falla "Service de los 30.000 km: cambio de aceite y filtro", total 56500.00. 2: vehículo 3, mecánico 4, `EN_REPARACION`, falla "El motor falla en frío y tironea al acelerar", total 18000.00. |
| `item_orden` | 1: orden 1, repuesto 1, cantidad 1, 8500.00; 2: orden 1, repuesto 4, cantidad 4, 12000.00; 3: orden 2, repuesto 3, cantidad 4, 4500.00. |
| `historial_estado_orden` | 1: orden 1, `NULL → PENDIENTE`, usuario 3; 2: orden 2, `NULL → PENDIENTE`, usuario 3; 3: orden 2, `PENDIENTE → EN_REPARACION`, usuario 4. |
| `evento_seguridad` | 1: actor `SISTEMA`, acción `Carga de los datos iniciales`. |
| `intento_acceso` | vacía. |

Conteos finales: 4, 7, 7, 0, 1, 2, 3, 4, 4, 1, 2, 3, 3 (en el orden `estado_orden`, `usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`, `cliente`, `vehiculo`, `repuesto`, `movimiento_stock`, `historial_precio_repuesto`, `orden_trabajo`, `item_orden`, `historial_estado_orden`).

### D7 — Coherencia calculada, no escrita a mano

- `precio_unitario` de cada ítem se copia de `repuesto.precio` (objeto cargado), y `total` de la orden es `sum(cantidad * precio_unitario)` en `Decimal` — igual que exige RN10 a la API.
- `repuesto.stock` y la `cantidad` de su movimiento salen del mismo número; el precio del filtro (8500.00) es el `precio_nuevo` de su línea de historial.
- La orden 2 **no** descuenta stock (el stock se descuenta al terminar, RN13): bujía queda en 2 con 4 pedidas (IN-04, a propósito para C-11/C-12).
- Fechas: los `default_factory=ahora_utc` de los modelos (con zona); no se fijan fechas a mano.

### D8 — Verificación sin pytest (Strict TDD adaptado)

- **`test/seed.sql`** (versionado, sólo lectura, para `psql -f`): una consulta por requisito de `specs/seed-data` con el resultado esperado en comentario (conteos D6, catálogo, usuarios/roles/ADMIN sin vencimiento, correos `= lower(trim(email))`, hash `$2b$<costo>$`, stock = suma de movimientos, historial de precio, órdenes con total = suma de ítems e historial, evento `SISTEMA`). No usa credenciales ni escribe.
- **`test/seed.http`** (versionado): login de los siete usuarios con su contraseña de prueba (200), `GET /auth/yo` con roles, `nuevo@` → 403 por cambio pendiente en `GET /eventos`, `admin@` → `GET /eventos` con `total` 1 y el evento `SISTEMA`.
- **RED**: los dos archivos se escriben primero y se corren sobre la base migrada **sin** seed: conteos en 0, logins 401.
- **GREEN/TRIANGULATE**: tres corridas — seed sobre base vacía; seed por segunda vez (la base ya tiene filas en las tres tablas de sólo agregado, las del propio seed); seed sobre la base que dejan `auth.http`, `sesion.http` y `personal.http` (usuarios, roles, eventos e intentos ajenos al seed). La salida de `test/seed.sql` debe ser idéntica en las tres corridas. `test/solo_agregado.sql` no sirve para sembrar filas de sólo agregado: termina en `ROLLBACK`.
- **Lo que psql no muestra** se comprueba con un script temporal `$env:TEMP\verificar_c06.py` (no versionado): (a) `verificar_correos` rechaza `Admin@example.com`, `" admin@example.com"`, `x@taller.local`, `x@taller.test`, `x@localhost` y acepta los siete del seed; (b) atomicidad: reemplazar `seed.cargar_evento_sistema` por una función que lanza `RuntimeError`, llamar `sembrar` y comprobar que los conteos por tabla son los de antes; (c) la salida de `main()` no contiene `ClaveSegura1`, `Provisoria1`, `$2b$` ni la contraseña de la base.

### D9 — Encabezados de los `.http` existentes (S-09)

Sólo comentarios; ningún caso cambia:

- `test/auth.http`: agregar el camino "con el seed": `python seed.py` y después **sólo** el `INSERT` de "Jorge Sin Usuario" (`20111222`), **sin** los `DELETE` (el seed ya vació todo; los `DELETE … LIKE '%@example.com'` alcanzarían a los usuarios del seed y fallarían por FK). Los documentos del seed no coinciden con los del archivo, así que el caso 6 sigue usando su propia ficha.
- `test/personal.http`: reemplazar "correr `python seed.py` antes y luego el bloque de arriba" por: `python seed.py`, después `UPDATE asignacion_rol SET revocada_en = now() WHERE rol = 'ADMIN' AND revocada_en IS NULL;` (el caso 62 exige que `jefa` sea el único ADMIN sin vencimiento; `asignacion_rol` no es de sólo agregado) y después el bloque de limpieza. Lo mismo vale como precondición del script de concurrencia de C-09.
- `test/sesion.http`: su nota actual ("`python seed.py` antes y luego el bloque") ya es correcta (sus correos son `@sesion.example.com`); no se toca salvo que la corrida de 7.x muestre lo contrario.

## Risks / Trade-offs

- [Borra todos los datos de la base configurada] → es el comportamiento pedido por la consigna. Mitigación: docstring y salida que lo dicen explícitamente; la base sale del mismo `.env` que la app (nunca una URL por defecto). No se agrega confirmación interactiva (rompería su uso antes de cada `.http`).
- [`TRUNCATE` con uvicorn corriendo] → toma `ACCESS EXCLUSIVE`; las peticiones concurrentes esperan hasta que el seed confirme (menos de un segundo después de los hashes, que van antes de abrir la conexión). Las sesiones abiertas quedan con tokens de ids que ahora son otros usuarios: hay que volver a iniciar sesión después de cada seed (los `.http` ya lo hacen).
- [El dueño de la tabla puede `TRUNCATE` historiales de sólo agregado] → límite ya documentado en C-04 (un solo rol de base). El seed es la única vía que lo usa.
- [Ids deterministas dependen del orden de inserción] → el orden está fijo en `USUARIOS` y en las funciones `cargar_*`; `test/seed.sql` verifica los ids.
- [Los `.http` futuros dependen de estos datos] → cambiar un dato del seed obliga a revisar C-10…C-16; D6 es la referencia única.
- [Tiempo de bcrypt] → 7 hashes con costo 12 y concurrencia 4 ≈ 1 s; aceptable para un comando de puesta en marcha.

## Migration Plan

Sin migraciones ni cambios de modelos. Puesta en marcha (Flujo 9): `alembic upgrade head` → `python seed.py` → `uvicorn main:app`. Rollback: borrar `seed.py`, `test/seed.sql` y `test/seed.http` y revertir los comentarios de los dos `.http`; los datos se regeneran corriendo otra vez el seed o vaciando con el mismo `TRUNCATE`.

## Supuestos a confirmar (S-01…S-10)

- **S-01 — Vaciado con `TRUNCATE … RESTART IDENTITY CASCADE` de las 13 tablas de la metadata** (D2). Descartados: `DELETE` (bloqueado por el trigger), desactivar triggers, `downgrade`/`upgrade`.
- **S-02 — Una sola transacción para vaciar y cargar** (D5), con el `UnitOfWork` base de `app/core` construido en el script (el script hace de "router": construye y abre el UoW; no hay servicio).
- **S-03 — Correos: el seed verifica con `CorreoNormalizado` y falla, no normaliza** (D3).
- **S-04 — Conexión desde `get_settings()` (`.env`)**, la misma que la app y Alembic; sin argumentos ni URL en el script; errores de configuración → código 1 sin conectarse.
- **S-05 — Contraseñas**: `ClaveSegura1` para todos menos `nuevo@` (`Provisoria1`); un hash por usuario calculado antes de abrir la conexión (D4).
- **S-06 — Roles**: `admin@` **y** `admin2@` como ADMIN **sin `vence_en`** (S-09 de C-09 exige al menos el primero; el segundo también, para que revocar un ADMIN desde el otro dé 200 con el seed solo — caso PDF C-08). `otorgada_por` nulo y sin eventos por asignación (los asigna la carga, no un ADMIN). Alternativa: `admin2@` con vencimiento, para que el 409 de RN05 se vea sin preparación — descartada porque ese caso ya lo cubre `test/personal.http`.
- **S-07 — Autor de las filas con `usuario_id` obligatorio**: stock inicial e historial de precio → `admin@` (id 1); creación de órdenes → `recepcion@` (id 3); inicio de la orden 2 → `mecanico@` (id 4), coherente con quién puede hacer cada operación (RN11, matriz de roles). El evento de la carga usa el actor textual `SISTEMA`.
- **S-08 — Datos que la KB no fija**: precio de la bujía 4500.00; códigos de repuesto; nombres, documentos (`28111222`, `25111333`, distintos de los de los `.http`), teléfonos y patentes; ítems de la orden 1 (1 filtro + 4 litros de aceite: RN10 exige al menos un ítem y la KB no los da) y fallas de las órdenes (D6).
- **S-09 — Encabezados de `test/auth.http` y `test/personal.http`** ajustados para correr después del seed (D9), sin cambiar casos.
- **S-10 — Verificación**: `test/seed.sql` y `test/seed.http` versionados + script temporal `verificar_c06.py` (D8).
