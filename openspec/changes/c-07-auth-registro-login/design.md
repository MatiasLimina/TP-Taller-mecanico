# Design — C-07 auth-registro-login

## Context

Estado actual (ver proposal.md — Why):

- `app/modules/usuarios/models.py` ya declara `Usuario`, `AsignacionRol` (enum `Rol`, índice único parcial `uq_asignacion_rol_usuario_id_rol`), `IntentoAcceso` (índice `ix_intento_acceso_email_ip_cuando`) y `EventoSeguridad`; `app/modules/clientes/models.py` declara `Cliente` con `uq_cliente_documento` y `uq_cliente_usuario_id`. `usuario.email` tiene `uq_usuario_email`. Las columnas de texto son `VARCHAR` sin largo y las fechas `timestamptz` con `default_factory=ahora_utc` (hora de Python, UTC).
- `app/core/security.py` (C-05) expone `hash_password`, `verify_password`, `crear_token_acceso`, `aplicar_cookie_acceso`, `eliminar_cookie_acceso` y el hash ficticio en `app.state.hash_ficticio`. Su docstring (líneas 8-9) dice que, en el login, un `PasswordInvalidaError` se traduce al mismo 401 y nunca a 500; C-07 lo corrige para reflejar que el DTO responde 422 antes (S-07).
- `app/core/unit_of_work.py`, `repository.py`, `errores.py` y `schemas.py` (C-02) fijan el patrón: repos con `flush()`, UoW construido por dependencia y abierto por el servicio, `restriccion_violada(exc)` fuera del bloque, `EntradaBase` con `extra="forbid"`, `SalidaBase` que rechaza `password_hash`. `ErrorDeAplicacion` sólo cubre 404/409/422 y no lleva encabezados.
- `main.py` tiene el grupo `rutas_abiertas` con sólo el router de salud; `database.py` ofrece `get_session` y `app.state.session_factory`.
- Verificación del TP: archivos `.http` en `test/` (hoy sólo `health.http`) y `test/solo_agregado.sql`; C-05 agregó además `test/verificar_security_core.py`. No hay pytest ni otro runner (decisión del TP, `10_preguntas_abiertas.md`).
- La consigna exige: unicidad garantizada por la base, **sin consulta previa**; el límite de intentos "cuesta una consulta"; el intento se anota en sesión propia "que se confirma siempre", declarado en comentario con su costo.

## Goals / Non-Goals

**Goals:**

- Que el login no retenga una conexión durante bcrypt y que el registro no la tome hasta tener el hash (DD-06).
- Que los caminos de "correo inexistente", "contraseña incorrecta" y "usuario inactivo" ejecuten el mismo trabajo (mismas consultas, una verificación bcrypt, una escritura de intento).
- Que el 429 cueste una sola consulta y ningún hash.
- Dejar en el módulo `usuarios` las piezas que C-08/C-09 reutilizan (consulta de roles vigentes, router `/auth`, error 401, convención de `evento_seguridad`) sin implementar nada de C-08.

**Non-Goals:**

- Guards (`get_usuario_actual`, `requiere_rol`), grupo protegido, `/auth/yo`, `/auth/cambiar-password`, alta de personal y roles (C-08/C-09).
- Repositorio y endpoints de clientes (C-10).
- Defensa contra fuerza bruta distribuida (muchas IPs) o por cuenta global: la consigna fija el par correo + IP.
- Confirmación por correo, recuperación de contraseña, política de complejidad más allá del largo.

## Decisions

### D1 — Estructura del módulo `usuarios`

