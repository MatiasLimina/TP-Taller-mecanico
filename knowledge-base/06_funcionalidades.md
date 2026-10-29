# Funcionalidades

Organizadas por épica. Los criterios derivan de los ejercicios y casos de prueba (C-xx) de la consigna.

## Épica 1: Proyecto y ciclo de vida (Ej.1)
### US-001 — Configuración segura
**Como** desarrollador **quiero** `Settings` (pydantic-settings) desde entorno/.env **para** no versionar secretos.
- [ ] URL de base armada con `@computed_field` desde `POSTGRES_*`
- [ ] Clave de firma y password de base sin default: si faltan, la app no arranca
- [ ] `env.example` completo y sin secretos; costo de bcrypt y tamaño de pool en Settings
**Reglas:** requisitos no funcionales

### US-002 — Lifespan y salud
- [ ] Motor + fábrica en lifespan → `app.state`; `get_session` con `expire_on_commit=False`; `dispose()` al apagar; hash ficticio calculado una vez
- [ ] `GET /health/live` sin tocar la base; `GET /health/ready` hace `SELECT 1` y da 503 si falla

## Épica 2: Autenticación (Ej.4)
### US-010 — Registro (RN02) — C-02
- [ ] 201; correo o documento repetido → 409 sin filas sueltas
### US-011 — Login con cookie (RN08, RN09) — C-03, C-04, C-05
- [ ] Orden: límite de intentos (429 + Retry-After, sin hash) → verificación (hash real o ficticio)
- [ ] Cookie `access_token` HttpOnly, SameSite=Lax, Max-Age = duración, Secure configurable; cuerpo sin token
- [ ] Cada intento se anota en `intento_acceso` en sesión/transacción propia
### US-012 — Logout, `/auth/yo`, cambio de contraseña (RN07) — C-09
- [ ] Logout borra la cookie; `/auth/yo` devuelve usuario, roles vigentes y roles del token
- [ ] Cambio invalida sesiones anteriores; la nueva cookie vale

## Épica 3: Autorización y personal (Ej.5)
### US-020 — Roles con vigencia (RN03–RN05) — C-07, C-08
- [ ] Asignar con vencimiento opcional (tz-aware y futuro, si no 422); revocar sin borrar; reasignar rol vencido cierra la fila previa y abre otra
- [ ] Autoprotección: ADMIN no se revoca, nunca 0 admins (409)
### US-021 — Alta de personal y eventos
- [ ] `POST /usuarios` con contraseña provisoria (`debe_cambiar_password`); `GET /eventos` paginado
- [ ] `evento_seguridad` registra altas, cambios de rol/contraseña y datos iniciales (actor SISTEMA)
### US-022 — 401 vs 403 y cambio obligatorio (RN04, RN06) — C-06, C-09
- [ ] 401: sin cookie / token inválido o vencido / usuario inexistente o inactivo / token anterior al cambio de contraseña
- [ ] 403: sin rol vigente; cambio pendiente fuera de `/auth` y salud

## Épica 4: Clientes y vehículos
### US-030 — Alta de clientes y vehículos (RN01) — C-19
- [ ] `POST /clientes`, `GET /clientes/{id}` con vehículos, `POST /clientes/{id}/vehiculos`
- [ ] `DELETE /vehiculos/{id}` → 204 (baja lógica); 409 con órdenes abiertas (RN16); misma patente reutilizable tras la baja; patente vigente repetida → 409
### US-031 — Consulta propia (RN17)
- [ ] `GET /mis-vehiculos`

## Épica 5: Repuestos y stock
### US-040 — Catálogo de repuestos (Ej.3) — C-16
- [ ] `GET /repuestos?q&page&size` con búsqueda por descripción **o código** (C-11, S-08) con parámetros ligados (`' OR '1'='1` → lista vacía)
- [ ] `POST` con `stock_inicial` (genera movimiento "Stock inicial"); `PATCH` sólo descripción y precio (stock → 422; si cambia el precio, línea de historial — RN20, C-11); `DELETE` lógico
### US-041 — Reposición y movimientos (RN14)
- [ ] `POST /repuestos/{id}/reponer`; `GET /repuestos/{id}/movimientos`
### US-042 — Historial de precios (RN20) — C-18
- [ ] Cambio de precio crea línea (anterior/nuevo) en la misma transacción; PATCH de sólo descripción no crea línea; RECEPCION → 403

## Épica 6: Órdenes de trabajo
### US-050 — Alta de orden (RN10, RN19) — C-10
- [ ] Cuerpo `{vehiculo_id, falla, items[{repuesto_id, cantidad}]}`; respuesta con precios copiados, total y primer historial
- [ ] Repuesto inexistente → 409 y no queda orden; catálogo vacío → 409 propio
### US-051 — Iniciar / terminar / cancelar (RN11–RN13) — C-11, C-12, C-13
- [ ] Iniciar (mecánico queda asignado); terminar descuenta stock + movimientos + historial atómicamente; falta de stock → 409 sin cambios; aviso por `BackgroundTasks` sólo si hubo commit
- [ ] Cancelar: dueño / recepción / admin; 403 antes que 409; ajena → 403; terminada → 409
### US-052 — Lecturas (RN17) — C-15, C-17
- [ ] `GET /ordenes?estado`, `GET /ordenes/{id}` (vehículo, cliente, ítems, repuesto, historial) con **número fijo de consultas** (2 vs 4 ítems → mismas consultas); `GET /estados-orden`; `GET /mis-ordenes`; estado inválido en filtro → 422

## Épica 7: Integridad en base (Ej.7) — C-14
### US-060 — Sólo agregado
- [ ] Trigger rechaza UPDATE/DELETE en las tres tablas (seis rechazos en psql + FK por estado inexistente); `test/solo_agregado.sql`

## Épica 8: Entregables y pruebas
### US-070 — Migraciones y semillas
- [ ] Migración 1 `--autogenerate`; migración 2 manual (trigger) con comentario de revisión; `upgrade head` → `downgrade base` → `upgrade head`
- [ ] `seed.py` idempotente de estado inicial; README con pasos desde cero (incluye generar la clave de firma)
- [ ] `.http` en `test/` para C-01…C-19 con respuesta esperada en comentario; evidencia C-14 y C-15
