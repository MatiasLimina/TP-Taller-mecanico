# Actores y Roles

## Actores del sistema
| Actor | Descripción | Cómo interactúa |
|-------|-------------|-----------------|
| ADMIN | Administra personal, roles, catálogo y stock | API autenticada; único que asigna/revoca roles |
| RECEPCION | Da de alta clientes/vehículos y abre órdenes | API autenticada |
| MECANICO | Toma, repara y termina órdenes | API autenticada |
| CLIENTE | Se auto-registra; consulta sus vehículos y órdenes; cancela las suyas | API autenticada (rutas `/mis-*`, cancelar) |
| Visitante | Sin sesión | Health, registro, login |
| SISTEMA | Actor textual en `evento_seguridad` (no es usuario) | Seed / procesos internos |

Un **cliente** (ficha del taller) puede tener o no usuario, y a lo sumo uno (`cliente.usuario_id` UNIQUE nulo). Ej.: Jorge no tiene usuario.

## Roles
- Tabla `asignacion_rol`; `usuario` **no** tiene columna `rol`.
- Roles vigentes = filas no revocadas (`revocada_en IS NULL`) y sin vencer (`vence_en` nulo o futuro).
- Valores: `ADMIN`, `RECEPCION`, `MECANICO`, `CLIENTE` (CHECK).
- Los roles del token son sólo informativos (RN04): la decisión se toma consultando la base en cada petición.

## RBAC — Matriz de permisos (según consigna, leída por extracción)
| Método y ruta | Quién | Códigos |
|---------------|-------|---------|
| GET /health/live, /health/ready | Cualquiera | 200 (/ready también 503) |
| POST /auth/registro | Cualquiera | 201, 409, 422 |
| POST /auth/login | Cualquiera | 200, 401, 422, 429 |
| POST /auth/logout | Cualquiera | 200 |
| GET /auth/yo | Autenticado | 200, 401 |
| POST /auth/cambiar-password | Autenticado | 200, 401, 422 |
| POST /usuarios (alta de personal, contraseña provisoria) | ADMIN | 201, 409, 422 |
| POST /usuarios/{id}/roles | ADMIN | 201, 404, 409, 422 |
| GET /usuarios/{id}/roles | ADMIN | 200, 404 |
| DELETE /usuarios/{id}/roles/{rol} | ADMIN | 200, 404, 409 |
| GET /eventos (page, size) | ADMIN | 200, 422 |
| POST /clientes | RECEPCION, ADMIN | 201, 409, 422 |
| GET /clientes/{id} (con vehículos) | RECEPCION, ADMIN | 200, 404 |
| POST /clientes/{id}/vehiculos | RECEPCION, ADMIN | 201, 404, 409, 422 |
| DELETE /vehiculos/{id} | RECEPCION, ADMIN | 204, 404, 409 |
| GET /mis-vehiculos | Autenticado | 200 |
| GET /repuestos (q, page, size) | ADMIN, RECEPCION, MECANICO | 200, 422 |
| GET /repuestos/{id} | ADMIN, RECEPCION, MECANICO | 200, 404 |
| POST /repuestos (con stock_inicial) | ADMIN | 201, 409, 422 |
| PATCH /repuestos/{id} (descripción y precio) | ADMIN | 200, 404, 422 |
| DELETE /repuestos/{id} | ADMIN | 204, 404 |
| POST /repuestos/{id}/reponer | ADMIN | 200, 404, 422 |
| GET /repuestos/{id}/movimientos | ADMIN | 200, 404 |
| GET /repuestos/{id}/precios (historial) | ADMIN | 200, 404 |
| GET /ordenes (estado, page, size) | RECEPCION, ADMIN, MECANICO | 200, 422 |
| POST /ordenes | RECEPCION, ADMIN | 201, 409, 422 |
| GET /ordenes/{id} | El personal, o el dueño del vehículo | 200, 403, 404 |
| POST /ordenes/{id}/iniciar | MECANICO | 200, 404, 409 |
| POST /ordenes/{id}/terminar | Mecánico asignado, o ADMIN | 200, 403, 404, 409 |
| POST /ordenes/{id}/cancelar | RECEPCION, ADMIN o el dueño | 200, 403, 404, 409 |
| GET /estados-orden (por posición) | Autenticado | 200 |
| GET /mis-ordenes (page, size) | Autenticado | 200, 422 |

> Matriz **validada** contra la tabla "Endpoints de referencia" del PDF (capturas aportadas por el usuario). No existe `GET /usuarios` (listado).

Toda ruta del grupo protegido responde además **401** sin sesión y **403** con el cambio de contraseña pendiente (RN06).

**Cancelar no lleva `requiere_rol`**: el dueño del vehículo no tiene rol de personal. El servicio decide: primero quién es y su relación con la orden (403), luego si el estado lo permite (409) — RN12.

**Transiciones (`iniciar`, `terminar`, `cancelar`)**: un `IdRuta` inválido responde 422. «Mecánico asignado» exige que el rol MECANICO siga vigente (C-14 S-04).

## Rutas públicas / abiertas
- `GET /health/live`, `GET /health/ready`
- `POST /auth/registro`, `POST /auth/login`
- Dentro del grupo "abierto" (permitidas con cambio de contraseña pendiente): `/auth/*` y salud.