| Archivo | Contenido |
|---------|-----------|
| `schemas.py` | `RegistroEntrada`, `LoginEntrada` (heredan `EntradaBase`); `RegistroSalida`, `ClienteRegistradoSalida`, `LoginSalida`, `MensajeSalida` (heredan `SalidaBase`) |
| `repository.py` | `UsuarioRepository`, `AsignacionRolRepository`, `IntentoAccesoRepository` |
| `unit_of_work.py` | `UsuariosUoW` + `get_usuarios_uow` / `UsuariosUoWDep`; `AnotadorIntentos` + `get_anotador_intentos` / `AnotadorIntentosDep` |
| `service.py` | `registrar(uow, datos)`, `iniciar_sesion(uow, anotador, datos, ip, hash_ficticio)`; constantes del límite y mensajes |
| `router.py` | `router = APIRouter(prefix="/auth", tags=["auth"])` con registro, login y logout |

La ficha de cliente y el evento se escriben con `BaseRepository(session, Cliente)` y `BaseRepository(session, EventoSeguridad)` dentro de `UsuariosUoW`: alcanza con `add()` y evita crear `app/modules/clientes/repository.py`, que pertenece a C-10 (Lautaro) y chocaría en el merge.

- *Alternativa descartada*: crear `ClienteRepository` acá — adelanta trabajo de C-10 y genera conflicto de archivos entre ramas paralelas.

### D2 — Contratos de entrada

```python
CorreoNormalizado = Annotated[EmailStr, BeforeValidator(strip), AfterValidator(str.lower)]  # ≤ 254
MIN_CARACTERES_PASSWORD = 8           # constante fija del registro (S-02)
class RegistroEntrada(EntradaBase):
    email: CorreoNormalizado          # strip + minúsculas, ≤ 254
    password: PasswordRegistro        # ≥ MIN_CARACTERES_PASSWORD caracteres, ≤ 72 bytes UTF-8
    nombre: TextoNoVacio100           # strip, 1–100 tras el strip
    documento: TextoNoVacio20         # strip, 1–20 tras el strip
    telefono: TextoNoVacio30          # strip, 1–30 tras el strip
class LoginEntrada(EntradaBase):
    email: CorreoNormalizado
    password: PasswordLogin           # 1 carácter mín., ≤ 72 bytes UTF-8 (sin mínimo de 8)
```

- El límite de 72 se valida en **bytes** con un `AfterValidator` (`len(v.encode("utf-8")) > 72` → error de valor). Un surrogate suelto que no se puede codificar también es 422. El manejador global de validación ya omite `input`, así que la contraseña no se refleja. En el login, más de 72 bytes también es **422 del DTO** (S-07): el límite es público (está en el contrato del registro), así que el 422 no revela nada de lo que protege RN09 (qué correos existen).
- `EmailStr` (de `email-validator`, incluido en `fastapi[standard]`) valida el formato; antes se recortan los espacios y después todo el correo se pasa a minúsculas (el validador sólo normaliza el dominio). Así la unicidad de `uq_usuario_email` y el conteo de intentos son insensibles a mayúsculas sin índice funcional ni migración. La normalización vive en los **dos** DTO (registro y login).
- El mínimo de 8 caracteres es una constante fija del DTO del registro y **nunca** se aplica en el login (S-02): una contraseña corta en el login simplemente no coincide (401), los usuarios del seed con contraseñas cortas pueden entrar igual, y no se filtra la política a quien prueba credenciales.
- `nombre`, `documento` y `telefono`: `strip` de espacios al inicio y al final, y `min_length=1` **después** del recorte (un campo sólo de espacios es 422). El recorte importa para la unicidad: `uq_cliente_documento` compara el texto exacto, así que sin él `" 30123456"` y `"30123456"` serían documentos distintos y se saltearía RN02. Sin validación de formato propio de documento ni teléfono (S-03).
- Los largos máximos (`nombre` 100, `documento` 20, `telefono` 30, `email` 254) no los fija la consigna: protegen de cuerpos enormes y viven **sólo en el DTO** (S-03). La base no cambia: las columnas son `AutoString`/`VARCHAR` sin largo, así que un texto largo nunca produce `DataError` ni 500.
- *Alternativa descartada*: `str` sin formato para el correo del login (para que todo error sea 401) — la matriz admite 422 en el login y un correo malformado no puede existir en la base, así que el 422 no revela nada.

