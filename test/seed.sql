-- =============================================================================
-- test/seed.sql -- Verificacion en psql del estado inicial (C-06 seed-script)
--
-- Consultas de solo lectura que comprueban que `python seed.py` deja las 13
-- tablas del dominio en el estado exacto de `openspec/changes/c-06-seed-script/design.md` (D6)
-- y que `alembic_version` queda intacta.
--
-- Uso (sobre una base migrada a la ultima revision):
--     psql -d <base> -f test/seed.sql
-- La conexion usa las variables PG* o los parametros de psql (-h, -p, -U);
-- este archivo no contiene credenciales ni modifica datos.
--
-- Cobertura de requisitos (`specs/seed-data` y `specs/security-events`):
--   1.  Recarga completa e idempotente (conteos de las 13 tablas en una fila)
--   2.  Catalogo de estados (`estado_orden`)
--   3.  Usuarios y roles iniciales + Ids deterministas (`usuario` y `asignacion_rol`)
--   4.  Usuarios y roles iniciales (primer ADMIN sin vencimiento: 2 ADMIN vigentes)
--   5.  Correos verificados antes de cargar (todos en minusculas y sin espacios)
--   6.  Usuarios y roles iniciales (hashes bcrypt del costo configurado y distintos)
--   7.  Clientes y vehiculos (`cliente` y `vehiculo` vigentes)
--   8.  Repuestos con stock inicial por movimiento + Stock no descontado
--   9.  Historial de precio inicial (`historial_precio_repuesto` 8000.00 -> 8500.00)
--   10. Ordenes de ejemplo + Ids deterministas (`orden_trabajo` y `total` = suma de items)
--   11. Ordenes de ejemplo (precios copiados y sobreentrega de 4 bujias con stock 2, IN-04)
--   12. Ordenes de ejemplo (`historial_estado_orden` coherente con el estado de cada orden)
--   13. Evento de la carga inicial + Operaciones que dejan evento (`SISTEMA`)
--   14. Recarga completa e idempotente (version del esquema conservada en `alembic_version`)
-- =============================================================================

\set ON_ERROR_STOP on

-- --- 1. Conteos de las 13 tablas del dominio (orden de design D6) ---
-- Esperado: 4 | 7 | 7 | 0 | 1 | 2 | 3 | 4 | 4 | 1 | 2 | 3 | 3
SELECT
    (SELECT count(*) FROM estado_orden)              AS estado_orden,
    (SELECT count(*) FROM usuario)                   AS usuario,
    (SELECT count(*) FROM asignacion_rol)            AS asignacion_rol,
    (SELECT count(*) FROM intento_acceso)            AS intento_acceso,
    (SELECT count(*) FROM evento_seguridad)          AS evento_seguridad,
    (SELECT count(*) FROM cliente)                   AS cliente,
    (SELECT count(*) FROM vehiculo)                  AS vehiculo,
    (SELECT count(*) FROM repuesto)                  AS repuesto,
    (SELECT count(*) FROM movimiento_stock)          AS movimiento_stock,
    (SELECT count(*) FROM historial_precio_repuesto) AS historial_precio_repuesto,
    (SELECT count(*) FROM orden_trabajo)             AS orden_trabajo,
    (SELECT count(*) FROM item_orden)                AS item_orden,
    (SELECT count(*) FROM historial_estado_orden)    AS historial_estado_orden;

-- --- 2. Catalogo de estados (`estado_orden`) ---
-- Esperado:
--   PENDIENTE     | 1 | f | t
--   EN_REPARACION | 2 | f | t
--   TERMINADA     | 3 | t | t
--   CANCELADA     | 4 | t | t
SELECT codigo, posicion, es_final, descripcion <> '' AS con_descripcion
FROM estado_orden
ORDER BY posicion;

-- --- 3. Usuarios y sus asignaciones de rol iniciales ---
-- Esperado:
--   1 | admin@example.com     | t | f | ADMIN     | t | t | NULL
--   2 | admin2@example.com    | t | f | ADMIN     | t | t | NULL
--   3 | recepcion@example.com | t | f | RECEPCION | t | t | NULL
--   4 | mecanico@example.com  | t | f | MECANICO  | t | t | NULL
--   5 | mecanico2@example.com | t | f | MECANICO  | t | t | NULL
--   6 | cliente@example.com   | t | f | CLIENTE   | t | t | NULL
--   7 | nuevo@example.com     | t | t | MECANICO  | t | t | NULL
SELECT
    u.id,
    u.email,
    u.activo,
    u.debe_cambiar_password,
    a.rol,
    a.vence_en IS NULL    AS sin_vence,
    a.revocada_en IS NULL AS abierta,
    a.otorgada_por
