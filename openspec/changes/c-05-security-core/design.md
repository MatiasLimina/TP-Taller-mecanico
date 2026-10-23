# Design — C-05 security-core

## Context

C-01 dejó `Settings` con `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_SECONDS`, `BCRYPT_COST`, `BCRYPT_MAX_CONCURRENCY` y `COOKIE_SECURE` validados, y en `main.py` un comentario que reserva el lugar del hash ficticio (ver proposal.md — Why). No existe todavía `app/core/security.py`.

Restricciones que moldean el diseño:

- Reglas duras del proyecto: handlers `async def`, bcrypt nunca en el bucle de eventos, secretos sólo desde el entorno, ninguna entrada inválida termina en 500, sin `Authorization: Bearer`.
- Decisiones ya tomadas: token 1800 s, bcrypt costo 12, semáforo 4, `COOKIE_SECURE=false` en desarrollo, `iat` sin truncar (DD-05), hash antes de la transacción (DD-06), anti-enumeración con hash ficticio (RN09).
- IN-03: el límite de 72 bytes se valida en el contrato, independientemente de la versión de bcrypt.
- Sin pytest: la verificación es con comandos ejecutables y, desde C-07, archivos `.http`.
- Versiones resueltas en el venv: bcrypt 5.0.0 y PyJWT 2.15.1. Comportamientos relevantes comprobados:
  - PyJWT exige que `sub` sea texto (`InvalidSubjectError` si es entero).
  - Si `iat`/`exp` se pasan como `datetime`, PyJWT los convierte con `timegm(utctimetuple())` y **pierde los microsegundos**.
  - Si se pasan como número con fracción, el valor se conserva en el token y al decodificarlo.
  - bcrypt 5.0.0 rechaza con `ValueError` las contraseñas de más de 72 bytes (no trunca).

## Goals / Non-Goals

**Goals:**

- Dejar un contrato estable y mínimo que C-06, C-07 y C-08 consuman sin volver a tocar `security.py`.
- Que el costo de bcrypt no frene el bucle ni sature el executor por defecto.
- Que la comparación de tiempos del login sea posible: hash ficticio calculado una vez y con el mismo costo que los reales.
- Que tokens y cookies cumplan RN07/RN09 y DD-04 sin depender de endpoints.

**Non-Goals:**

- Endpoints de registro, login, logout o cambio de contraseña (C-07), guards y dependencias de autorización (C-08), consulta de roles vigentes (C-08).
- Modelos, tablas, migraciones y seed (C-02/C-03/C-06).
- Refresh tokens, revocación por lista negra, `aud`/`iss`/`jti`: no los pide la consigna.
- Cifrado del token: JWT firmado, no cifrado; no debe llevar datos sensibles más allá del id y los roles informativos.

## Decisions

### D1 — Contrato público del módulo

`app/core/security.py` expone sólo lo que los changes siguientes necesitan:

```python
NOMBRE_COOKIE_ACCESO = "access_token"
ALGORITMO_JWT = "HS256"
MAX_BYTES_BCRYPT = 72

class PasswordInvalidaError(ValueError): ...
class TokenInvalidoError(Exception): ...

@dataclass(frozen=True, slots=True)
class TokenAcceso:
    usuario_id: int
    iat: datetime          # tz-aware, UTC, con fracción
    exp: datetime          # tz-aware, UTC
    roles: tuple[str, ...] # informativos

async def hash_password(password: str) -> str
async def verify_password(password: str, password_hash: str) -> bool
def crear_token_acceso(usuario_id: int, roles: Iterable[str], *, ahora: datetime | None = None) -> str
def decodificar_token_acceso(token: str) -> TokenAcceso
def aplicar_cookie_acceso(response: Response, token: str) -> None
def eliminar_cookie_acceso(response: Response) -> None
async def crear_hash_ficticio() -> str
```

- `ahora` existe sólo para verificación determinista (emitir un token ya vencido o con microsegundos conocidos); en producción se omite y se usa `datetime.now(timezone.utc)`. Si es naive, se rechaza con `ValueError`.
- *Alternativa descartada*: devolver el payload crudo de PyJWT. Un dataclass tipado evita que C-08 dependa de nombres y tipos de claims dispersos.

### D2 — bcrypt en `asyncio.to_thread` con semáforo perezoso

`hash_password` y `verify_password` validan la contraseña en el bucle (barato) y delegan **todo** el trabajo bcrypt (`gensalt` + `hashpw` / `checkpw`) a `asyncio.to_thread`, bajo un `asyncio.Semaphore` de tamaño `BCRYPT_MAX_CONCURRENCY`.

