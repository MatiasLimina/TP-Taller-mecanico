# Proposal — C-05 security-core

## Why

C-01 dejó la configuración y el ciclo de vida, pero no existe ninguna primitiva de seguridad: sin hashing de contraseñas ni tokens no se puede autenticar. C-06 necesita hashes para el seed, C-07 necesita hashear/verificar y emitir la cookie, y C-08 necesita verificar el token en cada petición. Además, bcrypt es costoso (~300 ms): si corre en el bucle de eventos frena todas las peticiones, y si el login responde distinto según exista o no el correo, revela qué cuentas existen (RN09).

## What Changes

- Nuevo `app/core/security.py` con:
  - Hash y verificación bcrypt con el costo de `BCRYPT_COST`, ejecutados en `asyncio.to_thread` bajo un semáforo de `BCRYPT_MAX_CONCURRENCY` operaciones simultáneas.
  - Rechazo de contraseñas de más de 72 **bytes** UTF-8 (no caracteres), sin truncarlas (IN-03).
  - Emisión y verificación de JWT (HS256) con `sub`, `iat` con fracción de segundo, `exp` y `roles` vigentes informativos; errores normalizados en excepciones propias.
  - Helpers para poner y borrar la cookie `access_token` (HttpOnly, SameSite=Lax, `Path=/`, Max-Age igual a la vigencia, `Secure` según `COOKIE_SECURE`). El módulo no lee `Authorization`.
  - Generación de un hash ficticio con sal aleatoria y el mismo costo, para anti-enumeración.
- `main.py`: el lifespan calcula el hash ficticio una sola vez y lo deja en `app.state.hash_ficticio`.
- Sin endpoints, guards, modelos, migraciones ni variables de entorno nuevas.

## Capabilities

### New Capabilities
- `security-core`: primitivas de seguridad del proceso: hashing bcrypt no bloqueante y acotado, límite de longitud de contraseña, emisión/verificación de tokens JWT, transporte en cookie HttpOnly y hash ficticio de anti-enumeración.

### Modified Capabilities
- (ninguna — el comportamiento de las specs existentes no cambia.)

## Impact

- **Código nuevo**: `app/core/security.py`.
- **Código modificado**: `main.py` (una línea en el lifespan, en el lugar ya reservado por C-01).
- **Dependencias**: `bcrypt` y `PyJWT` ya están en `requirements.txt` (C-01); no se agregan paquetes.
- **Configuración**: se consumen `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_SECONDS`, `BCRYPT_COST`, `BCRYPT_MAX_CONCURRENCY` y `COOKIE_SECURE`, ya existentes. Sin cambios en `.env` ni en `env.example`.
- **Datos**: sin cambios de esquema ni migraciones.
- **Downstream**: C-06 usa `hash_password` para el seed; C-07 usa hash/verify, emisión y cookie; C-08 usa la verificación del token y `app.state.hash_ficticio`. Los escenarios de cookie y de `Authorization` ignorado se comprueban de punta a punta en C-07/C-08.
