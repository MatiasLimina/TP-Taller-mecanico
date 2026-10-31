# Design — C-16 verificacion-http-readme

## Context

Motivación y alcance: ver `proposal.md`. Este change no modifica comportamiento de la aplicación ni agrega requisitos a las especificaciones (`skip_specs: true` en `.openspec.yaml`): cierra los entregables documentales y de verificación de la Fase 6 (US-070, Flujo 9 y págs. 20–22 de `docs/TP_Cap1a6_Consigna.pdf`).

Estado actual de `main` (`941cb7e`):

- **Código de la aplicación y migraciones (C-01…C-15)**:
  - 28 rutas montadas en `main.py` en dos grupos (`rutas_abiertas`: `/health/*` y `/auth/*`; `rutas_protegidas`: `/usuarios`, `/eventos`, `/clientes`, `/vehiculos`, `/mis-vehiculos`, `/repuestos`, `/ordenes`, `/estados-orden`, `/mis-ordenes`, con `exigir_password_al_dia` montado una sola vez).
  - 2 migraciones en `migrations/versions/`: `1c921a1fe62f_esquema_inicial.py` (autogenerada, 13 tablas, 3 índices únicos parciales, CHECKs y FKs, catálogo `estado_orden` vacío) y `9141e6428bad_solo_agregado.py` (escrita a mano, función `rechazar_cambio_solo_agregado()` + disparador `trg_solo_agregado` sobre `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`), ambas con comentario «leída antes de aplicar».
  - `seed.py` (C-06): vacía las 13 tablas con `TRUNCATE TABLE … RESTART IDENTITY CASCADE` en una sola transacción del `UnitOfWork` y carga el estado inicial determinista (4 estados, 7 usuarios con `ClaveSegura1`/`Provisoria1`, 2 fichas de cliente, 3 vehículos, 4 repuestos con movimiento `Stock inicial`, 1 línea de historial de precio `8000.00 -> 8500.00`, 2 órdenes con ítems e historial —la #2 con 4 bujías y stock 2, IN-04— y 1 evento `SISTEMA`).
- **Archivos existentes en `test/`**:
  - Corren directamente después de `python seed.py` sin `psql` intermedio: `health.http` (2 casos), `seed.http` (19 casos), `lecturas_ordenes.http` (70 casos, cubre PDF C-15 y C-17), `seed.sql` (14 consultas de sólo lectura) y `solo_agregado.sql` (evidencia SQL de PDF C-14 con `ROLLBACK`).
  - Llevan bloques `psql` de preparación o pasos intermedios en `psql` porque fueron escritos antes de que `seed.py` estuviera en `main`: `auth.http` (43 casos; requiere `INSERT` de ficha `20111222` para el caso 6), `sesion.http` (32 casos; usa `psql` para asignar roles y desactivar usuario), `personal.http` (70 casos; usa `psql` para el primer `ADMIN` y vencimientos), `clientes.http` (69 casos; usa `psql` para roles y órdenes de prueba), `repuestos.http` (91 casos; hace `TRUNCATE` y asigna roles por `psql`), `stock.http` (72 casos; hace `TRUNCATE` y asigna roles por `psql`), `ordenes.http` (79 casos; hace `TRUNCATE` y asigna roles por `psql`), `transiciones.http` (97 casos; hace `TRUNCATE` y asigna roles por `psql`).
  - Evidencias y scripts: `test/evidencia_c15.txt` (generado en C-15 con `SQL_ECHO=true`: 5 sentencias `SELECT` para 2 y 4 ítems) y `test/verificar_security_core.py` (verificación autónoma de C-05 sin base).
- **Faltantes para la entrega**:
  1. `README.md` en la raíz (hoy no existe).
  2. Un archivo `.http` integrador (`test/casos_pdf.http`) que cumpla literalmente la consigna («El proyecto incluye archivos `.http` en `test/` que demuestran los casos siguientes [C-01…C-19], cada uno con la respuesta esperada en un comentario… Antes de cada archivo se corre `python seed.py`») y la verificación end-to-end de la matriz RBAC contra el seed, ejecutable de principio a fin por HTTP tras `python seed.py` sin ningún paso manual en `psql`.
  3. `test/evidencia_c14.txt` con la salida capturada de `psql -f test/solo_agregado.sql` (los 6 rechazos `P0001` y el `23503` de clave foránea).
  4. Ejecución de cierre del chequeo de condición bloqueante (ciclo de migraciones sobre base vacía y auditoría de secretos).

## Goals / Non-Goals

**Goals:**
- Entregar un `README.md` claro, reproducible desde cero en Windows/PowerShell, que incluya las evidencias de C-14, C-15 y C-12, la advertencia de `python seed.py` (heredada de C-06), la tabla del estado inicial y el mapa completo de casos C-01…C-19.
- Proveer `test/casos_pdf.http` ejecutable al 100 % por HTTP inmediatamente después de `python seed.py` (cero `psql` intermedio), cubriendo la matriz RBAC y los casos PDF C-01…C-19 sobre los datos del seed, sin tocar los 11 archivos `.http` existentes.
- Versionar `test/evidencia_c14.txt` como par de `test/evidencia_c15.txt`.
- Dejar un procedimiento automático de verificación (`$env:TEMP\verificar_c16.py`) que compruebe condición bloqueante, secretos, ciclo de migraciones, `seed.py`, `solo_agregado.sql` y los 72 casos de `test/casos_pdf.http`.

**Non-Goals:**
- Modificar `app/**`, `main.py`, `seed.py`, `migrations/**`, `alembic.ini`, `env.example` o `.gitignore`.
- Reescribir o borrar los 11 archivos `.http` de C-01…C-15 (siguen siendo la batería exhaustiva por módulo).
- Introducir `pytest` o herramientas externas no declaradas en `requirements*.txt`.

## Decisions

### D1 — Archivos del change

| Archivo | Cambio |
|---------|--------|
| `test/evidencia_c14.txt` (nuevo, generado) | Salida de `psql -f test/solo_agregado.sql` con los 6 errores `P0001`, el `23503`, el conteo `1 \| 1 \| 1` y `ROLLBACK` (D3) |
| `test/casos_pdf.http` (nuevo) | 72 peticiones HTTP ejecutables de corrido tras `python seed.py`: logins del seed, matriz RBAC y casos PDF C-01…C-19 (D2) |
| `README.md` (nuevo, raíz) | Guía desde cero, advertencia del seed, estado inicial, tabla de rutas/RBAC, índice C-01…C-19 y evidencias C-14, C-15 y C-12 (D4) |

No se modifica ningún archivo existente fuera de `openspec/changes/c-16-verificacion-http-readme/`.

### D2 — Diseño de `test/casos_pdf.http` (ejecución 100 % HTTP sobre `python seed.py`)

El archivo parte de `python seed.py` recién ejecutado y se recorre de arriba abajo sin tocar `psql`. Todas las peticiones llevan `# @no-cookie-jar` y comentario `# Esperado: <código> …`. El orden de las secciones evita que un caso altere las filas que necesita otro posterior:

1. **Sección A — Logins de los 7 usuarios del seed (casos 1–7)**:
   - `1` `loginAdmin` (`admin@example.com`, id 1, `ADMIN`), `2` `loginAdmin2` (`admin2@example.com`, id 2, `ADMIN`), `3` `loginRecepcion` (`recepcion@example.com`, id 3, `RECEPCION`), `4` `loginMecanico` (`mecanico@example.com`, id 4, `MECANICO`), `5` `loginMecanico2` (`mecanico2@example.com`, id 5, `MECANICO`), `6` `loginCliente` (`cliente@example.com`, id 6, `CLIENTE`, dueña de los vehículos 1 `AB123CD` y 2 `AC456EF` y de la orden 1), `7` `loginNuevo` (`nuevo@example.com`, id 7, `MECANICO` con `debe_cambiar_password: true`, contraseña `Provisoria1`).
   - El caso `1` documenta la primera mitad de **PDF C-03**: `Set-Cookie: access_token=<jwt>; HttpOnly; Max-Age=1800; Path=/; SameSite=lax` y cuerpo `{"mensaje": "Sesión iniciada", "debe_cambiar_password": false, "expira_en_segundos": 1800}` sin token.

2. **Sección B — Casos PDF C-01 a C-04, C-06 y Matriz RBAC contra el seed (casos 8–26)**:
   - **PDF C-01 (casos 8–9)**: `GET /ordenes/abc` con `loginRecepcion` → `422` (`int_parsing` en `["path", "orden_id"]`, sin ejecutar el handler); `GET /repuestos/abc` con `loginMecanico` → `422` (`["path", "repuesto_id"]`).
   - **PDF C-02 (casos 10–14)**:
     - `10` `POST /auth/registro` de `carlos@cierre.example.com` (doc `49000001`, tel `1149000001`, `@name registroCarlos`) → `201` (`id: 8`, `cliente.id: 3`, `roles: ["CLIENTE"]`).
     - `11` `POST /auth/registro` con correo repetido `carlos@cierre.example.com` y doc nuevo `49000002` → `409` `{"detail": "El correo ya está registrado"}` (sin fila suelta para `49000002`).
     - `12` `POST /auth/registro` con correo nuevo `otro@cierre.example.com` y doc repetido `49000001` → `409` `{"detail": "El documento ya pertenece a un cliente del taller"}` (sin usuario `otro@cierre.example.com`).
     - `13` `POST /auth/registro` con correo nuevo `jorge@cierre.example.com` y doc `25111333` (ficha de Jorge del seed, sin usuario, RN02) → `409` `{"detail": "El documento ya pertenece a un cliente del taller"}`.
     - `14` `POST /auth/login` de `carlos@cierre.example.com` (`@name loginCarlos`) → `200`.
   - **PDF C-03 (casos 15–17)**:
     - `15` `GET /auth/yo` sin cookie → `401` `{"detail": "Se requiere iniciar sesión"}`.
     - `16` `GET /auth/yo` sin cookie y con `Authorization: Bearer token-ignorado` → `401` `{"detail": "Se requiere iniciar sesión"}`.
     - `17` `GET /auth/yo` con `loginAdmin` → `200` con `roles_vigentes: ["ADMIN"]` y `roles_token: ["ADMIN"]`.
   - **PDF C-04 (casos 18–19)**:
     - `18` `POST /auth/login` `recepcion@example.com` con contraseña incorrecta → `401` `{"detail": "Correo o contraseña incorrectos"}`.
     - `19` `POST /auth/login` `inexistente@cierre.example.com` con contraseña incorrecta → `401` `{"detail": "Correo o contraseña incorrectos"}` (mismo mensaje y verificación contra hash ficticio, RN09).
   - **PDF C-06 y Matriz RBAC end-to-end (casos 20–26)**:
     - `20` Ruta protegida sin cookie (`GET /ordenes`) → `401` `{"detail": "Se requiere iniciar sesión"}`.
     - `21` Ruta protegida con cambio obligatorio pendiente (`GET /ordenes` con `loginNuevo`, RN06) → `403` `{"detail": "Debe cambiar la contraseña antes de continuar"}`; grupo abierto (`GET /auth/yo` con `loginNuevo`) → `200` con `debe_cambiar_password: true`.
     - `22` Rutas exclusivas de `ADMIN` rechazadas a otros roles: `GET /eventos` con `loginRecepcion` → `403`; `POST /usuarios` con `loginMecanico` → `403`; `POST /repuestos` con `loginRecepcion` → `403`; `GET /repuestos/1/movimientos` con `loginMecanico` → `403`; `GET /repuestos/1/precios` con `loginRecepcion` → `403` (también parte de **PDF C-18**).
     - `23` Rutas de `RECEPCION`/`ADMIN` rechazadas a `MECANICO` y `CLIENTE`: `GET /clientes/1` con `loginCliente` → `403`; `POST /clientes` con `loginMecanico` → `403`; `DELETE /vehiculos/1` con `loginMecanico` → `403`; `POST /ordenes` con `loginMecanico` → `403`.
     - `24` Rutas del personal rechazadas a `CLIENTE`: `GET /repuestos` con `loginCliente` → `403`; `GET /ordenes` con `loginCliente` → `403`.
     - `25` Ruta exclusiva de `MECANICO` (`POST /ordenes/1/iniciar`) rechazada a `loginAdmin` (`ADMIN` no es comodín) y a `loginRecepcion` → `403` `{"detail": "No tiene permiso para realizar esta operación"}`.
     - `26` **Lo propio (PDF C-06, RN17)**:
       - `26a` `GET /ordenes/1` con `loginCliente` (Laura, dueña del vehículo 1) → `200` (ve su orden).
       - `26b` `GET /ordenes/2` con `loginCliente` (orden de Jorge, ajena) → `403` `{"detail": "Sólo el personal del taller o el dueño del vehículo puede ver la orden"}`.
       - `26c` `GET /ordenes/1` con `loginCarlos` (otro cliente, ajena) → `403` `{"detail": "Sólo el personal del taller o el dueño del vehículo puede ver la orden"}`.
       - `26d` `GET /mis-vehiculos` con `loginCliente` → `200` con `AB123CD` y `AC456EF`.
       - `26e` `GET /mis-ordenes` con `loginCliente` → `200` con `total: 1` (orden 1).
     *(Para mantener numeración correlativa `1..72` en `### N.`, cada petición individual lleva su propio número `### N.`).*

3. **Sección C — Casos PDF C-07, C-08 y C-09 (roles, autoprotección y cambio obligatorio)**:
   - **PDF C-07**:
     - `POST /usuarios/2/roles` con `loginAdmin` y `vence_en` en el pasado (`"2020-01-01T00:00:00Z"`) → `422`.
     - `POST /usuarios/2/roles` con `loginAdmin` y `vence_en` sin zona horaria (`"2030-01-01T00:00:00"`) → `422`.
     - `DELETE /usuarios/2/roles/ADMIN` con `loginAdmin` (revoca el `ADMIN` de `admin2@example.com`, permitido porque `admin@example.com` sigue siendo `ADMIN` vigente sin vencimiento) → `200` con `revocada_en` no nulo.
     - `GET /eventos` con la misma cookie `loginAdmin2` → `403` `{"detail": "No tiene permiso para realizar esta operación"}` (RN04).
     - `GET /auth/yo` con la misma cookie `loginAdmin2` → `200` con `roles_vigentes: []` y `roles_token: ["ADMIN"]`.
     - `GET /usuarios/2/roles` con `loginAdmin` → `200` con `roles_vigentes: []` y la fila revocada conservada en `asignaciones`.
   - **PDF C-08**:
     - `DELETE /usuarios/1/roles/ADMIN` con `loginAdmin` → `409` `{"detail": "Un administrador no puede revocarse su propio rol ADMIN"}` (RN05).
   - **PDF C-09**:
     - `POST /auth/login` de `nuevo@example.com` con `Provisoria1` (`@name loginNuevoAntes`) → `200` (`debe_cambiar_password: true`).
     - `POST /auth/cambiar-password` enseguida con `loginNuevoAntes` (`Provisoria1` → `NuevaSegura1`, `@name cambioNuevo`) → `200` con `Set-Cookie` nueva y `debe_cambiar_password: false`.
     - `GET /ordenes` con la cookie de `cambioNuevo` → `200` (la nueva cookie vale en el grupo protegido).
     - `GET /auth/yo` con la cookie de `loginNuevoAntes` → `401` `{"detail": "La sesión no es válida o venció"}` (RN07, sin esperar entre el login y el cambio).

4. **Sección D — Casos PDF C-16, C-18 y C-17 (repuestos, precios y catálogo de estados)**:
   - **PDF C-16**:
     - `GET /repuestos?q=%27%20OR%20%271%27%3D%271` con `loginRecepcion` → `200` con `items: []` y `total: 0`.
     - `GET /repuestos?q=freno&size=1` con `loginRecepcion` → `200` con `PAS-FRE-DEL`, `total: 1`, `pages: 1`.
     - `GET /repuestos?q=freno&size=1&page=2` con `loginRecepcion` → `422` `{"detail": "La página 2 no existe: hay 1"}`.
     - `GET /repuestos?size=500` con `loginRecepcion` → `422`.
     - `PATCH /repuestos/2` con `loginAdmin` `{"descripcion": "Pastillas de freno delanteras ventiladas"}` → `200` (sólo cambia `descripcion`; `precio` sigue `"32000.00"` y `stock` `4`).
     - `PATCH /repuestos/2` con `loginAdmin` `{"stock": 99}` → `422` (`extra_forbidden`).
   - **PDF C-18**:
     - `PATCH /repuestos/2` con `loginAdmin` `{"precio": "35000.00"}` → `200` (`precio: "35000.00"`).
     - `PATCH /repuestos/2` con `loginAdmin` `{"descripcion": "Pastillas de freno delanteras"}` → `200` (no cambia el precio).
     - `GET /repuestos/2/precios` con `loginAdmin` → `200` con una única línea (`precio_anterior: "32000.00"`, `precio_nuevo: "35000.00"`; el segundo PATCH no agregó línea).
     - `GET /repuestos/2/precios` con `loginRecepcion` → `403` `{"detail": "No tiene permiso para realizar esta operación"}`.
   - **PDF C-17**:
     - `GET /estados-orden` sin cookie → `401` `{"detail": "Se requiere iniciar sesión"}`.
     - `GET /estados-orden` con `loginCliente` → `200` con los 4 estados por `posicion` (`TERMINADA` y `CANCELADA` con `es_final: true`).
     - `GET /ordenes?estado=REABIERTA` con `loginRecepcion` → `422` (`loc: ["query", "estado"]`).

5. **Sección E — Casos PDF C-10, C-11, C-12, C-13 y C-15 (órdenes de trabajo)**:
   - **PDF C-10**:
     - `POST /ordenes` con `loginRecepcion` y `repuesto_id: 9999` → `409` `{"detail": "Repuestos inexistentes o dados de baja: 9999"}`.
     - `POST /ordenes` con `loginRecepcion` sobre `vehiculo_id: 1` (`AB123CD` de Laura) con 2 ítems (`repuesto_id: 1` × 2 y `repuesto_id: 4` × 1) → `201` (`id: 3`, `estado: "PENDIENTE"`, `total: "29000.00"`, precios copiados e historial `null -> PENDIENTE`).
   - **PDF C-11**:
     - `POST /ordenes/2/terminar` con `loginMecanico` → `409` `{"detail": "Stock insuficiente para el repuesto BUJ-01: hay 2 y se necesitan 4"}`.
     - `GET /repuestos/3` con `loginMecanico` → `200` (`stock: 2`) y `GET /ordenes/2` con `loginMecanico` → `200` (`estado: "EN_REPARACION"`, 2 líneas de historial).
   - **PDF C-12**:
     - `POST /repuestos/3/reponer` con `loginAdmin` `{"cantidad": 2, "motivo": "Reposición para orden #2"}` → `200` (`stock: 4`).
     - `POST /ordenes/2/terminar` con `loginMecanico` → `200` (`estado: "TERMINADA"`, 3 líneas de historial; aviso simulado en consola tras 0,5 s).
     - `GET /repuestos/3/movimientos` con `loginAdmin` → `200` con 3 movimientos (`+2`, `+2`, `-4` con `orden_id: 2`).
   - **PDF C-13**:
     - `POST /ordenes/3/cancelar` con `loginCarlos` (ajena) → `403` `{"detail": "Sólo la recepción, un administrador o el dueño del vehículo puede cancelar la orden"}`.
     - `POST /ordenes/3/cancelar` con `loginCliente` (Laura, dueña de la orden 3 `PENDIENTE`) → `200` (`estado: "CANCELADA"`).
     - `POST /ordenes/2/cancelar` con `loginRecepcion` (orden 2 `TERMINADA`) → `409` `{"detail": "La orden 2 está TERMINADA, un estado final: no admite más cambios"}`.
   - **PDF C-15**:
     - `POST /ordenes` con `loginRecepcion` sobre `vehiculo_id: 1` con 4 ítems (`repuesto_id` 1, 2, 3, 4 × 1) → `201` (`id: 4`, `total: "60000.00"`).
     - `GET /ordenes/1` con `loginRecepcion` (2 ítems) → `200` (5 sentencias `SELECT` en consola).
     - `GET /ordenes/4` con `loginRecepcion` (4 ítems) → `200` (las mismas 5 sentencias `SELECT` en consola).

6. **Sección F — Caso PDF C-19 (baja lógica de vehículo sin órdenes y reutilización de patente)**:
   - El vehículo 2 (`AC456EF`, de Laura) no tiene órdenes (las órdenes 1, 3 y 4 son del vehículo 1; la 2 es del vehículo 3).
   - `DELETE /vehiculos/2` con `loginRecepcion` → `204` sin cuerpo.
   - `POST /clientes/2/vehiculos` con `loginRecepcion` (`{"patente": "AC456EF", "marca": "Volkswagen", "modelo": "Gol Trend", "anio": 2018}`, para Jorge, ficha 2) → `201` (`id: 4`, `cliente_id: 2`, `patente: "AC456EF"`).
   - `POST /clientes/1/vehiculos` con `loginRecepcion` con la misma patente `"AC456EF"` → `409` `{"detail": "Ya hay un vehículo vigente con la patente AC456EF"}`.

7. **Sección G — Caso PDF C-05 (límite de intentos de login: 6 fallos seguidos → 429 con `Retry-After`)**:
   - Se ejecuta al final sobre `"carlos@cierre.example.com"` para no bloquear a ningún usuario del seed:
   - 5 peticiones `POST /auth/login` con `{"email": "carlos@cierre.example.com", "password": "ClaveMala1"}` → cada una responde `401` `{"detail": "Correo o contraseña incorrectos"}`.
   - 6.ª petición `POST /auth/login` con `{"email": "carlos@cierre.example.com", "password": "ClaveMala1"}` → `429` con encabezado `Retry-After` y cuerpo `{"detail": "Demasiados intentos fallidos. Espere antes de volver a intentar"}`, en pocos milisegundos sin calcular bcrypt.

### D3 — Evidencia del caso PDF C-14 (`test/evidencia_c14.txt`)

- `test/solo_agregado.sql` ya existe desde C-04 y es idempotente porque abre `BEGIN;` y termina en `ROLLBACK;`.
- Para dejar la evidencia versionada (igual que `test/evidencia_c15.txt` en C-15) y además incluir su fragmento en `README.md`, el script de verificación ejecuta `psql` contra la base migrada con `-f test/solo_agregado.sql` (con `PGOPTIONS="-c lc_messages=C"` o codificación UTF-8 limpia y sin imprimir contraseñas ni URLs) y guarda la salida completa (`stdout` + `stderr` intercalados) en `test/evidencia_c14.txt`, precedida por dos líneas de encabezado:
  - `Evidencia del caso PDF C-14 — disparador de sólo agregado y clave foránea de estado_orden`
  - `Generada con psql -f test/solo_agregado.sql sobre la base migrada con alembic upgrade head`
- Se verifica que `test/evidencia_c14.txt` contenga exactamente:
  - 6 ocurrencias de `P0001` (`UPDATE rechazado: historial_estado_orden es de solo agregado`, `DELETE rechazado: historial_estado_orden es de solo agregado`, `UPDATE rechazado: movimiento_stock es de solo agregado`, `DELETE rechazado: movimiento_stock es de solo agregado`, `UPDATE rechazado: historial_precio_repuesto es de solo agregado`, `DELETE rechazado: historial_precio_repuesto es de solo agregado`),
  - 1 ocurrencia de `23503` con `fk_orden_trabajo_estado_estado_orden`,
  - la fila de comprobación `1 |               1 |                         1`,
  - y `ROLLBACK`.

### D4 — Estructura y contenido de `README.md`

`README.md` (en la raíz, en español y con enlaces relativos a los archivos del repo) tendrá exactamente estas secciones:

1. **Título, descripción e integrantes**:
   - Resumen de la API asincrónica del taller mecánico (Programación III, caps. 1–6).
   - Tabla de integrantes (`Matías Limina`, `Nicolás Lionel Monjelardi`, `Lautaro Agustín Agüero` con sus usuarios de GitHub de `docs/REPARTO_DE_TAREAS.md` §1).
2. **Stack tecnológico y arquitectura**:
   - Tabla de tecnologías y versiones mínimas (`Python 3.12`, `FastAPI >=0.111`, `SQLModel >=0.0.45`, `SQLAlchemy[asyncio] >=2.0`, `asyncpg >=0.30`, `PostgreSQL 16`, `Alembic >=1.13`, `pydantic-settings >=2.0`, `bcrypt >=4.0`, `PyJWT >=2.8`, `uvicorn`).
   - Capas por módulo (`Router → Service → UoW → Repository → Model`) y árbol de directorios del proyecto (`main.py`, `seed.py`, `alembic.ini`, `env.example`, `requirements.txt`, `requirements-dev.txt`, `app/core/`, `app/modules/`, `migrations/`, `test/`).
3. **Puesta en marcha desde cero (Flujo 9, US-070)**:
   - Prerrequisitos: Python 3.12+ y PostgreSQL 16 con una base vacía creada (p. ej. `CREATE DATABASE taller;`).
   - Paso 1 — Entorno virtual e instalación:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     pip install -r requirements.txt
     pip install -r requirements-dev.txt
     ```
   - Paso 2 — Configuración (`.env` y clave de firma):
     ```powershell
     Copy-Item env.example .env
     python -c "import secrets; print(secrets.token_urlsafe(64))"
     ```
     Indicar que se deben completar en `.env` los dos secretos obligatorios sin valor por defecto (`POSTGRES_PASSWORD` y `SECRET_KEY`), que `.env` está en `.gitignore` y nunca se sube al repositorio, y que en PowerShell debe usarse `Copy-Item` (no `>`, que escribe UTF-16). Tabla de todas las variables de `env.example`.
   - Paso 3 — Migraciones de Alembic:
     ```powershell
     alembic upgrade head
     ```
     Explicar las dos revisiones: `1c921a1fe62f_esquema_inicial.py` (`--autogenerate`, 13 tablas, catálogo `estado_orden` vacío) y `9141e6428bad_solo_agregado.py` (manual, función + disparador `trg_solo_agregado` sobre las 3 tablas de historial), y cómo probar el ciclo completo `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` y `alembic check`.
   - Paso 4 — Carga de datos iniciales (`seed.py`):
     ```powershell
     python seed.py
     ```
     **Advertencia destacada (heredada de C-06)**: `python seed.py` **borra todos los datos de las 13 tablas del dominio** de la base configurada en `.env` (`TRUNCATE TABLE … RESTART IDENTITY CASCADE`) y recarga el estado inicial conocido con ids deterministas; es una herramienta exclusiva de desarrollo y pruebas y debe correrse antes de cada archivo `.http`.
   - Paso 5 — Arranque del servidor:
     ```powershell
     uvicorn main:app --port 8000
     ```
     Y cómo arrancarlo mostrando las consultas SQL en consola (`$env:SQL_ECHO="true"; uvicorn main:app --port 8000`).
4. **Estado inicial cargado por `python seed.py`**:
   - Tablas con los 4 estados (`PENDIENTE`, `EN_REPARACION`, `TERMINADA`, `CANCELADA`), los 7 usuarios (`admin@`, `admin2@`, `recepcion@`, `mecanico@`, `mecanico2@`, `cliente@` con `ClaveSegura1`, y `nuevo@example.com` con `Provisoria1` y `debe_cambiar_password=true`), los 2 clientes (Laura id 1 con vehículos 1 `AB123CD` y 2 `AC456EF`; Jorge id 2 sin usuario con vehículo 3 `AD789GH`), los 4 repuestos (`FIL-ACE-01`, `PAS-FRE-DEL`, `BUJ-01`, `ACE-5W30-1L`), el historial inicial de precio del filtro (`8000.00 -> 8500.00`), las 2 órdenes (#1 `PENDIENTE` de Laura; #2 `EN_REPARACION` de Jorge con 4 bujías y stock 2, IN-04) y el evento `SISTEMA`.
5. **Matriz de endpoints y permisos (RBAC)**:
   - Tabla de las 28 rutas agrupadas en grupo abierto (`/health/*`, `/auth/*`) y grupo protegido, con quién puede llamar a cada una y qué códigos devuelve.
6. **Casos de prueba (`.http` y `.sql` en `test/`)**:
   - Cómo ejecutar el archivo integrador `test/casos_pdf.http` directamente después de `python seed.py` con la extensión REST Client de VS Code (sin pasos manuales en `psql`).
   - Tabla de trazabilidad de los **19 casos de prueba mínimos del PDF (C-01 a C-19)** indicando para cada uno: qué demuestra, qué resultado se espera, qué casos de `test/casos_pdf.http` lo cubren sobre el seed y qué archivo `.http`/`.sql` específico de módulo lo desarrolla en detalle (`auth.http`, `sesion.http`, `personal.http`, `clientes.http`, `repuestos.http`, `stock.http`, `ordenes.http`, `transiciones.http`, `lecturas_ordenes.http`, `seed.http`, `health.http`, `solo_agregado.sql`, `seed.sql`).
7. **Evidencia del caso C-14 (sólo agregado y clave foránea de estado)**:
   - Comando `psql -h localhost -p 5432 -U taller -d taller -f test/solo_agregado.sql`, enlace a [test/evidencia_c14.txt](test/evidencia_c14.txt) y bloque con los 6 rechazos `P0001`, el rechazo `23503`, el conteo `1 | 1 | 1` y el `ROLLBACK`.
8. **Evidencia del caso C-15 (detalle de una orden con 2 y con 4 ítems sin N+1)**:
   - Explicación de las 5 sentencias `SELECT` fijas (`autenticar` 1 + `get_detalle` 3 + `_roles_vigentes` 1), enlace a [test/evidencia_c15.txt](test/evidencia_c15.txt) y bloque con la salida de `SQL_ECHO=true` de `GET /ordenes/1` (2 ítems) y `GET /ordenes/3` (4 ítems).
9. **Evidencia del caso C-12 (aviso en segundo plano con `BackgroundTasks`)**:
   - Fragmento de la consola de `uvicorn` al terminar la orden #2 (`POST /ordenes/2/terminar` → `200 OK` y, 0,5 s después del commit, `INFO:     Aviso simulado al cliente: la orden #2 del vehículo AD789GH está terminada`).

### D5 — Chequeo de condición bloqueante y script de verificación (`$env:TEMP\verificar_c16.py`)

Un único script temporal `$env:TEMP\verificar_c16.py` (no se versiona) ejecuta de forma reproducible todas las comprobaciones de cierre y genera `test/evidencia_c14.txt`:

- **Bloque (a) — Condición bloqueante: secretos y archivos versionados**:
  - `git ls-files` no contiene `.env` ni ningún `.env.*` (salvo `env.example`); `git check-ignore .env` devuelve `.env` con código 0.
  - `env.example` tiene `POSTGRES_PASSWORD=` y `SECRET_KEY=` vacíos (sin valor tras `=`).
  - `alembic.ini` no contiene `sqlalchemy.url` descomentada, ni `postgresql://`, ni `asyncpg`, ni la contraseña real del `.env` local.
  - Ningún archivo rastreado por `git ls-files` contiene el valor actual de `SECRET_KEY` ni de `POSTGRES_PASSWORD` (cuando tienen más de 8 caracteres y son distintos de nombres de tabla/usuario como `taller`).
- **Bloque (b) — Condición bloqueante: ciclo de migraciones sobre base vacía descartable**:
  - Conectándose con `asyncpg` a la base `postgres` (con las credenciales de `get_settings()`), crea una base vacía descartable `taller_verif_c16` (`DROP DATABASE IF EXISTS taller_verif_c16; CREATE DATABASE taller_verif_c16;`), y en un bloque `try/finally` (que siempre la borra al terminar) ejecuta con `POSTGRES_DB=taller_verif_c16`:
    1. `alembic upgrade head` sobre base vacía → código 0; existen las 13 tablas del dominio, `estado_orden` tiene 0 filas, existen la función `rechazar_cambio_solo_agregado` y los 3 disparadores `trg_solo_agregado`.
    2. `alembic downgrade base` → código 0; quedan 0 tablas del dominio, 0 disparadores y 0 funciones de sólo agregado.
    3. `alembic upgrade head` → código 0; vuelven a estar las 13 tablas y los 3 disparadores.
    4. `alembic check` → código 0 (`No new upgrade operations detected`).
- **Bloque (c) — Evidencia del caso C-14 (`test/solo_agregado.sql` → `test/evidencia_c14.txt`)**:
  - Sobre la base configurada (migrada y sembrada con `python seed.py`), ejecuta `psql` con `-f test/solo_agregado.sql` (usando `PGPASSWORD` en el entorno del subproceso, sin poner credenciales en la línea de comandos ni en el archivo generado), escribe `test/evidencia_c14.txt` con el encabezado de D3 y verifica las 6 líneas `P0001`, la línea `23503` (`fk_orden_trabajo_estado_estado_orden`), la fila `1 | 1 | 1` y `ROLLBACK`, y que los conteos de las 13 tablas del seed (`test/seed.sql`) sigan en `4, 7, 7, 0, 1, 2, 3, 4, 4, 1, 2, 3, 3`.
- **Bloque (d) — Ejecución íntegra de `test/casos_pdf.http` contra `python seed.py`**:
  - Corre `.venv\Scripts\python.exe seed.py` → código 0.
  - Parsea `test/casos_pdf.http` y ejecuta en orden sus 72 peticiones con `httpx.AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test")` dentro de `async with main.lifespan(main.app):`, resolviendo `{{base}}` y `{{<nombre>.response.headers.Set-Cookie}}`, verificando que todas las peticiones lleven `# @no-cookie-jar`, que el código HTTP de cada una coincida con el `# Esperado: <NNN>` de su comentario, que el caso 56 (`POST /ordenes/2/terminar`) emita el registro en `uvicorn.error.avisos` (`Aviso simulado al cliente: la orden #2 del vehículo AD789GH está terminada`), que los casos 62 y 63 (`GET /ordenes/1` de 2 ítems y `GET /ordenes/4` de 4 ítems) emitan exactamente la misma cantidad de sentencias SQL (5 y 5), y que el caso 72 devuelva `429` con cabecera `Retry-After`.
- **Bloque (e) — Verificación de `README.md` y restauración del seed**:
  - Comprueba que `README.md` exista, no esté vacío y contenga las secciones y menciones obligatorias (`python -m venv`, `pip install -r requirements.txt`, `secrets.token_urlsafe`, `alembic upgrade head`, `python seed.py` con la advertencia de que borra/vacía los datos del dominio, `uvicorn main:app`, los tres integrantes, referencias a `C-01`…`C-19`, la evidencia de C-14 con los 6 `P0001` y `23503`, y la evidencia de C-15 con `GET /ordenes/1` y `GET /ordenes/3`).
  - Finalmente vuelve a correr `.venv\Scripts\python.exe seed.py` para dejar la base de desarrollo limpia en el estado inicial del seed.

## Risks / Trade-offs

- [Los archivos `.http` de C-07…C-14 tienen bloques `psql` propios en su encabezado] → Se conservan sin cambios como suites exhaustivas de cada change y se agrega `test/casos_pdf.http` para que quien evalúe el TP pueda correr `python seed.py` y probar todos los casos C-01…C-19 y la matriz RBAC de corrido sin tocar `psql`. `README.md` explica ambos caminos.
- [El caso C-05 (429 por 6 intentos fallidos) bloquea el par `(email, IP)` durante 60 s] → En `test/casos_pdf.http` se ejecuta en la última sección (Sección G) y sobre el usuario nuevo `carlos@cierre.example.com` creado en C-02, de modo que ningún usuario del seed queda bloqueado durante ni después del recorrido.
- [El caso C-18 modifica el precio de `PAS-FRE-DEL` (`32000.00 -> 35000.00`) y el caso C-12 agota el stock de `BUJ-01`] → En `test/casos_pdf.http`, el alta de la orden de 4 ítems (C-15, caso 61) va después y espera `total: "60000.00"` (`8500 + 35000 + 4500 + 12000`); el alta de orden no descuenta ni exige stock (RN13, C-13 S-17), así que crear la orden 4 con `BUJ-01` en stock 0 responde `201`.
- [Idioma de los mensajes de PostgreSQL en `test/evidencia_c14.txt`] → Los mensajes de los 6 rechazos del disparador están definidos en ASCII por nuestra propia migración (`UPDATE rechazado: … es de solo agregado`), y los códigos SQLSTATE (`P0001` y `23503`) y el nombre de la restricción (`fk_orden_trabajo_estado_estado_orden`) son independientes del idioma de la instalación de PostgreSQL.

## Migration Plan

Sin migraciones nuevas ni cambios de código en `app/`. Despliegue = mergear la rama `feat/C-16-verificacion-http-readme` en `main`; rollback = revertir el merge (elimina `README.md`, `test/casos_pdf.http` y `test/evidencia_c14.txt`).

## Open Questions / Supuestos

- **S-01 — Sin delta de specs (`skip_specs: true`).** (A) Declarar `skip_specs: true` en `.openspec.yaml` porque C-16 sólo agrega documentación (`README.md`), casos `.http` integradores y evidencia capturada sin cambiar ningún comportamiento del sistema (como indica la guía de OpenSpec: no inventar requisitos para cambios de documentación/verificación); (B) crear una spec nueva `project-deliverables`. **Recomendado A**.
- **S-02 — Recorrido de C-01…C-19 y matriz RBAC sobre el seed.** (A) Conservar intactos los 11 archivos `.http` existentes de C-01…C-15 y agregar `test/casos_pdf.http` (72 casos ejecutables 100 % por HTTP tras `python seed.py`, sin `psql` intermedio) que recorre la matriz RBAC y los casos PDF C-01…C-19 en orden, mapeando ambos en `README.md`; (B) no crear `test/casos_pdf.http` y documentar en `README.md` únicamente los `.http` existentes con sus pasos manuales de `psql`. **Recomendado A**: cumple literalmente «Antes de cada archivo se corre `python seed.py`» de la pág. 20 del PDF sin perder ninguna prueba de módulo.
- **S-03 — Evidencia de C-14 y C-15.** (A) Generar y versionar `test/evidencia_c14.txt` con la salida de `psql -f test/solo_agregado.sql` (par de `test/evidencia_c15.txt`) y además embeber los fragmentos clave de C-14, C-15 y C-12 directamente en `README.md`; (B) sólo enlazar los archivos de `test/` sin mostrar el fragmento en `README.md`. **Recomendado A**: quien corrige ve las evidencias directamente al abrir el repositorio en GitHub y además tiene los archivos completos en `test/`.