**Correos en minúsculas: API + seed, sin migración (S-01).** La garantía queda repartida en dos puntos de escritura: la API normaliza en sus DTO y el seed (C-06) verifica o normaliza al cargar.

- *Alternativa descartada*: `CHECK (email = lower(email))` en una tercera migración — la consigna (Ejercicio 2) exige exactamente dos migraciones («Se entregan dos migraciones»: la autogenerada y la escrita a mano del trigger); regenerar la primera reabriría C-03, ya archivado.
- *Alternativa descartada*: índice único funcional sobre `lower(email)` — invasivo: reemplaza `uq_usuario_email`, del que dependen `app/core/unit_of_work.py` (línea 42) y la traducción del 409 por correo repetido; además también exigiría una migración.
- *Alternativa descartada*: no normalizar — `Ana@x.com` y `ana@x.com` serían cuentas distintas y el límite de intentos se evadiría cambiando mayúsculas.

### D3 — Contratos de salida

- `RegistroSalida`: `id`, `email`, `nombre`, `cliente: ClienteRegistradoSalida` (`id`, `nombre`, `documento`, `telefono`). 201. Sin roles: se sabe que es CLIENTE y el detalle de roles es de `/auth/yo` (C-08).
- `LoginSalida`: `mensaje` (`"Sesión iniciada"`), `debe_cambiar_password`, `expira_en_segundos` (de `ACCESS_TOKEN_EXPIRE_SECONDS`). Coincide con el ejemplo de la consigna.
- `MensajeSalida`: `mensaje` (`"Sesión cerrada"`) para el logout.
- Todas heredan `SalidaBase`, cuyo chequeo de `password_hash` corre al importar.

### D4 — Repositorios

```python
class UsuarioRepository(BaseRepository[Usuario]):
    async def get_by_email(self, email: str) -> Usuario | None

class AsignacionRolRepository(BaseRepository[AsignacionRol]):
    async def roles_vigentes(self, usuario_id: int, ahora: datetime) -> list[str]
        # SELECT rol WHERE usuario_id = :id AND revocada_en IS NULL
        #   AND (vence_en IS NULL OR vence_en > :ahora) ORDER BY rol

class IntentoAccesoRepository(BaseRepository[IntentoAcceso]):
    async def quinto_fallo_reciente(self, email: str, ip: str, desde: datetime) -> datetime | None
```

`quinto_fallo_reciente` es **una** consulta con subconsulta escalar:

```sql
SELECT cuando FROM intento_acceso
WHERE email = :email AND ip = :ip AND exito IS false AND cuando > :desde
  AND (ultimo_exito IS NULL OR cuando > ultimo_exito)   -- ultimo_exito = SELECT max(cuando) … exito IS true
ORDER BY cuando DESC OFFSET 4 LIMIT 1
```

Devuelve la fecha del quinto fallo más reciente que cuenta, o `None` si hay menos de cinco. Con esa fecha el servicio decide el bloqueo **y** calcula `Retry-After` sin otra consulta. Ambas partes usan el índice `(email, ip, cuando)`. `roles_vigentes` selecciona sólo la columna `rol`: no carga entidades ni relaciones (sin riesgo de carga perezosa). C-08 la reutiliza para `requiere_rol` y `/auth/yo`.

- *Alternativa descartada*: `COUNT(*)` + otra consulta para el `Retry-After` — dos idas a la base por intento, y la consigna pide "una consulta".

### D5 — `UsuariosUoW` y la excepción declarada de `intento_acceso`

`UsuariosUoW(session)` expone `usuarios`, `asignaciones`, `intentos` (sólo lectura del conteo), `clientes` y `eventos`, todos con la misma sesión de la petición.

