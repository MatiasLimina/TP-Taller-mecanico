# Decisiones y Supuestos

## Decisiones documentadas (impuestas por la consigna)

### DD-01 — Catálogo `estado_orden` en lugar de CHECK
**Decisión:** estados como filas con PK `codigo`, FK desde orden e historial. **Contexto:** la lista es dato y lleva atributos (`es_final`, `posicion`). **Alternativas:** CHECK con lista. **Justificación:** consultable, extensible, `es_final` decide "orden abierta". **Trade-offs:** enum en código y catálogo deben mantenerse sincronizados; migración crea tabla vacía y `seed.py` la carga (sin seed no hay órdenes → 409).

### DD-02 — Unicidad parcial para patente y código
**Decisión:** índice único parcial `WHERE borrado_en IS NULL`. **Alternativa:** UNIQUE común (bloquea re-registro). **Trade-off:** la unicidad sólo rige entre vigentes.

### DD-03 — Roles en tabla propia, decididos en cada petición
**Decisión:** `asignacion_rol` con vigencia y revocación; el token trae roles sólo informativos. **Justificación:** revocar surte efecto sin esperar al vencimiento del token. **Trade-off:** una consulta extra por petición.

### DD-04 — Cookie HttpOnly y no Bearer
**Decisión:** token sólo en cookie; nunca en cuerpo ni `Authorization`. **Justificación:** inaccesible a JS. **Trade-off:** SameSite=Lax; `Secure` configurable.

### DD-05 — `iat` sin truncar
**Decisión:** comparar `iat` con `password_cambiada_en` con fracciones de segundo. **Justificación:** evitar que sesiones del mismo segundo anteriores al cambio sigan valiendo (RN07).

### DD-06 — Hash antes de la transacción
**Decisión:** bcrypt (~300 ms) se calcula antes de abrir el UoW. **Justificación:** no retener conexión sin usarla.

### DD-07 — Intento de acceso en sesión propia
**Decisión:** única escritura fuera del UoW de la petición. **Justificación:** el fallo contado es el mismo que haría rollback. **Costo declarado en comentario:** deja filas aunque la petición falle.

### DD-08 — Trigger como mecanismo de sólo agregado
**Decisión:** trigger por migración manual. **Alternativa:** rol de base sin permisos (descrito en 6.9, no pedido). **Nota:** cualquiera de los dos alcanza; ambos = defensa en profundidad.

### DD-09 — Cancelar sin `requiere_rol`
**Decisión:** la decisión la toma el servicio (403 por relación, luego 409 por estado), porque el dueño no tiene rol de personal.

### DD-10 — Aviso con `BackgroundTasks`
**Decisión:** simulado, en el mismo proceso, sólo tras commit. **Riesgo aceptado:** se pierde si el proceso se reinicia; sin reintento (se resuelve en cap. 8). El aviso se registra con el logger `uvicorn.error.avisos` a nivel INFO, porque el proyecto no configura logging (C-14 S-13).

### DD-11 — Concurrencia diferida
**Decisión:** la consigna no evalúa concurrencia (cap. 7), pero la actualización perdida de stock **queda evitada** (C-11, S-02): el punto único de escritura aplica cada movimiento con un `UPDATE` atómico condicional (`stock + :delta >= 0 … RETURNING`), en orden ascendente de `repuesto_id`, sin bloqueo explícito ni reintentos. Dos órdenes simultáneas no descuentan sobre el mismo valor leído; si el stock no alcanza, 409 propio y rollback total. *(Antes: se aceptaba la actualización perdida.)* El alta de órdenes (C-13) se serializa con la baja de vehículos y de repuestos por bloqueos de fila en un orden global (orden → vehículo → repuestos por id), sin interbloqueos. Las transiciones de orden (C-14) se serializan con el bloqueo `FOR UPDATE` sobre la fila de la orden, tomado primero.

## Supuestos inferidos

### SU-01 — Nombres de variables de entorno (RESUELTO: se mantienen los propuestos)
**Supuesto:** además de `POSTGRES_*` y `SQL_ECHO`, los nombres (`SECRET_KEY`, `BCRYPT_COST`, etc.) son libres. **Origen:** la consigna sólo exige que existan y que la clave no tenga default. **Riesgo:** correcciones automáticas que esperen otros nombres. **Validar:** confirmar con la cátedra.

### SU-02 — Columnas de `cliente` y `usuario`
**Supuesto:** `cliente` = `id, usuario_id, nombre, documento, telefono` (la extracción del PDF desordenó la tabla). **Origen:** columnas listadas en la tabla de restricciones. **Riesgo:** diferencias menores. **Validar:** releer el PDF original.

### SU-03 — Códigos HTTP por endpoint (RESUELTO)
La matriz de `03` fue validada contra la tabla del PDF aportada por el usuario.

### SU-04 — Cantidad de movimiento de salida (RESUELTO: con signo, SUM(cantidad) = stock)
**Supuesto:** las salidas por terminación guardan `cantidad` negativa (CHECK `cantidad <> 0` permite ambos signos). **Origen:** "salida" + CHECK `<> 0`. **Riesgo:** convención distinta en el motivo/seed.

### SU-05 — Defaults de configuración (RESUELTO)
Token 1800 s, BCRYPT_COST 12, BCRYPT_MAX_CONCURRENCY 4, POOL_SIZE 5, MAX_OVERFLOW 10, COOKIE_SECURE=false (dev). Todos configurables por entorno.

### SU-06 — Idioma
**Supuesto:** mensajes de error y nombres de dominio en español (la consigna lo está), código en snake_case.

### SU-07 — Historiales por repuesto sin paginar (C-12, S-05)
**Supuesto:** `GET /repuestos/{id}/movimientos` y `GET /repuestos/{id}/precios` devuelven la lista completa, sin `page`/`size`. **Origen:** la consigna sólo pagina `/eventos`, `/repuestos`, `/ordenes` y `/mis-ordenes`. **Riesgo:** respuestas grandes en un repuesto muy usado (en un taller, decenas de filas). **Validar:** si creciera, agregar paginación sin romper la ruta.

### SU-08 — Orden cronológico de los historiales (C-12, S-06)
**Supuesto:** los historiales van por `id` ascendente (el más antiguo primero): la suma de movimientos llega al stock actual y las líneas de precio quedan encadenadas `anterior → nuevo`. **Origen:** lectura de libro de movimientos. **Riesgo:** ninguno funcional; distinto orden que `/eventos`.
