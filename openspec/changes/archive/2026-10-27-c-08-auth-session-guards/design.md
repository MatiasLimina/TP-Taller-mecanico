# Design — C-08 auth-session-guards

## Context

Estado actual (ver proposal.md — Why):

- `app/core/security.py` (C-05) ya tiene todo lo criptográfico: `decodificar_token_acceso(token) -> TokenAcceso(usuario_id, iat, exp, roles)` con `iat` como `datetime` UTC **con fracción**, `TokenInvalidoError` genérico (firma, vencimiento, claims, `sub` no canónico), `crear_token_acceso(usuario_id, roles, *, ahora=None)` que acepta la marca de emisión, `NOMBRE_COOKIE_ACCESO`, `aplicar_cookie_acceso`, `hash_password`/`verify_password` (to_thread + semáforo) y `PasswordInvalidaError`. Este change no lo modifica.
- `app/modules/usuarios/` (C-07): `Usuario` con `activo`, `debe_cambiar_password` y `password_cambiada_en` (`UTCDateTime`: `timestamptz`, devuelve fechas con zona); `UsuarioRepository` (hereda `get_by_id` y `update` de `BaseRepository`), `AsignacionRolRepository.roles_vigentes(usuario_id, ahora)`; `UsuariosUoW` con `usuarios`, `asignaciones`, `eventos`; `UsuariosUoWDep`; `service.SesionIniciada(token, salida)`; `LoginSalida`; tipos `PasswordRegistro`/`PasswordLogin` y `MIN_CARACTERES_PASSWORD` en `schemas.py`; `router = APIRouter(prefix="/auth")` dentro de `rutas_abiertas`.
- `app/core/errores.py`: `ErrorDeAplicacion` con `NoAutenticado` (401), `NoEncontrado`, `Conflicto`, `EntradaInvalida`, `DemasiadosIntentos`; no hay 403.
- `main.py`: sólo `rutas_abiertas` (salud + `/auth`), con el comentario "C-08 agrega `rutas_protegidas` al lado". No existe `app/core/dependencies.py`.
- FastAPI instalado: 0.162. Comprobado en su código (`fastapi/routing.py`, `fastapi/dependencies/utils.py`): el cuerpo JSON se decodifica **antes** de resolver dependencias (JSON mal formado → 422 inmediato); después se resuelven las sub-dependencias (una excepción corta ahí) y recién luego se validan ruta, query y cuerpo (los 422 se acumulan al final). Las dependencias de un `APIRouter(dependencies=…)` se anteponen a las de la ruta, y una dependencia repetida en la misma petición se ejecuta una vez (caché por petición).
- Verificación del TP: `.http` en `test/` con la respuesta esperada en comentario, sin pytest (C-07 D13). C-06 (seed) puede no estar listo: los casos se preparan con `/auth/registro` y `psql`.

## Goals / Non-Goals

**Goals:**

- Una sola fuente de "quién es" por petición (`get_usuario_actual`), ejecutada una vez aunque la pidan el grupo, `requiere_rol` y el handler.
- 401 y 403 siempre distintos y en un orden fijo (spec `access-control`, "Orden de los rechazos").
- RN07 exacto: el token del cambio vale y cualquier sesión anterior no, aunque sea del mismo segundo, sin migraciones nuevas.
- Ninguna conexión retenida durante bcrypt en el cambio de contraseña (dos operaciones bcrypt, ambas fuera de toda transacción).
- Dejar a C-09…C-15 una API mínima: `UsuarioActualDep`, `requiere_rol(*roles)` y `rutas_protegidas`.

**Non-Goals:**

- Rutas de dominio protegidas (ninguna se adelanta: ver S-06), alta de personal, roles, autoprotección, `/eventos` (C-09).
- Revocación de sesiones individuales, lista negra de tokens o renovación de token (no los pide la consigna; RN07 alcanza con `password_cambiada_en`).
- Límite de intentos sobre la contraseña actual del cambio (S-02).
- Concurrencia entre dos cambios de contraseña simultáneos del mismo usuario (DD-11, cap. 7).

## Decisions

### D1 — Dónde vive cada pieza