`AnotadorIntentos` es la **única** escritura fuera del UoW de la petición (DD-07, RN08). Vive en `unit_of_work.py` y la construye una dependencia con `request.app.state.session_factory`:

```python
class AnotadorIntentos:
    # EXCEPCIÓN DECLARADA (RN08, DD-07): sesión y transacción propias, confirmadas siempre,
    # porque el fallo que se cuenta es el mismo que revierte la petición. Costo: una
    # conexión extra por intento y filas que persisten aunque la petición falle.
    async def anotar(self, email: str, ip: str, exito: bool) -> None:
        async with self._session_factory() as session:
            async with UnitOfWork(session):
                await IntentoAccesoRepository(session).add(IntentoAcceso(email=…, ip=…, exito=…))
```

- La confirmación la hace el `UnitOfWork` base (sigue siendo el único `commit()` de `app/`); esta clase sí crea y cierra su sesión, y por eso lleva el comentario.
- Se anota **antes** de lanzar el 401, de modo que el fallo queda guardado aunque la petición termine en error.
- *Alternativa descartada*: `session.commit()` explícito en el anotador — funciona, pero suma un segundo lugar con `commit()` que la inspección de C-02 tendría que exceptuar.
- *Alternativa descartada*: anotar dentro del UoW de la petición — el 401 lo revertiría y el límite nunca se alcanzaría.

### D6 — Registro: hash antes, un bloque, traducción afuera

```
password_hash = await hash_password(datos.password)      # antes de abrir (DD-06)
try:
    async with uow:
        usuario    = await uow.usuarios.add(Usuario(email, nombre, password_hash))     # flush → uq_usuario_email
        await uow.asignaciones.add(AsignacionRol(usuario_id=usuario.id, rol=Rol.CLIENTE))
        cliente    = await uow.clientes.add(Cliente(usuario_id=usuario.id, nombre, documento, telefono))  # flush → uq_cliente_documento
        await uow.eventos.add(EventoSeguridad(actor=email, accion="Auto-registro de cliente"))
        salida = RegistroSalida(...)   # armada adentro, con valores ya cargados
except IntegrityError as exc:
    match restriccion_violada(exc):
        "uq_usuario_email"     → Conflicto("El correo ya está registrado")
        "uq_cliente_documento" → Conflicto("El documento ya pertenece a un cliente del taller")
        _                      → raise   # el manejador global responde 409/422 genérico
```

- Sin consulta previa de existencia: la base decide (consigna, RN01). Un registro concurrente que gane la carrera hace fallar al otro en el `flush` o en el `commit`; ambos salen por el mismo `except` (el `commit` falla dentro de `__aexit__`, que está dentro del `try`).
- El rollback del UoW deshace las cuatro filas: no hay filas sueltas. La ficha del cliente existente (p. ej. Jorge, sin usuario) nunca se lee ni se actualiza, así que no se puede apropiar.
- La salida se arma dentro del bloque para no leer atributos después de un posible rollback (advertencia del docstring de `unit_of_work.py`).
- *Alternativa descartada*: buscar la ficha por documento y vincularla si no tiene usuario — es exactamente lo que RN02 prohíbe.

### D7 — Login: orden y fronteras de transacción

```
ahora = datetime.now(UTC)
async with uow:                                              # bloque 1: 2 consultas
    quinto = await uow.intentos.quinto_fallo_reciente(email, ip, ahora - VENTANA)
    if quinto: raise DemasiadosIntentos(MENSAJE_429, retry_after=…)   # sin hash
    usuario = await uow.usuarios.get_by_email(email)
    (id, hash, activo, debe_cambiar) = valores locales o None
# conexión liberada: bcrypt no la retiene
try:
    ok = await verify_password(password, hash if usuario else hash_ficticio)
except PasswordInvalidaError:
    ok = False                                                # respaldo: el DTO ya respondió 422 (S-07)
exito = ok and usuario is not None and activo
await anotador.anotar(email, ip, exito)                       # sesión propia, siempre
if not exito: raise NoAutenticado("Correo o contraseña incorrectos")
async with uow:                                              # bloque 2: sólo en éxito
    roles = await uow.asignaciones.roles_vigentes(id, datetime.now(UTC))
token = crear_token_acceso(id, roles)
return SesionIniciada(token, LoginSalida(...))
```