FROM usuario u
JOIN asignacion_rol a ON a.usuario_id = u.id
ORDER BY u.id;

-- --- 4. ADMIN vigentes sin vencimiento de usuarios activos (S-06, RN05) ---
-- Esperado: 2
SELECT count(*) AS admins_vigentes_sin_vence
FROM asignacion_rol a
JOIN usuario u ON u.id = a.usuario_id
WHERE a.rol = 'ADMIN'
  AND a.revocada_en IS NULL
  AND a.vence_en IS NULL
  AND u.activo;

-- --- 5. Correos normalizados (minusculas y sin espacios) ---
-- Esperado: 0
SELECT count(*) AS correos_no_normalizados
FROM usuario
WHERE email <> lower(btrim(email));

-- --- 6. Hashes bcrypt con el costo configurado (con otro BCRYPT_COST, cambiar el 12) ---
-- Esperado: hashes_invalidos = 0, hashes_distintos = 7
SELECT count(*) AS hashes_invalidos
FROM usuario
WHERE password_hash NOT LIKE '$2b$12$%';

SELECT count(DISTINCT password_hash) AS hashes_distintos
FROM usuario;

-- --- 7. Clientes y cantidad de vehiculos vigentes ---
-- Esperado:
--   1 | Laura Martínez | 28111222 | 6    | 2
--   2 | Jorge Pérez    | 25111333 | NULL | 1
SELECT
    c.id,
    c.nombre,
    c.documento,
    c.usuario_id,
    count(v.id) AS vehiculos
FROM cliente c
LEFT JOIN vehiculo v ON v.cliente_id = c.id AND v.borrado_en IS NULL
GROUP BY c.id
ORDER BY c.id;

-- --- 8. Repuestos y coherencia con movimientos de stock inicial ---
-- Esperado:
--   1 | FIL-ACE-01  |  8500.00 | 10 | 10 | t
--   2 | PAS-FRE-DEL | 32000.00 |  4 |  4 | t
--   3 | BUJ-01      |  4500.00 |  2 |  2 | t
--   4 | ACE-5W30-1L | 12000.00 | 20 | 20 | t
SELECT
    r.id,
    r.codigo,
    r.precio,
    r.stock,
    coalesce(sum(m.cantidad), 0)                                AS suma_movimientos,
    bool_and(m.motivo = 'Stock inicial' AND m.orden_id IS NULL) AS solo_stock_inicial
FROM repuesto r
LEFT JOIN movimiento_stock m ON m.repuesto_id = r.id
GROUP BY r.id
ORDER BY r.id;

-- --- 9. Historial de precio del filtro de aceite ---
-- Esperado: 1 | 1 | 8000.00 | 8500.00
SELECT repuesto_id, usuario_id, precio_anterior, precio_nuevo
FROM historial_precio_repuesto;

-- --- 10. Ordenes de trabajo y coherencia de su total con la suma de items ---
-- Esperado:
--   1 | 1 | NULL | PENDIENTE     | 56500.00 | 56500.00 | 2
--   2 | 3 |    4 | EN_REPARACION | 18000.00 | 18000.00 | 1
SELECT
    o.id,
    o.vehiculo_id,
    o.mecanico_id,
    o.estado,
    o.total,
    sum(i.cantidad * i.precio_unitario) AS suma_items,
    count(i.id)                         AS items
FROM orden_trabajo o
JOIN item_orden i ON i.orden_id = o.id
GROUP BY o.id
ORDER BY o.id;

-- --- 11. Items de las ordenes (precio copiado y sobreentrega en orden 2, IN-04) ---
-- Esperado:
--   1 | 1 | 1 | t | 10
--   1 | 4 | 4 | t | 20
--   2 | 3 | 4 | t |  2
SELECT
    i.orden_id,
    i.repuesto_id,
    i.cantidad,
    i.precio_unitario = r.precio AS precio_copiado,
    r.stock
FROM item_orden i
JOIN repuesto r ON r.id = i.repuesto_id
ORDER BY i.id;

-- --- 12. Historial de estados de las ordenes ---
-- Esperado:
--   1 | NULL      | PENDIENTE     | 3
--   2 | NULL      | PENDIENTE     | 3
--   2 | PENDIENTE | EN_REPARACION | 4
SELECT orden_id, desde_estado, hasta_estado, usuario_id
FROM historial_estado_orden
ORDER BY id;

-- --- 13. Evento de seguridad de la carga inicial ---
-- Esperado: 1 | SISTEMA | Carga de los datos iniciales | t
SELECT id, actor, accion, cuando IS NOT NULL AS con_cuando
FROM evento_seguridad;

-- --- 14. Version del esquema en Alembic ---
-- Esperado: 9141e6428bad
SELECT version_num
FROM alembic_version;
