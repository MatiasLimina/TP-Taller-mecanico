# Flujos Principales

## Flujo 1: Login (RN08, RN09)
**Disparador:** `POST /auth/login` · **Actor:** cualquiera

1. Router valida contrato (email, password ≤ 72 bytes).
2. Servicio cuenta fallos recientes en `intento_acceso` (mismo email + IP, 60 s, desde el último éxito).
3. Si ≥ 5 → 429 + `Retry-After`, **sin calcular hash**.
4. Busca usuario; verifica bcrypt (`to_thread` + semáforo) contra su hash **o** contra el hash ficticio si no existe.
5. Anota el intento (éxito/fallo) en **sesión y transacción propias**, confirmadas siempre (única escritura fuera del UoW de la petición).
6. Si falló → 401 con mensaje idéntico; si OK → emite JWT (`sub`, `iat` con fracción, `exp`, roles vigentes) y lo pone en cookie HttpOnly.
7. Respuesta: `{mensaje, debe_cambiar_password, expira_en_segundos}`.

```
Cliente → Router → Service → [sesión propia: intento_acceso] 
                         ↘ UoW: usuario + asignacion_rol
                    ← Set-Cookie: access_token (HttpOnly, SameSite=Lax)
```
**Errores:** correo inexistente / contraseña mala → 401 igual; límite → 429; contraseña >72 bytes → 422.

## Flujo 2: Autorización por petición (RN04, RN06, RN07)
1. `get_usuario_actual`: lee `request.cookies`; 401 si falta, inválido, vencido, usuario inexistente/inactivo, o `iat` < `password_cambiada_en` (comparación sin truncar).
2. Control de cambio obligatorio (montado una vez en el grupo protegido): 403 si `debe_cambiar_password`.
3. `requiere_rol(...)`: consulta roles vigentes en base (no revocados, sin vencer); 403 si no coincide.
4. Revocar un rol hace que la siguiente petición con la misma cookie dé 403.

## Flujo 3: Registro (RN02)
`POST /auth/registro` → hash bcrypt **antes** de abrir la transacción → un UoW: inserta `usuario`, `asignacion_rol(CLIENTE)`, `cliente`, `evento_seguridad`. Correo/documento duplicado → `IntegrityError` traducido a 409; rollback completo (sin filas sueltas). Documento ya perteneciente a un cliente existente → 409 (no se apropia la ficha).

## Flujo 4: Alta de orden (RN10, RN19)
`POST /ordenes` (RECEPCION/ADMIN) → DTO sin precio/total/estado → UoW: verifica catálogo no vacío, vehículo vigente, repuestos vigentes; copia `precio_unitario`; calcula `total`; crea orden PENDIENTE + ítems + historial (`null → PENDIENTE`). Repuesto inexistente/baja → 409, nada queda.
- Orden de bloqueos del alta (C-13): vehículo `FOR UPDATE` (lo bloquea también la baja de C-10) → repuestos `FOR SHARE` en orden ascendente de id; los precios se copian dentro de esa transacción.

## Flujo 5: Terminar orden (RN11, RN13, RN14) — C-11, C-12
**Actor:** mecánico asignado o ADMIN

1. Servicio abre UoW; valida permiso (403) y estado EN_REPARACION (409).
2. Para cada ítem: descuenta stock por el **punto único de escritura**; crea `movimiento_stock` (cantidad negativa, `orden_id`).
3. Si algún repuesto no alcanza, el 409 lo decide el `UPDATE` condicional del punto único de escritura (C-11), no un CHECK `stock >= 0` aparte → rollback total. Orden de bloqueos: orden `FOR UPDATE` primero, luego repuestos en orden ascendente de id.
4. Cambia estado a TERMINADA + línea en `historial_estado_orden`.
5. Commit al salir del bloque; recién entonces se agenda `BackgroundTasks` (aviso simulado `sleep(0.5)` + log), que corre tras enviar la respuesta.

## Flujo 6: Cancelar orden (RN12) — C-13
1. Identificar al actor y su relación con la orden (personal con rol vigente o dueño del vehículo: el usuario del cliente al que pertenece el vehículo, aun si el vehículo está dado de baja, C-14 S-08) → 403 si no. Orden inexistente → 404 antes que 403 para una orden ajena (S-07).
2. Recién después, estado PENDIENTE → CANCELADA; otro estado → 409.
3. Historial de estado.

## Flujo 7: Cambio de precio de repuesto (RN20) — C-18
`PATCH /repuestos/{id}` (ADMIN) con `exclude_unset` → un UoW: si el precio cambió, actualiza y agrega `historial_precio_repuesto`; si no cambió, sin línea. Un `stock` en el cuerpo → 422 (`extra=forbid`).

## Flujo 8: Cambio obligatorio de contraseña (RN06, RN07) — C-09
Usuario `nuevo@example.com` hace login → `debe_cambiar_password=true` → toda ruta protegida da 403 → `POST /auth/cambiar-password` (hash fuera del bucle y antes de la transacción) → actualiza hash, `password_cambiada_en`, baja la bandera → emite cookie nueva (válida) → la cookie anterior da 401.

## Flujo 9: Puesta en marcha
`python -m venv` → `pip install -r requirements.txt` → `.env` (con clave de firma generada) → `alembic upgrade head` (2 migraciones) → `python seed.py` → `uvicorn main:app`.
