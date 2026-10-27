# Proposal — C-08 auth-session-guards

## Why

C-07 entrega la cookie `access_token`, pero nada la lee todavía: no hay forma de saber quién hace una petición, de cortar una sesión vieja ni de decidir permisos. Sin eso no puede existir ninguna ruta protegida (C-09 en adelante) y quedan sin cumplir tres reglas de la consigna: los permisos se deciden con los roles vigentes en la base en cada petición (RN04), con cambio de contraseña pendiente sólo se puede usar `/auth` y salud (RN06), y al cambiar la contraseña las sesiones anteriores dejan de valer aunque sean del mismo segundo (RN07). Es el Ejercicio 5 (autorización, "401 y 403") más la parte del Ejercicio 4 que C-07 dejó pendiente: `GET /auth/yo`, el cambio de contraseña y el caso C-03 "sin cookie o con `Authorization: Bearer` → 401" (S-06 de C-07).

## What Changes

- `app/core/dependencies.py` (nuevo): `get_usuario_actual` lee la cookie de `request.cookies` y responde 401 si falta, si el token es inválido o venció, si el usuario no existe o está inactivo, o si el `iat` es anterior a `password_cambiada_en` (comparación sin truncar). `exigir_password_al_dia` responde 403 con el cambio de contraseña pendiente. `requiere_rol(*roles)` consulta en la base los roles vigentes en cada petición y responde 403 si ninguno coincide (RN04).
- `main.py`: dos grupos de rutas. El abierto (`/health/*`, `/auth/*`) ya existe; se agrega `rutas_protegidas` con el control de cambio de contraseña montado **una sola vez** a nivel de grupo (RN06). El grupo nace vacío: C-09 en adelante cuelgan sus routers de él.
- `GET /auth/yo` (autenticado, grupo abierto): el usuario, sus roles vigentes en la base y los roles que dice el token.
- `POST /auth/cambiar-password` (autenticado, grupo abierto): verifica la contraseña actual y hashea la nueva fuera de toda transacción; en un solo Unit of Work actualiza el hash, fija `password_cambiada_en`, baja `debe_cambiar_password` y deja una línea en `evento_seguridad`; entrega una cookie nueva que vale, mientras la anterior pasa a dar 401.
- `app/core/errores.py`: error de aplicación nuevo "sin permiso" (403) con la misma forma `{"detail": …}`.
- Módulo `usuarios`: servicio de sesión (autenticar, comprobar roles, perfil, cambio de contraseña) y contratos `CambioPasswordEntrada` y `PerfilSalida`. Reutiliza los repositorios de C-07 (`get_by_id`, `update`, `roles_vigentes`): no hay métodos de repositorio nuevos.
- `test/sesion.http`: casos C-03 (parte diferida), C-06 (parte de 401 contra 403 que no necesita órdenes) y C-09, con la respuesta esperada en comentario.

Fuera de alcance: alta de personal, asignación y revocación de roles, autoprotección y `GET /eventos` (C-09, casos PDF C-07 y C-08); "lo propio" de C-06 (`/mis-*`, dueño de la orden: C-10/C-13/C-15); cualquier ruta protegida de dominio.

## Capabilities

### New Capabilities
- `auth-session`: identificación del usuario de cada petición a partir de la cookie (los cinco motivos de 401, RN07 sin truncar, `Authorization` ignorado) y `GET /auth/yo`.
- `access-control`: grupos de rutas abierto y protegido, bloqueo por cambio de contraseña pendiente (RN06) y autorización por roles vigentes en la base en cada petición (RN04), con el orden 401 → 403.
- `auth-password-change`: `POST /auth/cambiar-password`: contrato (72 bytes, mínimo de la nueva), verificación de la actual, cambio atómico con evento de seguridad, invalidación de las sesiones anteriores y cookie nueva (RN07). Se separa de `auth-login` porque es una operación de escritura autenticada con su propia regla de invalidación, y de `auth-session` porque esa capacidad sólo lee.

### Modified Capabilities
- `error-translation`: las operaciones pasan a poder señalar también "sin permiso" (403), con la misma forma `{"detail": …}`.

## Impact

- **Código nuevo**: `app/core/dependencies.py`, `test/sesion.http`.
- **Código modificado**: `app/core/errores.py` (clase 403 y docstring), `app/modules/usuarios/{schemas,service,router}.py` (piezas de sesión y cambio de contraseña, sin tocar registro/login/logout), `main.py` (grupo protegido).
- **Sin cambios**: modelos y migraciones (`password_cambiada_en`, `debe_cambiar_password` y `activo` existen desde C-03; la consigna exige exactamente dos migraciones), `app/core/security.py` (ya emite `iat` con fracción y acepta la marca de emisión), `app/modules/usuarios/{repository,unit_of_work}.py`, configuración, `.env`/`env.example`.
- **Dependencias**: ninguna nueva.
- **Downstream**: C-09 monta `/usuarios` y `/eventos` en `rutas_protegidas` con `requiere_rol(Rol.ADMIN)` y completa los casos C-07/C-08/C-09 del PDF; C-10 a C-15 usan `UsuarioActualDep`/`requiere_rol`; C-06 (seed) puede cargar usuarios con `debe_cambiar_password=true`; C-16 integra `test/sesion.http`.
- **Governance**: CRÍTICO (autorización, 401 contra 403). Ninguna línea de código se escribe sin aprobación humana explícita del plan y de los supuestos S-01…S-09 de `design.md`.