- El semáforo es un singleton de módulo creado **en la primera llamada**, no al importar: `_semaforo_bcrypt: asyncio.Semaphore | None`. La asignación ocurre antes de cualquier `await`, así que no hay carrera; crear el semáforo al importar leería `Settings` antes de tiempo y rompería "importar sin `.env`" (C-01).
- `asyncio.to_thread` usa el executor por defecto (en Windows, `min(32, cpu + 4)` hilos). Con el tope en 4, bcrypt nunca lo satura y quedan hilos para otros `to_thread` futuros.
- *Alternativa descartada*: `run_in_executor` con un `ThreadPoolExecutor` propio — da el mismo resultado pero agrega un ciclo de vida (crear/apagar el pool) que nadie pidió.
- *Alternativa descartada*: limitar el executor por defecto con `loop.set_default_executor` — penalizaría cualquier otro trabajo off-loop, no sólo bcrypt.
- *Alternativa descartada*: `anyio.to_thread.run_sync(..., limiter=CapacityLimiter(...))` — funciona, pero suma a `anyio` como dependencia explícita y `to_thread` ya es suficiente.

### D3 — Validación de 72 bytes en el módulo (defensa en profundidad)

Un helper privado codifica la contraseña a UTF-8 antes de cualquier bcrypt:

- `UnicodeEncodeError` (p. ej. un surrogate suelto que llega por JSON) → `PasswordInvalidaError`.
- `len(bytes) > 72` → `PasswordInvalidaError` con mensaje fijo; nunca se incluye la contraseña.
- La validación corre **antes** de adquirir el semáforo y antes de bcrypt, para no gastar tiempo ni hilo en una entrada inválida.

C-07 volverá a validar en el DTO (422 antes del servicio); esta capa garantiza que ni el seed ni un uso futuro puedan llamar bcrypt con una entrada fuera de contrato. `verify_password` también valida: un excedente no se trata como "contraseña incorrecta" (401) sino como entrada inválida.

bcrypt 5.0.0 ya lanza `ValueError` con >72 bytes; la pre-validación hace que el comportamiento sea el mismo con 4.x (IN-03) y permite devolver un error propio en vez del texto de la librería.

### D4 — Claims del JWT: `sub` texto e `iat` numérico con fracción

`crear_token_acceso` arma:

```python
marca = ahora or datetime.now(timezone.utc)
iat = marca.timestamp()  # float, conserva microsegundos
payload = {
    "sub": str(usuario_id),
    "iat": iat,
    "exp": int(iat) + get_settings().access_token_expire_seconds,
    "roles": [str(rol) for rol in roles],
}
jwt.encode(payload, secret_key, algorithm="HS256")
```

- **`sub` como texto** porque PyJWT 2.15 rechaza `sub` entero al decodificar (`InvalidSubjectError`). C-08 lo convierte a `int`; si no es numérico, el token es inválido.
- **`iat` como float** y no como `datetime`: PyJWT convierte `datetime` con `timegm(utctimetuple())` y trunca los microsegundos, lo que rompería RN07. El float es un NumericDate válido (RFC 7519 permite fracciones) y se conserva al codificar y decodificar.
- **`exp` entero**: `int(iat) + vigencia`. La vida efectiva del token puede quedar hasta un segundo por debajo de la configurada; irrelevante para 1800 s y evita fracciones innecesarias en `exp`.
- **`roles`**: copia informativa de los roles vigentes que recibe el emisor; no se consultan roles acá (eso es C-07 al emitir y C-08 al decidir).
- Sin `aud`, `iss`, `jti` ni `nbf`: un solo servicio, sin federación.
- La clave se lee con `get_secret_value()` sólo dentro de `encode`/`decode`; nunca se registra ni se devuelve.

### D5 — Verificación normalizada en `TokenAcceso`

`decodificar_token_acceso` llama a `jwt.decode(token, clave, algorithms=[ALGORITMO_JWT], options={"require": ["sub", "iat", "exp"]})`:

- Fijar `algorithms` evita aceptar otro algoritmo (p. ej. `none`).
- `require` convierte claims faltantes en error de PyJWT.
- Se capturan `jwt.PyJWTError`, `TypeError` y `ValueError` y se relanza `TokenInvalidoError("El token de acceso no es válido.")` con `from None`: ni el mensaje de PyJWT ni el token salen del módulo.
- Conversiones propias: `int(sub)` (falla → token inválido), `float(iat)`/`float(exp)` y `datetime.fromtimestamp(..., tz=timezone.utc)`.
- `roles`: si falta, `()`; si está, debe ser una lista de textos; cualquier otra forma invalida el token.
- `verify_exp` queda en su valor por defecto (`True`): el vencimiento lo decide PyJWT, no una comparación artesanal.
- La precisión del float es ~0.24 µs en la época actual, suficiente para comparar `iat` contra `password_cambiada_en` sin truncar (RN07).

### D6 — Cookie de sesión con helpers, sin leer headers

- `aplicar_cookie_acceso(response, token)` llama a `response.set_cookie(NOMBRE_COOKIE_ACCESO, token, max_age=settings.access_token_expire_seconds, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/")`.
- `eliminar_cookie_acceso(response)` llama a `response.delete_cookie(NOMBRE_COOKIE_ACCESO, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure)`; el navegador la borra por nombre y path.
- El valor del JWT es base64url con puntos: no requiere escapado de cookie.
- El módulo **no recibe `Request`** en ninguna función: no puede leer `Authorization` ni por accidente. El guard de C-08 deberá leer exclusivamente `request.cookies[NOMBRE_COOKIE_ACCESO]`.
- *Alternativa descartada*: devolver un `dict` con atributos para que el router arme la cookie — más flexible, pero permite que cada endpoint se equivoque en `HttpOnly`/`SameSite`. Un helper único centraliza DD-04.