| Archivo | Contenido nuevo |
|---------|-----------------|
| `app/core/errores.py` | `SinPermiso(ErrorDeAplicacion)` con `status_code = 403`; docstring con el 403 |
| `app/modules/usuarios/schemas.py` | `CambioPasswordEntrada` (entrada), `PerfilSalida` (salida) |
| `app/modules/usuarios/service.py` | `UsuarioActual` (dataclass), `autenticar`, `exigir_roles`, `perfil`, `cambiar_password`; mensajes y acción del evento |
| `app/core/dependencies.py` | `get_usuario_actual`, `UsuarioActualDep`, `exigir_password_al_dia`, `requiere_rol` |
| `app/modules/usuarios/router.py` | `GET /auth/yo`, `POST /auth/cambiar-password` |
| `main.py` | `rutas_protegidas` con el control montado una vez |
| `test/sesion.http` | casos del change |

`dependencies.py` es un adaptador HTTP fino: lee la cookie, recibe el UoW por inyección y llama al servicio; las reglas (401/403) viven en `usuarios/service.py`, que no conoce `Request` ni `Response`. Así se cumple "el router (la inyección) construye el UoW y el servicio lo abre" también para las dependencias (S-09).

Imports sin ciclo: `core/dependencies.py` → `usuarios.service`, `usuarios.unit_of_work`, `usuarios.models.Rol`; `usuarios/router.py` → `core/dependencies.py`. `usuarios/service.py` **nunca** importa `core/dependencies.py`.

- *Alternativa descartada*: la lógica dentro de `dependencies.py` abriendo el UoW ahí — mezcla HTTP y reglas, y deja reglas de negocio fuera de la capa de servicio.
- *Alternativa descartada*: `fastapi.security.APIKeyCookie` — documenta la cookie en OpenAPI, pero la consigna pide leerla de `request.cookies` y agrega otra capa con su propio 403 por defecto (`auto_error`).

### D2 — `UsuarioActual` y `get_usuario_actual`

```python
@dataclass(frozen=True, slots=True)
class UsuarioActual:              # usuarios/service.py — valores, nunca la entidad
    id: int
    email: str
    nombre: str
    debe_cambiar_password: bool
    roles_token: tuple[str, ...]  # informativos (RN04)

# core/dependencies.py
async def get_usuario_actual(request: Request, uow: UsuariosUoWDep) -> UsuarioActual:
    return await service.autenticar(uow, request.cookies.get(NOMBRE_COOKIE_ACCESO))

UsuarioActualDep = Annotated[UsuarioActual, Depends(get_usuario_actual)]
```

`service.autenticar(uow, token: str | None) -> UsuarioActual`:

```
if not token:                         → NoAutenticado(MENSAJE_SIN_SESION)          # falta o vacía
try: datos = decodificar_token_acceso(token)
except TokenInvalidoError:            → NoAutenticado(MENSAJE_SESION_INVALIDA)     # 0 consultas
async with uow:                                                                    # 1 consulta
    usuario = await uow.usuarios.get_by_id(datos.usuario_id)
    if usuario is None or not usuario.activo:            → NoAutenticado(MENSAJE_SESION_INVALIDA)
    if usuario.password_cambiada_en is not None and datos.iat < usuario.password_cambiada_en:
                                                         → NoAutenticado(MENSAJE_SESION_INVALIDA)
    actual = UsuarioActual(...)        # armado adentro, con valores ya cargados
return actual
```

- Nunca se lee `Authorization`: el token sólo sale de `request.cookies` (DD-04). Con cookie y `Bearer` a la vez, gana la cookie porque el encabezado ni se mira.
- `UsuarioActual` no lleva `password_hash` ni la entidad: se puede pasar a cualquier servicio sin riesgo de exponer el hash ni de disparar cargas perezosas.
- El UoW es el mismo objeto que recibirá el handler si también pide `UsuariosUoWDep` (caché por petición): son bloques **sucesivos**, nunca anidados (spec `unit-of-work`). Si el handler usa el UoW de otro módulo, comparte la misma sesión de la petición.
- *Alternativa descartada*: devolver la entidad `Usuario` — expone el hash a quien la reciba y sus relaciones (`lazy="raise"`) se romperían fuera del repositorio.

