# Proposal — C-16 verificacion-http-readme

## Why

Con C-01…C-15 están implementados y verificados por módulo los 28 endpoints, las 13 tablas, las 2 migraciones de Alembic, el disparador de sólo agregado y `seed.py`, pero faltan los entregables de cierre que exige la consigna (US-070, Flujo 9, págs. 20–22 del PDF): no existe `README.md` con la puesta en marcha desde cero ni las evidencias de los casos C-14 y C-15, varios archivos `.http` de `test/` (escritos antes de que existiera `seed.py` en `main`) requieren sentencias `psql` intermedias en lugar de correr directamente tras `python seed.py` como pide el PDF («Antes de cada archivo se corre `python seed.py`»), falta capturar en un archivo versionado la salida de `test/solo_agregado.sql` (caso C-14, par de `test/evidencia_c15.txt`) y falta ejecutar el chequeo integral de la condición bloqueante de corrección (migraciones sobre base vacía, ciclo `upgrade/downgrade/upgrade` y ausencia de credenciales en el repositorio). Es el último change del roadmap (Fase 6) y todas sus dependencias (`C-06`, `C-09`, `C-14`, `C-15`) ya están en `main`.

## What Changes

- **`README.md` nuevo, en la raíz del repositorio**:
  - Propósito del proyecto, stack tecnológico, arquitectura en capas (`Router → Service → UoW → Repository → Model`), estructura de directorios e integrantes del equipo (`docs/REPARTO_DE_TAREAS.md` §1).
  - Puesta en marcha paso a paso desde cero (Flujo 9, US-070): entorno virtual (`python -m venv .venv`), instalación (`pip install -r requirements.txt` y `requirements-dev.txt`), creación de `.env` desde `env.example` (`Copy-Item env.example .env`, advirtiendo no usar `>` en PowerShell) con generación de `SECRET_KEY` mediante `python -c "import secrets; print(secrets.token_urlsafe(64))"`, migraciones (`alembic upgrade head`), carga inicial con `python seed.py` (**advirtiendo explícitamente que vacía las 13 tablas del dominio con `TRUNCATE … RESTART IDENTITY CASCADE`**, heredado de C-06) y arranque del servidor (`uvicorn main:app --port 8000`, con y sin `SQL_ECHO=true`).
  - Tabla del estado inicial que deja `python seed.py`: los 7 usuarios con sus roles y contraseñas de prueba (`ClaveSegura1` y `Provisoria1` para `nuevo@example.com`), las fichas de cliente (Laura y Jorge), los 3 vehículos, los 4 repuestos y las 2 órdenes iniciales (#1 `PENDIENTE` y #2 `EN_REPARACION` con 4 bujías y stock 2, IN-04).
  - Índice de verificación: tabla que mapea cada caso de la consigna (**C-01 a C-19**) tanto al recorrido unificado sobre el seed (`test/casos_pdf.http`) como al archivo `.http` o `.sql` específico de su módulo (`auth.http`, `sesion.http`, `personal.http`, `clientes.http`, `repuestos.http`, `stock.http`, `ordenes.http`, `transiciones.http`, `lecturas_ordenes.http`, `seed.http`, `health.http`, `solo_agregado.sql`), indicando cuáles corren directo tras `python seed.py` y cuáles llevan su propio bloque de preparación `psql`.
  - Evidencias exigidas por el formato de entrega del PDF:
    - **Caso C-14 (sólo agregado y FK de estado)**: comando `psql -f test/solo_agregado.sql` y fragmento de `test/evidencia_c14.txt` con los seis rechazos `P0001` (`UPDATE` y `DELETE` sobre `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`) y el rechazo `23503` (`fk_orden_trabajo_estado_estado_orden`).
    - **Caso C-15 (detalle de orden sin N+1)**: fragmento de `test/evidencia_c15.txt` (`SQL_ECHO=true` en `GET /ordenes/1` con 2 ítems y `GET /ordenes/3` con 4 ítems: 5 sentencias `SELECT` en ambos casos).
    - **Caso C-12 (aviso en segundo plano)**: línea emitida por `uvicorn.error.avisos` tras confirmar `POST /ordenes/2/terminar`.
  - Comandos para verificar la condición bloqueante (`alembic upgrade head` sobre base vacía, ciclo `upgrade head → downgrade base → upgrade head`, `alembic check` y chequeo de secretos).
- **`test/casos_pdf.http` nuevo**: archivo `.http` autocontenido que se ejecuta **de arriba abajo exclusivamente por HTTP inmediatamente después de `python seed.py`** (sin pasos manuales en `psql` entre peticiones), con `# @no-cookie-jar` en todas las peticiones y respuesta esperada en comentario (`# Esperado: …`):
  - **Sección A**: logins de los 7 usuarios del seed (`admin@`, `admin2@`, `recepcion@`, `mecanico@`, `mecanico2@`, `cliente@`, `nuevo@`).
  - **Sección B — Matriz RBAC end-to-end contra el seed**: verificación de `401` (sin cookie y con `Authorization: Bearer`), `403` por cambio de contraseña pendiente (`nuevo@example.com` bloqueado en el grupo protegido y permitido en `/auth/yo`), y `403` vs `200`/`201`/`204` por rol vigente y por relación de dueño a través de los módulos (`usuarios`/`eventos`, `clientes`/`vehiculos`, `repuestos`/`stock`/`precios`, `ordenes`/`estados-orden`/`mis-ordenes`, incluyendo que `ADMIN` sin `MECANICO` recibe `403` en `POST /ordenes/{id}/iniciar`).
  - **Sección C — Casos de prueba mínimos del PDF (C-01 a C-19, salvo C-14 que es SQL)**: secuencia ordenada sobre los datos del seed que demuestra cada caso de las págs. 20–21 del PDF sin romper las precondiciones de los casos siguientes (C-05 de límite 429 al final sobre la cuenta dedicada del caso para no bloquear sesiones previas).
- **`test/evidencia_c14.txt` nuevo (generado)**: salida capturada de `psql` al ejecutar `test/solo_agregado.sql` contra la base migrada, mostrando los 6 errores `P0001` del disparador `trg_solo_agregado`, el error `23503` de clave foránea de `estado_orden`, la consulta de comprobación `1 | 1 | 1` y el `ROLLBACK` final (sin credenciales ni datos sensibles).
- **Verificación integral de cierre (sin cambios en código de la aplicación)**: comprobación en base descartable del ciclo `alembic upgrade head → downgrade base → upgrade head` y `alembic check`, auditoría de `.gitignore`, `env.example`, `alembic.ini` y archivos versionados para confirmar cero credenciales reales en el repositorio, y corrida de punta a punta de `test/casos_pdf.http` y de los scripts/archivos de `test/` con un script temporal `$env:TEMP\verificar_c16.py` (no versionado).

Fuera de alcance: cambios en `app/**`, `main.py`, `seed.py`, `migrations/**`, `alembic.ini`, `env.example`, `.gitignore` o `requirements*.txt` (salvo que el chequeo de condición bloqueante revelara algún defecto, en cuyo caso se frena y se reporta); reescribir o eliminar los 11 archivos `.http` existentes de C-01…C-15 (se conservan intactos como suites exhaustivas de cada change); agregar `pytest` o nuevas migraciones.

## Capabilities

### New Capabilities
(ninguna — este change no introduce comportamiento nuevo del sistema; `.openspec.yaml` declara `skip_specs: true`)

### Modified Capabilities
(ninguna — los contratos de configuración, migraciones, sólo agregado, seed, seguridad, RBAC y endpoints ya están especificados en las 28 especificaciones vigentes de `openspec/specs/`)

## Impact

- **Archivos nuevos**: `README.md` (raíz), `test/casos_pdf.http`, `test/evidencia_c14.txt`.
- **Sin cambios**: `app/**`, `main.py`, `seed.py`, `migrations/**`, `alembic.ini`, `env.example`, `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `ruff.toml`, y los archivos existentes en `test/` (`health.http`, `seed.http`, `seed.sql`, `auth.http`, `sesion.http`, `personal.http`, `clientes.http`, `repuestos.http`, `stock.http`, `ordenes.http`, `transiciones.http`, `lecturas_ordenes.http`, `solo_agregado.sql`, `evidencia_c15.txt`, `verificar_security_core.py`).
- **Dependencias**: ninguna nueva. Requiere `C-06`, `C-09`, `C-14` y `C-15` en `main` (cumplido).
- **Downstream**: cierra la Fase 6 y el roadmap completo de 16 changes (`CHANGES.md`).
- **Governance**: BAJO (documentación, evidencia y verificación end-to-end sin tocar código de la aplicación). Propone Nico, implementa y cierra Lauti (`docs/REPARTO_DE_TAREAS.md` §3 y §6).
