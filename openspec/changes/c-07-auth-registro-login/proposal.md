# Proposal — C-07 auth-registro-login

## Why

C-03 dejó las tablas `usuario`, `asignacion_rol`, `cliente`, `intento_acceso` y `evento_seguridad`, y C-05 las primitivas de seguridad (bcrypt fuera del bucle, JWT, cookie, hash ficticio), pero todavía no hay forma de crear una cuenta ni de iniciar sesión: sin eso no se puede probar ninguna ruta protegida (C-08 en adelante). Además, el login es la superficie más expuesta del sistema: debe resistir fuerza bruta (RN08), no revelar qué correos existen (RN09) y el registro no puede dejar filas sueltas cuando choca con datos existentes (RN01, RN02). Casos de la consigna que cubre: C-02, C-03, C-04 y C-05.

## What Changes

- Módulo `usuarios` completo en capas: `schemas.py`, `repository.py`, `unit_of_work.py`, `service.py` y `router.py` (los modelos ya existen desde C-03).
- `POST /auth/registro` (público): crea en un solo Unit of Work el usuario, su rol CLIENTE, su ficha de cliente y una línea en `evento_seguridad`. La contraseña se hashea antes de abrir la transacción. Correo repetido o documento que ya es de un cliente → 409 con mensaje propio y sin filas sueltas; no se apropia de fichas existentes. Responde 201 sin cookie.
- `POST /auth/login` (público): límite de intentos por correo + IP (≥ 5 fallos en 60 s desde el último éxito → 429 con `Retry-After`, sin calcular ningún hash); verificación contra el hash real o el ficticio; 401 con el mismo cuerpo exista o no el correo; cada intento verificado se anota en `intento_acceso` con sesión y transacción propias, confirmadas siempre (excepción declarada en comentario). Éxito → cookie `access_token` y cuerpo `{mensaje, debe_cambiar_password, expira_en_segundos}` sin token.
- `POST /auth/logout` (público, idempotente): borra la cookie.
- `app/core/errores.py`: dos errores de aplicación nuevos, "no autenticado" (401) y "demasiados intentos" (429, con encabezado `Retry-After`), traducidos por el manejador global.
- `main.py`: el router de `/auth` se agrega al grupo de rutas abiertas.
- `test/auth.http`: casos C-02 a C-05 con la respuesta esperada en comentario.

Fuera de alcance (C-08/C-09): `get_usuario_actual`, `requiere_rol`, grupo de rutas protegidas, `GET /auth/yo`, `POST /auth/cambiar-password`, y la parte de C-03 que exige una ruta protegida (sin cookie o con `Authorization: Bearer` → 401), anotada en el scope de C-08.

## Capabilities

### New Capabilities
- `auth-registration`: auto-registro de clientes: contrato de entrada, creación atómica de usuario + rol CLIENTE + ficha + evento de seguridad, y conflictos de correo/documento sin filas sueltas (RN01, RN02).
- `auth-login`: inicio y cierre de sesión: límite de intentos por correo e IP (RN08), anti-enumeración (RN09), registro de cada intento en `intento_acceso`, emisión de la cookie de sesión y logout. Se separa de `auth-registration` porque evoluciona con C-08/C-09 (sesión, cambio de contraseña), mientras que el registro es una operación de alta autocontenida; y se separa de `security-core` porque esa capacidad son primitivas sin endpoints.

### Modified Capabilities
- `error-translation`: las operaciones pasan a poder señalar también "no autenticado" (401) y "demasiados intentos" (429 con `Retry-After`), con la misma forma `{"detail": …}`.

## Impact

- **Código nuevo**: `app/modules/usuarios/{schemas,repository,unit_of_work,service,router}.py`, `test/auth.http`.
- **Código modificado**: `app/core/errores.py` (dos clases y encabezados opcionales en el manejador de errores de aplicación), `main.py` (una línea: incluir el router de `/auth` en `rutas_abiertas`), `app/core/security.py` (**sólo el docstring**: una contraseña de más de 72 bytes en el login es 422 del DTO; el 401 del servicio queda como respaldo).
- **Sin cambios**: modelos, migraciones (la consigna exige exactamente dos; no se agrega una tercera), código de `security.py`, configuración, `.env`/`env.example`. `app/modules/clientes/` no se toca: el alta de la ficha usa el repositorio genérico (C-10 creará el repositorio de clientes).
- **Dependencias**: ninguna nueva (`EmailStr` usa `email-validator`, incluido en `fastapi[standard]`).
- **Datos**: los correos se guardan normalizados en minúsculas (la API normaliza en registro y login); el seed (C-06) debe cargarlos igual y fallar o normalizarlos si no (anotado en su scope). `nombre`, `documento` y `telefono` se guardan recortados, con largos máximos sólo en el contrato.
- **Downstream**: C-08 reutiliza la consulta de roles vigentes, el error 401 y el router de `/auth` (al que agrega `/auth/yo` y `/auth/cambiar-password`); C-09 hereda la convención de `evento_seguridad`; C-16 integra `test/auth.http`.
- **Governance**: CRÍTICO (auth). Ninguna línea de código se escribe sin aprobación humana explícita del plan.