### D3 — RN07 sin truncar: el mismo instante para la columna y el token

- `iat` viaja como número JSON con fracción y `decodificar_token_acceso` lo devuelve como `datetime` UTC; `password_cambiada_en` es `timestamptz` (microsegundos). La comparación es `datos.iat < usuario.password_cambiada_en`, entre dos `datetime` con zona, sin `int()`, `replace(microsecond=0)` ni `timestamp()` truncado.
- El ida y vuelta `datetime → float → JSON → float → datetime` es exacto al microsegundo para fechas actuales (precisión del `float` ≈ 0,24 µs a 1,8·10⁹ s y `fromtimestamp` redondea al microsegundo más cercano). Comprobado durante el propose con 2 000 000 fechas aleatorias de 2026–2046: 0 diferencias. La tarea 6.2 lo vuelve a comprobar.
- En el cambio, **un solo** `ahora = datetime.now(UTC)` se guarda en `password_cambiada_en` y se pasa a `crear_token_acceso(..., ahora=ahora)` después del commit. El token nuevo tiene `iat == password_cambiada_en` → no es "anterior" → vale. Toda sesión emitida antes tiene `iat` menor (aunque sea del mismo segundo) → 401.
- *Alternativa descartada*: emitir el token con otro `datetime.now()` tomado después del commit — `datetime.now` no es monótono (un ajuste NTP hacia atrás dejaría el token nuevo "anterior" al cambio y el usuario quedaría afuera).
- *Alternativa descartada*: comparar con `<=` y emitir con un instante posterior — mismo problema de reloj, y una sesión emitida exactamente en el instante del cambio sería rechazada sin razón.
- *Alternativa descartada*: un contador de versión de sesión en `usuario` — requiere una tercera migración (la consigna exige dos).

### D4 — Grupos de rutas y control de cambio pendiente (RN06)

```python
# core/dependencies.py
async def exigir_password_al_dia(actual: UsuarioActualDep) -> None:
    if actual.debe_cambiar_password:
        raise SinPermiso(MENSAJE_CAMBIO_PENDIENTE)

# main.py
rutas_protegidas = APIRouter(dependencies=[Depends(exigir_password_al_dia)])
# C-09+: rutas_protegidas.include_router(<router>) ANTES de app.include_router(rutas_protegidas):
# include_router copia las rutas en ese momento; lo que se agregue después no queda montado.
app.include_router(rutas_abiertas)
app.include_router(rutas_protegidas)
```

- El control depende de `get_usuario_actual`, así que toda ruta protegida da 401 sin sesión aunque no declare roles.
- Montado **una vez** a nivel de grupo: FastAPI suma dependencias y no las resta, por eso no se puede poner en la app y "sacarlo" de `/auth` (consigna, sección 5.10). `exigir_password_al_dia` no aparece en ningún router.
- `/auth/yo` y `/auth/cambiar-password` siguen en el router de `/auth` (grupo abierto) y piden `UsuarioActualDep` por ruta: con cambio pendiente responden normalmente.
- El grupo nace vacío (S-06).
- *Alternativa descartada*: middleware — no tiene inyección de dependencias, debería abrir sesión y transacción por fuera del UoW, y sus excepciones no pasan por los manejadores de `errores.py`.
- *Alternativa descartada*: el control en cada ruta — es exactamente lo que la consigna pide evitar (se olvida en una ruta nueva).

### D5 — `requiere_rol(*roles)` (RN04)

```python
def requiere_rol(*roles: Rol) -> Callable[..., Awaitable[UsuarioActual]]:
    if not roles:
        raise ValueError("requiere_rol necesita al menos un rol")   # error de programación, al importar
    permitidos = frozenset(rol.value for rol in roles)

    async def dependencia(actual: UsuarioActualDep, uow: UsuariosUoWDep) -> UsuarioActual:
        await service.exigir_roles(uow, actual.id, permitidos)
        return actual
    return dependencia

# service
async def exigir_roles(uow, usuario_id: int, permitidos: frozenset[str]) -> None:
    async with uow:                                                   # 1 consulta, sólo la columna rol
        vigentes = await uow.asignaciones.roles_vigentes(usuario_id, datetime.now(UTC))
    if permitidos.isdisjoint(vigentes):
        raise SinPermiso(MENSAJE_SIN_PERMISO)
```

