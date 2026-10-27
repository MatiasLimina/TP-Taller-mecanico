# Tasks — C-05 security-core

> **Verificación**: el TP no tiene test runner (sin pytest). Cada task se comprueba con comandos de PowerShell, scripts temporales en `$env:TEMP` (no se versionan) o `TestClient` para el lifespan. Governance **CRÍTICO (auth)**: revisar los escenarios de token/cookie antes de archivar.
> Skills a cargar antes de escribir código: `fastapi`.
> Prerrequisito: venv con `requirements.txt` instalado (bcrypt 5.x, PyJWT 2.x), `.env` con `SECRET_KEY` válida y PostgreSQL no es necesario para estas verificaciones.

## 1. Módulo y contraseñas (bcrypt)

- [x] 1.1 Crear `app/core/security.py` con docstring de contrato, `NOMBRE_COOKIE_ACCESO`, `ALGORITMO_JWT`, `MAX_BYTES_BCRYPT`, `PasswordInvalidaError`, `TokenInvalidoError`, el dataclass `TokenAcceso` y el helper privado que codifica la contraseña a UTF-8 y rechaza más de 72 bytes. Verificar: con `.env` renombrado temporalmente (`Rename-Item .env .env.bak; try { & ".venv\Scripts\python.exe" -c "import app.core.security" } finally { Rename-Item .env.bak .env }`) el import no falla, lo que confirma que no se lee `Settings` al importar; `& ".venv\Scripts\python.exe" -c "import app.core.security as s; print(s.__doc__)"` muestra funciones, claims, atributos de cookie y errores.
- [x] 1.2 Implementar `hash_password` y `verify_password`: validar antes de bcrypt, leer `get_settings()`, adquirir el semáforo perezoso de `BCRYPT_MAX_CONCURRENCY` y ejecutar `bcrypt.gensalt(rounds=...)`/`hashpw`/`checkpw` en `asyncio.to_thread`. Verificar con un script temporal: un mismo password produce dos hashes distintos (sal por hash), ambos verifican `True`, una contraseña incorrecta da `False`, y un hash ilegible (`"no-es-hash"`) da `False` sin excepción; el prefijo de los hashes es `$2b$12$`.
- [x] 1.3 Verificar el límite de 72 bytes (IN-03) con un script temporal: 72 bytes exactos hashean y verifican; 73 bytes lanzan `PasswordInvalidaError`; 40 caracteres `ñ` (80 bytes) lanzan `PasswordInvalidaError`; y verificar una contraseña de 73 bytes cuyos primeros 72 coinciden con una válida lanza `PasswordInvalidaError` en lugar de autenticar con el prefijo.
- [x] 1.4 Verificar concurrencia y no bloqueo con un script temporal: instrumentar `bcrypt.hashpw` con un contador de llamadas activas, lanzar 8 `hash_password` con `asyncio.gather` y comprobar que el máximo simultáneo es 4 y que las 8 terminan; en la misma corrida, un ticker `asyncio.sleep(0.01)` debe avanzar mientras se calculan los hashes (el bucle no se bloquea).

## 2. Tokens JWT

- [x] 2.1 Implementar `crear_token_acceso(usuario_id, roles, *, ahora=None)`: `sub` como texto, `iat` como `marca.timestamp()` (float), `exp = int(iat) + ACCESS_TOKEN_EXPIRE_SECONDS`, `roles` como lista de textos, firma HS256 con `SECRET_KEY`. Verificar con un script temporal y `jwt.decode` directo: `sub == "7"`, `roles` contiene los roles pasados, `exp - int(iat) == 1800`, y con `ahora=datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)` el `iat` decodificado conserva la fracción (`0.123456`).
- [x] 2.2 Implementar `decodificar_token_acceso` devolviendo `TokenAcceso` tz-aware en UTC, con `usuario_id` entero, `iat`/`exp` como `datetime` y `roles` como tupla; usar `algorithms=[ALGORITMO_JWT]` y `options={"require": ["sub", "iat", "exp"]}`. Verificar el camino feliz con un round-trip: `crear_token_acceso` → `decodificar` devuelve el mismo id, roles y una diferencia `exp - iat` de 1800 s (menos la fracción), sin error.
- [x] 2.3 Verificar los rechazos con un script temporal: token vencido (emitido con `ahora` 2000 s en el pasado), token alterado en un carácter, token firmado con otra clave (`jwt.encode` con `"otra-clave"`), token sin `sub`/`iat`/`exp` y token con `sub="abc"`; todos deben lanzar `TokenInvalidoError`, y `str(exc)` no debe contener el token, la clave ni el motivo de PyJWT.
- [x] 2.4 Verificar la precisión para RN07: emitir dos tokens con `ahora=t` y `ahora=t + 1 ms`, decodificarlos y comprobar que `iat` del segundo es estrictamente mayor que el del primero (la comparación con `password_cambiada_en` no se trunca).