- Los tres caminos de falla (correo inexistente, contraseña mala, inactivo) hacen exactamente: 2 consultas, 1 `verify_password`, 1 inserción. El inactivo verifica contra su hash real antes de rechazar, así que tarda lo mismo.
- Leer dentro de `async with uow:` es necesario: fuera del bloque la sesión abriría una transacción implícita que retendría la conexión durante bcrypt. Al salir del bloque el `commit` (sin escrituras) devuelve la conexión al pool. Dos bloques sucesivos son válidos (spec `unit-of-work`, "Bloques sucesivos").
- `roles_vigentes` se consulta sólo en el éxito: así no agrega una diferencia de tiempo entre los caminos de falla.
- El servicio devuelve el token al router en un dataclass `SesionIniciada`; el router llama `aplicar_cookie_acceso(response, token)`. El servicio no conoce `Response`.
- `hash_ficticio` e `ip` los resuelve el router (`request.app.state.hash_ficticio`, D9) y los pasa como argumentos: el servicio no conoce `Request`.

### D8 — Límite: ventana, `Retry-After` y qué se anota

- Constantes en `service.py`: `MAX_FALLOS = 5`, `VENTANA = timedelta(seconds=60)`. Son valores de la consigna (RN08), no configuración de entorno.
- Bloqueado ⇔ existe el quinto fallo reciente. `Retry-After = max(1, ceil((quinto + VENTANA - ahora).total_seconds()))`: el momento en que ese fallo sale de la ventana y quedan cuatro.
- Reloj: Python UTC en ambos lados. `cuando` se escribe con `default_factory=ahora_utc` (Python), y `desde`/`ahora` también son de Python, así que no se mezclan relojes de base y de aplicación.
- **Un 429 no se anota.** Si se anotara como fallo, cada reintento bloqueado renovaría la ventana y el bloqueo no terminaría nunca mientras el atacante insista (y la tabla crecería sin verificar nada). Además, el caso C-05 espera exactamente "los cinco fallos" en `intento_acceso`. Un 422 tampoco se anota: no llega al servicio.
- Un correo inexistente se anota y cuenta igual que uno existente: si no contara, el 429 revelaría qué correos existen.

### D9 — IP del cliente

`ip = request.client.host if request.client else "desconocida"`. No se lee `X-Forwarded-For`: el TP corre sin proxy y ese encabezado lo controla el cliente (permitiría evadir el límite cambiando el valor). Si en el futuro hay un proxy, se configura `--proxy-headers`/`forwarded_allow_ips` de uvicorn y `request.client` ya trae la IP real.

### D10 — Errores 401 y 429 en `app/core/errores.py`

```python
class ErrorDeAplicacion(Exception):
    status_code = 500
    headers: dict[str, str] | None = None
class NoAutenticado(ErrorDeAplicacion):  status_code = 401
class DemasiadosIntentos(ErrorDeAplicacion):
    status_code = 429
    def __init__(self, mensaje: str, retry_after: int) -> None:  # headers = {"Retry-After": str(retry_after)}
```

`_manejar_aplicacion` pasa `exc.headers` al `JSONResponse`. Los errores existentes no cambian (sin encabezados). `NoAutenticado` lo reutiliza C-08 para `get_usuario_actual`.

- *Alternativa descartada*: `HTTPException(429, headers=…)` en el router — el servicio tendría que devolver un código de estado o el router conocer la regla; rompe "los servicios no conocen HTTP".
- *Alternativa descartada*: agregar `WWW-Authenticate` al 401 — es para esquemas `Authorization`; la sesión viaja en cookie y la consigna prohíbe Bearer.