- Uso en C-09+: `actual: Annotated[UsuarioActual, Depends(requiere_rol(Rol.ADMIN))]` o `dependencies=[Depends(requiere_rol(Rol.RECEPCION, Rol.ADMIN))]`.
- Consulta la base en **cada** petición; `actual.roles_token` nunca participa (RN04, DD-03). Reutiliza `roles_vigentes` de C-07 (abiertas y sin vencer).
- Sin comodín: `ADMIN` pasa sólo donde se lo nombra (S-07).
- Orden: las dependencias del grupo se anteponen a las de la ruta, así que `exigir_password_al_dia` (403 cambio pendiente) corre antes que `requiere_rol` (403 sin permiso); ambas después de `get_usuario_actual` (401).

### D6 — `GET /auth/yo`

`service.perfil(uow, actual) -> PerfilSalida`: un bloque con `roles_vigentes(actual.id, ahora)`; arma `PerfilSalida(id, email, nombre, debe_cambiar_password, roles_vigentes, roles_token=list(actual.roles_token))`. Total por petición: 2 consultas (usuario en `autenticar`, roles acá). `PerfilSalida` hereda `SalidaBase` (S-04).

### D7 — `POST /auth/cambiar-password`

```python
class CambioPasswordEntrada(EntradaBase):
    password_actual: PasswordLogin      # 1 carácter .. 72 bytes, sin mínimo de 8 (como el login)
    password_nueva: PasswordRegistro    # MIN_CARACTERES_PASSWORD .. 72 bytes (como el registro)
    # model_validator(mode="after"): password_nueva == password_actual → ValueError (422)
```

`service.cambiar_password(uow, actual, datos) -> SesionIniciada`:

```
async with uow:                                                  # bloque 1: sólo leer el hash
    usuario = await uow.usuarios.get_by_id(actual.id)
    hash_guardado = usuario.password_hash if usuario is not None else None
if hash_guardado is None: → NoAutenticado(MENSAJE_SESION_INVALIDA)
try:    coincide = await verify_password(datos.password_actual, hash_guardado)   # fuera de transacción
except PasswordInvalidaError: coincide = False                                   # respaldo: el DTO ya da 422
if not coincide: → NoAutenticado(MENSAJE_PASSWORD_ACTUAL_INCORRECTA)
nuevo_hash = await hash_password(datos.password_nueva)                           # ANTES del bloque 2 (DD-06)
async with uow:                                                  # bloque 2: todo o nada
    usuario = await uow.usuarios.get_by_id(actual.id)
    ahora = datetime.now(UTC)
    await uow.usuarios.update(usuario, {"password_hash": nuevo_hash,
                                        "password_cambiada_en": ahora,
                                        "debe_cambiar_password": False})
    await uow.eventos.add(EventoSeguridad(actor=usuario.email, accion=ACCION_CAMBIO_PASSWORD))
    roles = await uow.asignaciones.roles_vigentes(actual.id, ahora)
token = crear_token_acceso(actual.id, roles, ahora=ahora)        # después del commit (D3)
return SesionIniciada(token, LoginSalida(mensaje=MENSAJE_PASSWORD_ACTUALIZADA,
                                         debe_cambiar_password=False,
                                         expira_en_segundos=settings.access_token_expire_seconds))
```