## 3. Cookie de sesión

- [x] 3.1 Implementar `aplicar_cookie_acceso(response, token)` y `eliminar_cookie_acceso(response)` con `max_age=ACCESS_TOKEN_EXPIRE_SECONDS`, `httponly=True`, `samesite="lax"`, `path="/"` y `secure=COOKIE_SECURE`. Verificar con un `starlette.responses.Response` temporal: el header `set-cookie` contiene `access_token=`, `HttpOnly`, `SameSite=lax`, `Path=/` y `Max-Age=1800`, y no contiene `Secure` con el valor por defecto; el borrado contiene `Max-Age=0`.
- [x] 3.2 Verificar `Secure` configurable en un proceso nuevo: `$env:COOKIE_SECURE="true"` → el header incluye `Secure`; quitar la variable y repetir → no lo incluye. No modificar el `.env` del usuario.
- [x] 3.3 Verificar el invariante "sin Bearer": `Select-String -Path app\core\security.py -Pattern "\.headers|request\.|Authorization:"` no devuelve nada y `inspect.signature` de las funciones públicas no muestra parámetros `Request`, `Headers` ni `Cookie`; el escenario end-to-end (Bearer ignorado → 401) se comprueba en C-08.

## 4. Hash ficticio y lifespan

- [x] 4.1 Implementar `crear_hash_ficticio()` como `await hash_password(secrets.token_urlsafe(32))`. Verificar con un script temporal: devuelve un hash con prefijo `$2b$12$`, dos llamadas producen hashes distintos y `verify_password("cualquiera", hash_ficticio)` da `False`.
- [x] 4.2 Reemplazar el comentario de `main.py` por `app.state.hash_ficticio = await crear_hash_ficticio()` dentro del `try` del lifespan, antes del `yield`. Verificar con `with TestClient(app)`: `app.state.hash_ficticio` existe antes de la primera petición, `GET /health/live` responde 200, y dos peticiones sucesivas conservan exactamente el mismo `app.state.hash_ficticio` (no se recalcula).
- [x] 4.3 Verificar que el costo del hash ficticio es el configurado: comparar su prefijo con el de un `hash_password` real (`$2b$12$` con `BCRYPT_COST=12`) y, con `$env:BCRYPT_COST="4"` en un proceso nuevo, comprobar que ambos bajan a `$2b$04$` (sin tocar el `.env`).

## 5. Integración y cierre

- [x] 5.1 Correr un script temporal que recorra la checklist de `specs/security-core/spec.md`: hash/verify, sal, 72 bytes, concurrencia, emisión/verificación/vencimiento/alteración, cookie/borrado, hash ficticio y estabilidad en el lifespan. Anotar en el resumen del apply el resultado de cada grupo de escenarios.
- [x] 5.2 Verificar que el alcance no se desbordó: `git status --short` muestra sólo los artefactos OPSX y, tras implementar, `app/core/security.py` + `main.py`; `Select-String -Path main.py -Pattern "include_router"` sigue mostrando sólo el router de salud; no hay endpoints, guards, modelos ni migraciones nuevos, y `git diff` no toca `.env` ni `env.example`.

## Workflow follow-up

- Revisar los escenarios de token y cookie (governance CRÍTICO) antes de archivar el change.
- Archivar `c-05-security-core` y marcar `C-05` como `[x]` en `CHANGES.md`.
- No commitear ni pushear hasta que el usuario lo pida.
