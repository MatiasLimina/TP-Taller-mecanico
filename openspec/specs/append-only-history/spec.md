# append-only-history Specification

## Purpose

Garantiza en la base de datos que los registros históricos del taller (`historial_estado_orden`, `movimiento_stock`, `historial_precio_repuesto`) sólo admiten altas: nadie, desde ningún cliente ni con ningún rol, puede modificar ni borrar sus filas (RN15), y deja evidencia reproducible del caso C-14.

## Requirements

### Requirement: Filas históricas inmodificables
La base SHALL rechazar todo `UPDATE` sobre filas de `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`, cualquiera sea la columna o el valor asignado, aunque el valor nuevo sea igual al anterior. La fila MUST quedar como estaba y la transacción que lo intentó MUST quedar en error.

#### Scenario: Corregir un cambio de estado
- **WHEN** se ejecuta un `UPDATE` que cambia `hasta_estado` de una fila existente de `historial_estado_orden`
- **THEN** la base rechaza la sentencia y la fila conserva su valor original

#### Scenario: Corregir un movimiento de stock
- **WHEN** se ejecuta un `UPDATE` que cambia `cantidad` de una fila existente de `movimiento_stock`
- **THEN** la base rechaza la sentencia y la fila conserva su valor original

#### Scenario: Corregir un cambio de precio
- **WHEN** se ejecuta un `UPDATE` que cambia `precio_nuevo` de una fila existente de `historial_precio_repuesto`
- **THEN** la base rechaza la sentencia y la fila conserva su valor original

#### Scenario: Actualización sin cambio de valor
- **WHEN** se ejecuta `UPDATE movimiento_stock SET motivo = motivo` sobre una fila existente
- **THEN** la base rechaza la sentencia igual que si cambiara el valor

### Requirement: Filas históricas imborrables
La base SHALL rechazar todo `DELETE` de filas de `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`; las filas MUST seguir existiendo después del intento.

#### Scenario: Borrar un cambio de estado
- **WHEN** se ejecuta un `DELETE` de una fila existente de `historial_estado_orden`
- **THEN** la base rechaza la sentencia y la fila sigue existiendo

#### Scenario: Borrar un movimiento de stock
- **WHEN** se ejecuta un `DELETE` de una fila existente de `movimiento_stock`
- **THEN** la base rechaza la sentencia y la fila sigue existiendo

#### Scenario: Borrar un cambio de precio
- **WHEN** se ejecuta un `DELETE` de una fila existente de `historial_precio_repuesto`
- **THEN** la base rechaza la sentencia y la fila sigue existiendo

#### Scenario: Borrar todas las filas
- **WHEN** se ejecuta `DELETE FROM movimiento_stock` sin condición sobre una tabla con filas
- **THEN** la base rechaza la sentencia y la tabla conserva todas sus filas

### Requirement: Altas permitidas
Las tres tablas SHALL seguir aceptando `INSERT` de filas válidas; la protección de sólo agregado MUST NOT impedir registrar un cambio de estado, un movimiento de stock ni un cambio de precio.

#### Scenario: Registrar en cada tabla
- **WHEN** con las protecciones instaladas se inserta una fila válida en cada una de las tres tablas
- **THEN** las tres filas se guardan

### Requirement: Protección independiente del origen
El rechazo SHALL aplicarse a cualquier sesión que se conecte a la base, incluido el rol dueño de las tablas con el que se conecta la aplicación y un cliente interactivo como psql, sin depender de la aplicación ni de permisos por rol.

#### Scenario: Intento desde psql con el rol de la aplicación
- **WHEN** desde psql, conectado con el mismo rol que usa la aplicación, se intenta un `UPDATE` sobre `historial_precio_repuesto`
- **THEN** la base rechaza la sentencia

#### Scenario: Borrar la orden dueña del historial
- **WHEN** se ejecuta con SQL un `DELETE` de una orden de trabajo que tiene filas en `historial_estado_orden`
- **THEN** la base rechaza el borrado y las filas del historial siguen existiendo

### Requirement: Rechazo identificable y no confundible con un error de datos
El rechazo SHALL informar en su mensaje la tabla y la operación rechazada, y su código de error MUST NOT pertenecer a las clases de violación de integridad (`23`) ni de error de dato (`22`), para que la aplicación no lo traduzca a una respuesta 4xx: un intento de modificar el historial es un defecto del servidor.

#### Scenario: Mensaje del rechazo
- **WHEN** se intenta un `DELETE` sobre `historial_estado_orden`
- **THEN** el error nombra la tabla `historial_estado_orden` y la operación `DELETE`

#### Scenario: Código de error
- **WHEN** se intenta un `UPDATE` sobre cualquiera de las tres tablas
- **THEN** el código SQLSTATE del error no empieza con `22` ni con `23`

#### Scenario: Llega a la API
- **WHEN** una operación de la API provocara un rechazo de sólo agregado
- **THEN** la respuesta es 500 `{"detail": "Error interno del servidor"}` sin texto de PostgreSQL, y el detalle queda sólo en el log

### Requirement: Vaciado completo para recarga
Vaciar por completo las tres tablas con `TRUNCATE` (la operación de mantenimiento que usa la recarga del estado inicial) SHALL seguir permitido; la protección MUST limitarse a modificar o borrar filas.

#### Scenario: Recarga del estado inicial
- **WHEN** con las protecciones instaladas y filas en las tres tablas se ejecuta `TRUNCATE … RESTART IDENTITY CASCADE` sobre las tablas del dominio
- **THEN** las tres tablas quedan vacías sin error y la protección sigue instalada para las filas que se carguen después

### Requirement: Evidencia reproducible del caso C-14
El proyecto SHALL incluir `test/solo_agregado.sql`, ejecutable con psql sobre una base migrada a la última revisión, que muestre seis rechazos de sólo agregado (`UPDATE` y `DELETE` sobre cada una de las tres tablas) y un séptimo rechazo por clave foránea al registrar una orden con un estado que no está en el catálogo. El script MUST NOT dejar filas nuevas en la base.

#### Scenario: Siete rechazos
- **WHEN** se ejecuta `psql -f test/solo_agregado.sql` sobre una base en la última revisión
- **THEN** la salida muestra seis errores de sólo agregado, uno por cada combinación de operación y tabla, y un error de clave foránea por el estado inexistente, cada uno con su resultado esperado anotado en un comentario del script

#### Scenario: Base sin cambios
- **WHEN** se cuentan las filas de todas las tablas del dominio antes y después de ejecutar el script
- **THEN** los conteos son iguales

#### Scenario: Con o sin datos de ejemplo
- **WHEN** el script se ejecuta sobre una base migrada vacía y, por separado, sobre una base que ya tiene catálogo, usuarios, órdenes, repuestos e historiales (como la que deja el seed)
- **THEN** en los dos casos muestra los mismos siete rechazos