- El router: `actual: UsuarioActualDep`, `datos: CambioPasswordEntrada`, `uow: UsuariosUoWDep`, `response: Response`; llama al servicio y `aplicar_cookie_acceso(response, sesion.token)`. Si el servicio lanza, no se toca la cookie.
- Dos bcrypt (~600 ms) y ninguna conexión tomada durante ellos: el bloque 1 se cierra antes de `verify_password` y el bloque 2 se abre después de `hash_password`.
- `update` es el genérico de `BaseRepository` (valida las claves y hace `flush()`): no hace falta un método nuevo.
- La línea de `evento_seguridad` sigue la convención de C-07 D12: `actor` = correo normalizado, `accion = "Cambio de contraseña"` (S-05). Va en el mismo bloque: si el commit falla, no queda ni el hash nuevo ni el evento.
- Identidad de la sesión: `get_by_id` en los bloques 1 y 2 devuelve la misma instancia que leyó `autenticar` (misma sesión, `expire_on_commit=False`); sus valores son de milisegundos antes, en la misma petición. Aceptable: ver Riesgos.
- *Alternativa descartada*: un solo bloque con las dos operaciones bcrypt adentro — retiene la conexión ~600 ms sin usarla (prohibido, DD-06).
- *Alternativa descartada*: llevar `password_hash` en `UsuarioActual` para ahorrar el bloque 1 — el hash viajaría por todos los servicios que reciben el usuario actual.

### D8 — Mensajes y respuestas de rechazo

| Situación | Código | `detail` |
|-----------|--------|----------|
| Sin cookie o cookie vacía | 401 | `Se requiere iniciar sesión` |
| Token inválido/alterado/vencido/otra clave; usuario inexistente o inactivo; sesión anterior al cambio | 401 | `La sesión no es válida o venció` |
| Contraseña actual incorrecta (cambio) | 401 | `La contraseña actual es incorrecta` |
| Cambio de contraseña pendiente en ruta protegida | 403 | `Debe cambiar la contraseña antes de continuar` |
| Sin rol vigente exigido | 403 | `No tiene permiso para realizar esta operación` |

- Un 401 no borra la cookie ni agrega `WWW-Authenticate` (C-07 D10: la sesión viaja en cookie; el cliente vuelve a `/auth/login`). S-03.
- Las constantes viven en `usuarios/service.py`, junto a las de C-07.

### D9 — Error 403 en `app/core/errores.py`

`class SinPermiso(ErrorDeAplicacion): status_code = 403`. El manejador `_manejar_aplicacion` ya cubre cualquier subclase (sin encabezados extra). Se actualiza el docstring del módulo para listar el 403.

- *Alternativa descartada*: `HTTPException(403)` en la dependencia — rompe "los servicios no conocen HTTP" y el cuerpo de FastAPI no pasa por la convención de mensajes propios.

### D10 — Verificación sin pytest (Strict TDD adaptado, como C-07 D13)

- **RED**: antes de escribir código se escribe `test/sesion.http` completo (tarea 1.1) y se corre contra el servidor actual: `/auth/yo` y `/auth/cambiar-password` → 404. Se anota la línea de base.
- **GREEN**: cada grupo de tareas implementa lo mínimo para que su sección del `.http` dé lo esperado.
- **TRIANGULATE**: cada regla tiene al menos dos casos (acepta/rechaza o dos motivos de rechazo distintos).
- **Safety net**: `test/health.http`, `test/auth.http` (C-07) y `test/verificar_security_core.py` se corren antes de tocar `errores.py`/`main.py`/`service.py` y al final.
- Lo que un `.http` no puede mostrar se comprueba con **un** script temporal `$env:TEMP\verificar_c08.py` (no versionado): arma una app de prueba con `main.lifespan`, `registrar_manejadores`, `main.rutas_abiertas` y un router de **sondas** con `APIRouter(dependencies=[Depends(exigir_password_al_dia)])` (la misma línea que `main.py`) y rutas `GET /sonda`, `GET /sonda-admin` (`requiere_rol(Rol.ADMIN)`), `GET /sonda-mecanico` (`requiere_rol(Rol.MECANICO)`), `GET /sonda-admin/{id}` (`id: int`) y `POST /sonda-admin` (cuerpo `EntradaBase` con un campo); cliente `httpx.AsyncClient(transport=ASGITransport(app))` dentro de `async with main.lifespan(app)`. Cubre: tokens vencidos, de otra clave, de usuario inexistente y con `iat` a ±1 µs de `password_cambiada_en`; `Bearer` con un token real; los 401/403 y su orden; conteo de consultas (listener `before_cursor_execute` sobre `app.state.engine.sync_engine`).
- `test/sesion.http` corre sobre un estado conocido: el bloque de limpieza `psql` del encabezado (correos `@sesion.example.com`) y la ficha creada por el propio archivo; si C-06 ya existe, `python seed.py` antes.

