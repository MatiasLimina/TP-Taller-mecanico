-- =============================================================================
-- test/solo_agregado.sql -- Evidencia del caso C-14 (RN15, Ej.7 de la consigna)
--
-- Demuestra que la base rechaza UPDATE y DELETE sobre las tres tablas de solo
-- agregado (historial_estado_orden, movimiento_stock, historial_precio_repuesto)
-- y que una orden con un estado inexistente es rechazada por la clave foranea.
--
-- Uso (sobre una base migrada a la ultima revision, con o sin datos de ejemplo):
--     psql -d <base> -f test/solo_agregado.sql
-- La conexion usa las variables PG* o los parametros de psql (-h, -p, -U);
-- este archivo no contiene credenciales.
--
-- Todo ocurre dentro de una transaccion que termina en ROLLBACK: no deja filas
-- en la base (las filas de solo agregado, una vez confirmadas, ya no se podrian
-- borrar). Se esperan SEIS errores P0001 (disparador) y UNO 23503 (clave foranea).
-- =============================================================================

\set ON_ERROR_STOP off
\set ON_ERROR_ROLLBACK on
\set VERBOSITY verbose
\set ECHO all

BEGIN;

-- --- Datos propios del script (valores unicos; el catalogo convive con el seed) ---
INSERT INTO estado_orden (codigo, descripcion, posicion, es_final) VALUES
    ('SA_ORIGEN',  'Estado de prueba origen',  9001, false),
    ('SA_DESTINO', 'Estado de prueba destino', 9002, false)
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO usuario (email, nombre, password_hash)
VALUES ('solo-agregado@example.test', 'Prueba solo agregado', 'sin-hash-de-prueba')
RETURNING id AS usuario_id \gset

INSERT INTO cliente (usuario_id, nombre, documento, telefono)
VALUES (:usuario_id, 'Cliente de prueba', 'SOLO-AGREGADO-DOC', '0000')
RETURNING id AS cliente_id \gset

INSERT INTO vehiculo (cliente_id, patente, marca, modelo, anio)
VALUES (:cliente_id, 'SOLOAG1', 'Marca', 'Modelo', 2020)
RETURNING id AS vehiculo_id \gset

INSERT INTO orden_trabajo (vehiculo_id, estado, falla, total)
VALUES (:vehiculo_id, 'SA_ORIGEN', 'Prueba de solo agregado', 0)
RETURNING id AS orden_id \gset

INSERT INTO repuesto (codigo, descripcion, precio, stock)
VALUES ('SOLO-AGREGADO-REP', 'Repuesto de prueba', 100.00, 10)
RETURNING id AS repuesto_id \gset

-- INSERT esta permitido en las tres tablas de solo agregado:
INSERT INTO historial_estado_orden (orden_id, desde_estado, hasta_estado, usuario_id)
VALUES (:orden_id, NULL, 'SA_ORIGEN', :usuario_id)
RETURNING id AS historial_estado_id \gset

INSERT INTO movimiento_stock (repuesto_id, orden_id, usuario_id, cantidad, motivo)
VALUES (:repuesto_id, :orden_id, :usuario_id, 5, 'ajuste de prueba')
RETURNING id AS movimiento_id \gset

INSERT INTO historial_precio_repuesto (repuesto_id, usuario_id, precio_anterior, precio_nuevo)
VALUES (:repuesto_id, :usuario_id, 100.00, 120.00)
RETURNING id AS historial_precio_id \gset

-- --- 1. historial_estado_orden ---
-- Esperado: ERROR P0001 -- "UPDATE rechazado: historial_estado_orden es de solo agregado"
UPDATE historial_estado_orden SET hasta_estado = 'SA_DESTINO' WHERE id = :historial_estado_id;

-- Esperado: ERROR P0001 -- "DELETE rechazado: historial_estado_orden es de solo agregado"
DELETE FROM historial_estado_orden WHERE id = :historial_estado_id;

-- --- 2. movimiento_stock ---
-- Esperado: ERROR P0001 -- "UPDATE rechazado: movimiento_stock es de solo agregado"
UPDATE movimiento_stock SET cantidad = 99 WHERE id = :movimiento_id;

-- Esperado: ERROR P0001 -- "DELETE rechazado: movimiento_stock es de solo agregado"
DELETE FROM movimiento_stock WHERE id = :movimiento_id;

-- --- 3. historial_precio_repuesto ---
-- Esperado: ERROR P0001 -- "UPDATE rechazado: historial_precio_repuesto es de solo agregado"
UPDATE historial_precio_repuesto SET precio_nuevo = 130.00 WHERE id = :historial_precio_id;

-- Esperado: ERROR P0001 -- "DELETE rechazado: historial_precio_repuesto es de solo agregado"
DELETE FROM historial_precio_repuesto WHERE id = :historial_precio_id;

-- --- 4. Clave foranea: orden con un estado que no esta en el catalogo ---
-- Esperado: ERROR 23503 -- violacion de fk_orden_trabajo_estado_estado_orden
INSERT INTO orden_trabajo (vehiculo_id, estado, falla, total)
VALUES (:vehiculo_id, 'INEXISTENTE', 'Estado fuera del catalogo', 0);

-- Las tres filas siguen intactas despues de los rechazos (cada conteo debe ser 1):
SELECT
    (SELECT count(*) FROM historial_estado_orden    WHERE id = :historial_estado_id)  AS historial_estado_orden,
    (SELECT count(*) FROM movimiento_stock          WHERE id = :movimiento_id)        AS movimiento_stock,
    (SELECT count(*) FROM historial_precio_repuesto WHERE id = :historial_precio_id)  AS historial_precio_repuesto;

-- Ninguna fila de lo anterior queda en la base (las secuencias de identidad si avanzan):
ROLLBACK;