### D11 — Router y `main.py`

- `POST /auth/registro` (`status_code=201`, `response_model=RegistroSalida`), `POST /auth/login` (`LoginSalida`, recibe `Request` y `Response`), `POST /auth/logout` (`MensajeSalida`, recibe `Response`, no usa base ni UoW).
- `main.py`: `rutas_abiertas.include_router(auth_router)`. RN06 deja `/auth/*` en el grupo abierto; C-08 agregará `/auth/yo` y `/auth/cambiar-password` a este mismo router con su propia dependencia de autenticación por ruta.
- Todos los handlers son `async def`.

### D12 — Convención de `evento_seguridad`

`actor` = correo (normalizado) de quien actúa, o `"SISTEMA"` para procesos internos (seed); `accion` = frase corta en español en infinitivo/sustantivo con el dato relevante (`"Auto-registro de cliente"`). C-09 (altas de personal, roles, contraseña) hereda la convención. El login y el logout no generan evento: la consigna lista altas, roles, contraseña y datos iniciales; los intentos ya quedan en `intento_acceso`.

### D13 — Verificación sin pytest (Strict TDD adaptado)

La configuración global del usuario activa Strict TDD, pero el proyecto decidió **sin pytest** (`10_preguntas_abiertas.md`, CLAUDE.md): la evidencia que se entrega son `.http` con la respuesta esperada en comentario. Equivalencia adoptada:

- **RED**: antes de escribir código se escribe `test/auth.http` con todos los casos (C-02 a C-05, contratos y logout) y se corre contra el servidor actual: `/auth/*` responde 404. Se anota esa línea de base.
- **GREEN**: cada grupo de tareas implementa lo mínimo para que su sección del `.http` dé lo esperado.
- **TRIANGULATE**: cada regla tiene al menos dos casos (éxito y falla, o dos fallas distintas).
- **Safety net**: `test/health.http` y `test/verificar_security_core.py` se corren antes de tocar `errores.py`/`main.py` y al final.
- Lo que un `.http` no puede mostrar (filas en la base, concurrencia, otra IP, tiempos comparados) se comprueba con consultas `psql` documentadas en comentarios del `.http` y con scripts temporales en `$env:TEMP` (no versionados) que usan `httpx.AsyncClient` con `ASGITransport(app, client=(ip, puerto))` para simular otra IP.
- El `.http` corre sobre un estado conocido: `python seed.py` (C-06) o, mientras C-06 no exista, `alembic downgrade base; alembic upgrade head` y la ficha de "cliente sin usuario" insertada con una línea `psql` documentada.

## Risks / Trade-offs

- [Carrera en el límite: varios logins simultáneos leen "4 fallos" y verifican todos] → aceptado; el semáforo de bcrypt acota el daño y la consigna no pide serializar (mismo criterio que DD-11). No se agrega bloqueo de filas.
- [Tiempo "parecido", no idéntico] → bcrypt (~300 ms) domina sobre las dos consultas y la inserción; los tres caminos de falla hacen el mismo trabajo. El éxito sí tarda distinto (consulta de roles), pero el éxito ya es distinguible.
- [El 429 no se anota] → un atacante no puede extender el bloqueo, pero tampoco queda rastro de los reintentos bloqueados; aceptable porque los fallos que dispararon el bloqueo sí están.
- [Bloqueo por correo + IP permite a un tercero bloquear a una víctima desde la misma IP (NAT compartido) por 60 s] → inherente a RN08; ventana corta.
- [Correo en minúsculas] → dos personas no pueden tener correos que sólo difieren en mayúsculas (prácticamente nunca deseable). La base no lo impone (regla de las dos migraciones): un correo con mayúsculas cargado por fuera de la API no podría iniciar sesión. Se mitiga en el único otro punto de escritura, el seed: C-06 verifica (falla al cargar) o normaliza los correos (S-01, anotado en el scope de C-06 en `CHANGES.md`).
- [Conexión extra por intento (anotador)] → costo declarado; el pool (5 + 10) lo absorbe en el TP. Si el pool se agota, el login espera en vez de fallar.
- [Hash del registro antes de saber si el correo existe] → un registro duplicado gasta ~300 ms de bcrypt; es el precio de no hacer consulta previa y de no retener la conexión.
- [`evento_seguridad.actor` guarda el correo] → dato personal en auditoría; aceptable y útil para `/eventos` (ADMIN).