## Risks / Trade-offs

- [Dos transacciones cortas por petición protegida con rol (usuario + roles)] → costo declarado de RN04/DD-03 ("una consulta extra por petición"); las consultas son por PK y por el índice `ix_asignacion_rol_usuario_id`.
- [Sin límite de intentos sobre `password_actual`] → quien ya tiene una cookie válida puede probar contraseñas actuales; el semáforo de bcrypt acota el ritmo y la cookie vence en 30 min. La consigna sólo pide el límite en el login (RN08) y `intento_acceso` es la tabla del login. S-02.
- [Instancia de `Usuario` reutilizada dentro de la petición (identity map)] → los valores leídos por `autenticar` se reutilizan en el cambio sin releer columnas; dos cambios simultáneos del mismo usuario pueden pisarse (gana el último commit, y ambas cookies emitidas valen hasta que la otra marca sea posterior). Concurrencia diferida (DD-11); no hay ruta que cambie la contraseña de otro usuario en C-08.
- [Carrera RN07: login o cambio con la contraseña vieja en vuelo durante un cambio] → aceptado (confirmado por el usuario, 2026-10-27, tras la revisión FINAL_DIFF). El login (C-07) y el cambio leen el hash, sueltan la transacción y corren bcrypt (~300 ms) antes de escribir o emitir el token: un login con la contraseña vieja que leyó el hash antes del commit del cambio obtiene un `iat` posterior a `password_cambiada_en` y su sesión sobrevive; dos cambios simultáneos se pisan (gana el último commit), también si el bloque 2 no vuelve a mirar `activo`. Mismo criterio que la carrera del límite de intentos de C-07 y DD-11: la concurrencia está fuera del alcance de la consigna (cap. 7) y el PDF prueba todo secuencial. Alternativa descartada por ahora: releer en el bloque 2 con `with_for_update()` + `populate_existing=True` (una simple relectura no alcanza por el identity map con `expire_on_commit=False`) y devolver 401 si el hash o `password_cambiada_en` cambiaron; toca `repository.py` y el login de C-07, fuera del alcance de C-08.
- [Grupo protegido vacío en C-08] → el 403 por cambio pendiente y el 403 por rol sólo se ejercitan con sondas en un script temporal; la evidencia `.http` de esos 403 llega con la primera ruta protegida (C-09, `POST /usuarios`). S-06.
- [Un 401 no borra la cookie] → el navegador sigue mandando una cookie muerta hasta que vence o se hace logout; inocuo (cada petición la rechaza) y evita que una dependencia de lectura escriba en la respuesta.
- [JSON mal formado da 422 antes que 401] → comportamiento de FastAPI (decodifica el cuerpo antes de resolver dependencias); no revela nada de la sesión. Documentado en la spec para que nadie lo "arregle".
- [Usuario desactivado o con la contraseña cambiada: mismo 401 que un token roto] → el cliente no sabe por qué; deliberado (no revela estado de la cuenta a quien tiene una cookie vieja).

## Migration Plan

Sin cambios de esquema ni de datos: `activo`, `debe_cambiar_password` y `password_cambiada_en` existen desde C-03. Despliegue: archivos nuevos y modificados, reiniciar uvicorn. Las cookies emitidas por C-07 siguen valiendo (mismo formato de token). Rollback: revertir `main.py`, `router.py`, `service.py`, `schemas.py`, `errores.py` y borrar `dependencies.py`; las filas de prueba se limpian con el bloque `psql` de `test/sesion.http` o `python seed.py`.

## Open Questions / Supuestos

No quedan preguntas abiertas: los nueve supuestos fueron **confirmados por el usuario (2026-10-27)**, cada uno tras comparar alternativas (las descartadas están en las decisiones D1–D10).

