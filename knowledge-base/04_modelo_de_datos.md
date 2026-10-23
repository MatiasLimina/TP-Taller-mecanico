# Modelo de Datos

Los nombres de tablas y columnas son **obligatorios** (los casos de prueba y la corrección los usan). Se pueden agregar columnas, no quitar ni renombrar. Fechas: `timestamptz`. Dinero: `NUMERIC` en base y `Decimal` en Python, nunca `float`. Toda FK lleva índice.

## Dominios
- **usuarios**: `usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`
- **clientes**: `cliente`, `vehiculo`
- **repuestos**: `repuesto`, `movimiento_stock`, `historial_precio_repuesto`
- **ordenes**: `estado_orden` (catálogo), `orden_trabajo`, `item_orden`, `historial_estado_orden`

## ERD
```
usuario 1 ──< asignacion_rol           (usuario_id; otorgada_por → usuario, nulo)
usuario 1 ──0..1 cliente               (cliente.usuario_id UNIQUE, nulo)  [uno a uno opcional]
cliente 1 ──< vehiculo
vehiculo 1 ──< orden_trabajo >── 0..1 usuario (mecanico_id)
estado_orden 1 ──< orden_trabajo.estado / historial.desde_estado / historial.hasta_estado
orden_trabajo 1 ◆──< item_orden >── repuesto      [composición: ítem no existe sin orden]
orden_trabajo 1 ──< historial_estado_orden        (usuario_id)
repuesto 1 ──< movimiento_stock (orden_id nulo, usuario_id)
repuesto 1 ──< historial_precio_repuesto (usuario_id)
intento_acceso, evento_seguridad: sin relaciones
```

## Entidades

### usuario
`id`, `email`, `nombre`, `password_hash`, `activo`, `debe_cambiar_password`, `password_cambiada_en` (nulo permitido). **email UNIQUE.** Sin columna `rol`. `Usuario.cliente` devuelve un objeto (no lista).

### asignacion_rol
`id`, `usuario_id`, `rol`, `desde`, `vence_en` (nulo), `revocada_en` (nulo), `otorgada_por` (nulo). CHECK `rol IN (ADMIN, RECEPCION, MECANICO, CLIENTE)`. **Índice único parcial (usuario_id, rol) WHERE revocada_en IS NULL.** La fila nunca se borra.

### intento_acceso
`id`, `cuando`, `email`, `ip`, `exito`. Índice (`email`, `ip`, `cuando`).

### evento_seguridad
`id`, `cuando`, `actor` (texto, p. ej. `SISTEMA`), `accion`. Sin restricciones extra.

### cliente
`id`, `usuario_id` (nulo), `nombre`, `documento`, `telefono`. **usuario_id UNIQUE; documento UNIQUE.**

### vehiculo
`id`, `cliente_id`, `patente`, `marca`, `modelo`, `anio`, `borrado_en` (nulo). **Índice único parcial (patente) WHERE borrado_en IS NULL; CHECK anio BETWEEN 1950 AND 2100.**

### repuesto
`id`, `codigo`, `descripcion`, `precio` NUMERIC(10,2), `stock`, `borrado_en` (nulo). **Índice único parcial (codigo) WHERE borrado_en IS NULL; CHECK precio > 0; CHECK stock >= 0.**

### estado_orden (catálogo)
`codigo` (PK, texto), `descripcion`, `posicion` (UNIQUE), `es_final`. La migración la crea **vacía**; `seed.py` carga las filas.

### orden_trabajo
`id`, `vehiculo_id`, `mecanico_id` (nulo), `estado` (FK → `estado_orden.codigo`), `falla`, `creada_en`, `total` NUMERIC(12,2). CHECK `total >= 0`.

### item_orden
`id`, `orden_id`, `repuesto_id`, `cantidad`, `precio_unitario` NUMERIC(10,2). CHECK `cantidad > 0`; CHECK `precio_unitario > 0`; **UNIQUE (orden_id, repuesto_id).**

### historial_estado_orden (sólo agregado)
`id`, `orden_id`, `desde_estado` (nulo), `hasta_estado`, `usuario_id`, `cuando`. `desde_estado` y `hasta_estado` son FK a `estado_orden.codigo`.

### movimiento_stock (sólo agregado)
`id`, `repuesto_id`, `orden_id` (nulo), `usuario_id`, `cantidad`, `motivo`, `cuando`. CHECK `cantidad <> 0`.

### historial_precio_repuesto (sólo agregado)
`id`, `repuesto_id`, `usuario_id`, `precio_anterior` NUMERIC(10,2), `precio_nuevo` NUMERIC(10,2), `cuando`. CHECK `precio_nuevo > 0`; CHECK `precio_nuevo <> precio_anterior`.

## Decisiones de modelado
- **Patente y código no son UNIQUE comunes**: borrado lógico + índice único parcial (`WHERE borrado_en IS NULL`) para que el comprador de un auto vendido pueda registrarlo con la misma patente.
- **Roles en su propia tabla**: historial de quién tuvo qué rol y hasta cuándo.
- **Catálogo en lugar de CHECK**: la FK rechaza estados inexistentes; `es_final` define "orden abierta". Un `Enum` en código (contrato de la API, vocabulario del servicio) debe coincidir con las filas del catálogo; agregar un estado exige tocar ambos y el servicio.
- Navegación declarada en **ambos extremos** de cada relación que se lea.

## Seed data inicial (`seed.py`, vacía las tablas y carga; el catálogo primero)
| Qué | Datos |
|-----|-------|
| Catálogo de estados | PENDIENTE (1), EN_REPARACION (2), TERMINADA (3, final), CANCELADA (4, final), cada uno con descripción |
| Usuarios | admin@example.com, admin2@example.com (ADMIN); recepcion@example.com (RECEPCION); mecanico@example.com, mecanico2@example.com (MECANICO); cliente@example.com (CLIENTE); nuevo@example.com (MECANICO, cambio de contraseña obligatorio). Contraseñas de mentira, sólo en `seed.py` |
| Clientes | Laura (con usuario cliente@example.com, dos vehículos); Jorge (sin usuario, un vehículo) |
| Repuestos | Filtro de aceite (stock 10, precio 8500), pastillas de freno delanteras (4, 32000), bujía (2), aceite 5W30 por litro (20, 12000); cada stock cargado como movimiento "Stock inicial" |
| Órdenes | #1 PENDIENTE del primer vehículo de Laura; #2 EN_REPARACION del vehículo de Jorge, asignada a mecanico@example.com, con 4 bujías cuando hay 2 en stock |
| Historial de precios | Una línea del filtro de aceite: 8000 → 8500 |
| Historial de seguridad | Una línea con actor SISTEMA: "Carga de los datos iniciales" |