### D7 — Hash ficticio una vez en el lifespan

`crear_hash_ficticio()` devuelve `await hash_password(secrets.token_urlsafe(32))`:

- 43 caracteres ASCII (< 72 bytes), aleatorio en cada arranque, imposible de adivinar y distinto de cualquier contraseña de usuario.
- Usa el mismo semáforo y `BCRYPT_COST` que los hashes reales: la verificación contra él cuesta lo mismo.
- En `lifespan` se asigna `app.state.hash_ficticio` **dentro del `try`**, antes del `yield`, para que un fallo de bcrypt dispare el `finally` que hace `engine.dispose()`.
- Costo aceptado: ~250–400 ms extra de arranque con costo 12.
- *Alternativa descartada*: calcularlo perezosamente en el primer login fallido — el primer intento tardaría distinto y varios logins concurrentes calcularían varios hashes.
- *Alternativa descartada*: un hash constante en el código — queda público y habría que actualizarlo a mano si cambia el costo.

### D8 — Configuración leída con `get_settings()` en cada llamada

Las funciones leen `get_settings()` (con `@lru_cache`) al invocarse, no al importar. Es el mismo patrón de C-01 y evita pasar `Settings` por routers y servicios que no lo necesitan.

- *Alternativa descartada*: parámetro `settings` explícito en cada función — más puro, pero obliga a C-06/C-07/C-08 a hilar la configuración por capas sin beneficio real, porque `get_settings()` ya es un singleton por proceso.
- *Alternativa descartada*: `settings = Settings()` a nivel de módulo — importar `security` exigiría `.env` y rompería la spec de runtime-lifecycle.

### D9 — Verificación sin test runner

No hay pytest (decisión del TP) ni endpoints nuevos todavía. Cada task verifica con:

- `& ".venv\Scripts\python.exe" -c "..."` para casos puntuales (hash/verify, claims, cookie, errores).
- Un script temporal en `$env:TEMP` para los chequeos de concurrencia y de bucle (instrumentar `bcrypt.hashpw` con un contador y correr tareas con `asyncio.gather`); no se versiona.
- `fastapi.testclient.TestClient` con `with TestClient(app)` para entrar al lifespan y comprobar `app.state.hash_ficticio` sin necesidad de PostgreSQL (`/health/live` no toca la base).
- El escenario "Authorization ignorado" se comprueba de punta a punta en C-08; en C-05 se verifica el invariante de diseño: `security.py` no menciona `Authorization` ni recibe `Request`.

## Risks / Trade-offs

- [Semáforo por proceso y ligado al bucle si alguna vez bloquea] → un solo proceso uvicorn en el TP; los scripts de verificación usan un único `asyncio.run`. Con varios workers, el tope real sería `workers × BCRYPT_MAX_CONCURRENCY`.
- [El executor por defecto es compartido] → el tope de 4 deja hilos libres; si en el futuro se agregan más tareas `to_thread`, revisar el tamaño del executor.
- [Igualdad de tiempos sólo aproximada] → el hash domina (~300 ms) frente a la consulta del usuario; C-07 debe verificar contra el hash ficticio **antes** de responder y no cortocircuitar cuando el correo no existe. Queda documentado para ese change.
- [Precisión del `iat` flotante] → ~0.24 µs, muy por debajo de la resolución de `password_cambiada_en`; C-08 debe fijar `password_cambiada_en` y recién después emitir la cookie nueva (el hash previo de ~300 ms garantiza un `iat` posterior).
- [`exp` entero acorta la vida hasta 1 s] → despreciable frente a 1800 s.
- [Hash ficticio agrega latencia al arranque] → aceptado (~250–400 ms); si bcrypt falla, la app no arranca, que es el comportamiento correcto.
- [`COOKIE_SECURE=false` en desarrollo] → el token viaja por HTTP local; en producción se configura `true`. Decisión ya tomada (RNF de la consigna).
- [Errores de token genéricos] → facilitan el debugging menos, pero cumplen "sin filtrar detalles" y evitan distinguir firma inválida de token vencido.
- [Roles dentro del token pueden quedar desactualizados] → son informativos por RN04; C-08 decide con la base en cada petición.

## Migration Plan

No hay cambios de esquema ni de datos. Despliegue: agregar `app/core/security.py`, reemplazar el comentario de `main.py` por la asignación del hash ficticio y reiniciar el proceso. Rollback: quitar la línea del lifespan y el módulo; no queda estado persistido. Al arrancar, verificar `/health/live` y que el arranque no falle por bcrypt.

## Open Questions

Ninguna. El contrato de `sub`, el nombre del claim de roles y el formato de `iat` se resuelven acá; C-07 y C-08 los consumen tal cual.