- **S-01 — Contrato del cambio** — confirmado por el usuario (2026-10-27): cuerpo `{password_actual, password_nueva}`; `password_actual` de 1 carácter a 72 bytes (sin mínimo, como el login); `password_nueva` de 8 caracteres a 72 bytes (como el registro) y **distinta** de la actual (422). Razón: la consigna sólo fija los 72 bytes "también para la actual del cambio"; repetir la provisoria anularía el propósito del cambio obligatorio.
- **S-02 — Contraseña actual incorrecta → 401** — confirmado por el usuario (2026-10-27): mensaje `La contraseña actual es incorrecta`, sin cookie nueva, sin invalidar la sesión en curso, sin anotarse en `intento_acceso` y sin límite propio. Razón: la matriz de la consigna para esta ruta es 200/401/422 (no hay 403 ni 409); 422 es "contrato no cumplido" y la contraseña equivocada no lo es.
- **S-03 — Dos mensajes de 401 de sesión** — confirmado por el usuario (2026-10-27): "Se requiere iniciar sesión" (sin cookie) y "La sesión no es válida o venció" (todo lo demás, sin distinguir token roto, vencido, cuenta inexistente, inactiva o sesión anterior al cambio). El 401 no borra la cookie ni lleva `WWW-Authenticate`. Razón: distinguir "no mandaste nada" no revela nada; distinguir el resto revelaría el estado de la cuenta.
- **S-04 — Cuerpo de `GET /auth/yo`** — confirmado por el usuario (2026-10-27): `{id, email, nombre, debe_cambiar_password, roles_vigentes, roles_token}`. Razón: la consigna pide "el usuario, sus roles vigentes y los que dice el token"; `debe_cambiar_password` le dice al cliente por qué recibe 403.
- **S-05 — Respuesta y auditoría del cambio** — confirmado por el usuario (2026-10-27): 200 `{mensaje: "Contraseña actualizada", debe_cambiar_password: false, expira_en_segundos}` (misma forma que el login) + cookie nueva con los roles vigentes; la línea `evento_seguridad` (`actor` = correo, `accion` = "Cambio de contraseña") la escribe **C-08** en el mismo UoW, aunque `CHANGES.md` ponga "cambios de contraseña" en el scope de C-09. Razón: el endpoint es de C-08 y el evento debe ser atómico con el cambio.
- **S-06 — Grupo protegido vacío y casos PDF parciales** — confirmado por el usuario (2026-10-27): C-08 no adelanta rutas de dominio. El 403 por cambio pendiente y el 403 por rol se verifican con sondas en el script temporal; la evidencia `.http` de esos 403 la agrega C-09 con `POST /usuarios`. De los casos que `CHANGES.md` asigna (C06–C09): C-03 se completa; C-09 se cubre salvo el 403 sobre una ruta protegida real; C-06 sólo en su parte 401/403 (lo propio necesita `/mis-*` y órdenes); C-07 (revocar por endpoint, vencimientos inválidos) y C-08 (autoprotección) necesitan los endpoints de C-09 y quedan allá.
- **S-07 — Sin comodín de ADMIN** — confirmado por el usuario (2026-10-27): `requiere_rol` deja pasar sólo los roles nombrados. Razón: la matriz nombra `ADMIN` explícitamente donde corresponde y `POST /ordenes/{id}/iniciar` es sólo `MECANICO`.
- **S-08 — Orden de rechazos** — confirmado por el usuario (2026-10-27): 401 (sesión) → 403 (cambio pendiente) → 403 (rol) → 422 (ruta/query/cuerpo) → operación; única excepción, JSON mal formado → 422 antes que todo (lo decide FastAPI). Razón: no revelar el contrato de rutas protegidas a quien no tiene sesión, y coincide con C-01 ("422 con la sesión iniciada").
- **S-09 — `app/core/dependencies.py` importa del módulo `usuarios`** — confirmado por el usuario (2026-10-27): la ubicación la fija la KB (`08_arquitectura_propuesta.md`), pero las reglas (401/403) viven en `usuarios/service.py` y el UoW llega por inyección (`UsuariosUoWDep`). Es la única dependencia de `core` hacia un módulo. Razón: respeta la estructura obligatoria sin poner lógica de negocio en `core` ni construir un UoW fuera de la inyección.