## Migration Plan

Sin cambios de esquema ni de datos: las tablas existen desde C-03. Despliegue: agregar el módulo, los dos errores y la línea de `main.py`; reiniciar uvicorn. Rollback: quitar la línea de `main.py` (las rutas desaparecen) y los archivos nuevos; las filas de `usuario`/`cliente`/`intento_acceso` creadas por pruebas se limpian con `python seed.py` o `alembic downgrade base; alembic upgrade head`.

## Open Questions / Supuestos

No quedan preguntas abiertas: los siete supuestos fueron **confirmados por el usuario (2026-10-27)**.

- **S-01 — Correos en minúsculas: la API normaliza + chequeo en el seed** — confirmado por el usuario (2026-10-27). Los DTO de registro y de login recortan espacios y pasan a minúsculas; **sin migración nueva**; `seed.py` (C-06) verifica (falla al cargar) o normaliza sus correos a minúsculas. Razón: la consigna exige exactamente dos migraciones y regenerar la primera reabriría C-03 (alternativas descartadas en D2). Anotado en el scope de C-06 en `CHANGES.md`.
- **S-02 — Mínimo de 8 caracteres, fijo, sólo en el registro** — confirmado por el usuario (2026-10-27). Constante del DTO del registro; nunca en el login. Razón: el login de contraseñas cortas del seed sigue funcionando y el login no filtra la política.
- **S-03 — Largos máximos y recorte en el DTO, sin cambios en la base** — confirmado por el usuario (2026-10-27). `nombre` 100, `documento` 20, `telefono` 30, `email` 254; `strip` y `min_length=1` tras el recorte en todos; sin formato propio de documento ni teléfono. Razón: `uq_cliente_documento` compara exacto (sin recorte, `" 30123456"` evadiría la unicidad) y las columnas sin largo descartan un `DataError`/500.
- **S-04 — El registro no inicia sesión** (201 sin cookie) — confirmado por el usuario (2026-10-27). Razón: toda cookie nace en `/auth/login`, invariante en el que se apoya C-08.
- **S-05 — Cuerpo del 201 = usuario + ficha anidada** (D3) — confirmado por el usuario (2026-10-27). Razón: la consigna no muestra el cuerpo y así el cliente ve su ficha sin otra petición.
- **S-06 — Parte de C-03 diferida a C-08** — confirmado por el usuario (2026-10-27). "Sin cookie o con `Authorization: Bearer` → 401" necesita una ruta protegida (`/auth/yo`); queda anotado en el scope de C-08 en `CHANGES.md` ("Completar el caso PDF C03…"). En C-07 se verifican los atributos de la cookie y el cuerpo sin token.
- **S-07 — Contraseña de más de 72 bytes en el login → 422 del DTO; 401 como respaldo; se corrige el docstring de `security.py`** — confirmado por el usuario (2026-10-27). El servicio traduce `PasswordInvalidaError` al 401 genérico si alguna vez llega (D7), nunca a 500; el docstring (líneas 8-9, hoy "se traduce al mismo 401") pasa a decirlo así (tarea 6.4, sólo comentario en un archivo de C-05). Razón: el límite de 72 bytes es público (contrato del registro), así que el 422 no revela qué correos existen (RN09).
