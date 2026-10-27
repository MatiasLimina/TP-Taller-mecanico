# domain-data-model Specification

## Purpose
Define el esquema relacional del dominio del taller (usuarios y roles, clientes y vehículos, repuestos y stock, órdenes y su catálogo de estados): qué tablas y columnas existen, qué garantiza la base por sí misma (unicidad, CHECKs, claves foráneas, tipos exactos) y cómo se navega entre entidades sin carga perezosa.

## Requirements

### Requirement: Tablas y columnas obligatorias
El esquema SHALL contener exactamente las 13 tablas del dominio con los nombres de la consigna (`usuario`, `asignacion_rol`, `intento_acceso`, `evento_seguridad`, `cliente`, `vehiculo`, `repuesto`, `movimiento_stock`, `historial_precio_repuesto`, `estado_orden`, `orden_trabajo`, `item_orden`, `historial_estado_orden`) y, en cada una, todas las columnas obligatorias con su nombre exacto. Se pueden agregar columnas; ninguna obligatoria se omite ni se renombra.

#### Scenario: Tablas presentes tras migrar
- **WHEN** se aplica el esquema sobre una base vacía y se listan las tablas del esquema público
- **THEN** aparecen las 13 tablas del dominio (además de la tabla de versión de Alembic) y ninguna otra

#### Scenario: Columnas de orden_trabajo
- **WHEN** se inspecciona la tabla `orden_trabajo`
- **THEN** tiene las columnas `id`, `vehiculo_id`, `mecanico_id`, `estado`, `falla`, `creada_en` y `total`

#### Scenario: Usuario sin columna de rol
- **WHEN** se inspecciona la tabla `usuario`
- **THEN** tiene `id`, `email`, `nombre`, `password_hash`, `activo`, `debe_cambiar_password` y `password_cambiada_en`, y no tiene ninguna columna `rol`

### Requirement: Fechas con zona horaria
Toda columna de fecha y hora del dominio SHALL ser `timestamp with time zone` y conservar fracciones de segundo; el modelo MUST entregar y aceptar valores con zona horaria, nunca fechas sin zona.

#### Scenario: Tipo de las columnas de fecha
- **WHEN** se inspeccionan `usuario.password_cambiada_en`, `asignacion_rol.desde`, `asignacion_rol.vence_en`, `asignacion_rol.revocada_en`, `intento_acceso.cuando`, `evento_seguridad.cuando`, `vehiculo.borrado_en`, `repuesto.borrado_en`, `orden_trabajo.creada_en` y las columnas `cuando` de los historiales y movimientos
- **THEN** todas son `timestamp with time zone`

#### Scenario: Fracciones de segundo conservadas
- **WHEN** se guarda en `usuario.password_cambiada_en` un instante con microsegundos y se lo vuelve a leer
- **THEN** el valor leído es igual al guardado, con zona horaria y sin truncar

### Requirement: Dinero exacto
Las columnas de dinero SHALL ser numéricas exactas: `repuesto.precio`, `item_orden.precio_unitario`, `historial_precio_repuesto.precio_anterior` y `precio_nuevo` `NUMERIC(10,2)`, y `orden_trabajo.total` `NUMERIC(12,2)`; en el modelo MUST representarse como decimales exactos, nunca como punto flotante.

#### Scenario: Tipo de las columnas de dinero
- **WHEN** se inspeccionan las columnas de dinero
- **THEN** son `numeric(10,2)` salvo `orden_trabajo.total`, que es `numeric(12,2)`

#### Scenario: Valor exacto
- **WHEN** se guarda un repuesto con precio `0.10 + 0.20` calculado en decimal exacto y se lo vuelve a leer
- **THEN** el precio leído es exactamente `0.30`

### Requirement: Unicidad común
La base SHALL rechazar duplicados de `usuario.email`, `cliente.documento`, `cliente.usuario_id`, `estado_orden.posicion` y del par `item_orden(orden_id, repuesto_id)`, sin consulta previa de la aplicación (RN01). `cliente.usuario_id` MUST admitir varios clientes sin usuario.

#### Scenario: Correo repetido
- **WHEN** se inserta un segundo usuario con el mismo `email` que uno existente
- **THEN** la base rechaza la escritura con una violación de unicidad

#### Scenario: Dos clientes sin usuario
- **WHEN** se insertan dos clientes con `usuario_id` nulo y documentos distintos
- **THEN** ambas filas se guardan

#### Scenario: Usuario con dos fichas de cliente
- **WHEN** se inserta un segundo cliente con el mismo `usuario_id` no nulo que otro
- **THEN** la base rechaza la escritura con una violación de unicidad

#### Scenario: Repuesto repetido en una orden
- **WHEN** se insertan dos ítems de la misma orden con el mismo `repuesto_id`
- **THEN** la base rechaza el segundo con una violación de unicidad

### Requirement: Unicidad parcial entre vigentes
La base SHALL garantizar unicidad sólo entre filas vigentes mediante índices únicos parciales: `asignacion_rol(usuario_id, rol)` donde `revocada_en` es nulo (RN03), `vehiculo(patente)` y `repuesto(codigo)` donde `borrado_en` es nulo (RN01, DD-02). Las filas revocadas o dadas de baja MUST NOT impedir una nueva fila con los mismos valores.

#### Scenario: Patente de un vehículo vigente
- **WHEN** se inserta un vehículo con la patente de otro vehículo sin baja
- **THEN** la base rechaza la escritura con una violación de unicidad

#### Scenario: Patente de un vehículo dado de baja
- **WHEN** un vehículo tiene `borrado_en` con valor y se inserta otro vehículo con la misma patente
- **THEN** la fila nueva se guarda y la dada de baja sigue en la tabla

#### Scenario: Código de repuesto reutilizado tras la baja
- **WHEN** un repuesto tiene `borrado_en` con valor y se inserta otro con el mismo código
- **THEN** la fila nueva se guarda; un tercero con ese código y sin baja es rechazado

#### Scenario: Rol abierto duplicado
- **WHEN** un usuario tiene una asignación de MECANICO con `revocada_en` nulo y se inserta otra asignación de MECANICO para él
- **THEN** la base rechaza la escritura con una violación de unicidad

#### Scenario: Rol reasignado tras revocar
- **WHEN** la asignación de MECANICO de un usuario tiene `revocada_en` con valor y se inserta una nueva asignación de MECANICO para él
- **THEN** la fila nueva se guarda y la revocada se conserva

### Requirement: Restricciones CHECK
La base SHALL rechazar: `asignacion_rol.rol` fuera de ADMIN, RECEPCION, MECANICO, CLIENTE; `vehiculo.anio` fuera de 1950–2100; `repuesto.precio` ≤ 0 y `stock` < 0; `orden_trabajo.total` < 0; `item_orden.cantidad` ≤ 0 y `precio_unitario` ≤ 0; `movimiento_stock.cantidad` = 0; `historial_precio_repuesto.precio_nuevo` ≤ 0 o igual a `precio_anterior`.

#### Scenario: Rol inexistente
- **WHEN** se inserta una asignación con rol `SUPERVISOR`
- **THEN** la base rechaza la escritura con una violación de CHECK

#### Scenario: Año en los límites
- **WHEN** se insertan vehículos con `anio` 1950 y 2100, y luego uno con 1949
- **THEN** los dos primeros se guardan y el tercero es rechazado con una violación de CHECK

#### Scenario: Stock negativo
- **WHEN** se actualiza el `stock` de un repuesto a -1
- **THEN** la base rechaza la escritura con una violación de CHECK

#### Scenario: Movimiento nulo
- **WHEN** se inserta un movimiento de stock con `cantidad` 0
- **THEN** la base rechaza la escritura; con `cantidad` -4 o 10 se guarda

#### Scenario: Precio sin cambio en el historial
- **WHEN** se inserta una línea de historial de precios con `precio_anterior` 8500 y `precio_nuevo` 8500
- **THEN** la base rechaza la escritura con una violación de CHECK

### Requirement: Catálogo de estados por clave foránea
Los estados de una orden SHALL ser filas de `estado_orden` (PK `codigo` de texto, `descripcion`, `posicion` única, `es_final`); `orden_trabajo.estado`, `historial_estado_orden.desde_estado` (nulo permitido) y `hasta_estado` MUST ser claves foráneas a `estado_orden.codigo`, sin `CHECK` con la lista de estados (RN19, DD-01).

#### Scenario: Estado inexistente
- **WHEN** se inserta una orden con `estado` `INEXISTENTE`
- **THEN** la base rechaza la escritura con una violación de clave foránea

#### Scenario: Catálogo vacío
- **WHEN** el catálogo no tiene filas y se inserta una orden con estado `PENDIENTE`
- **THEN** la base rechaza la escritura con una violación de clave foránea

#### Scenario: Primer historial sin estado previo
- **WHEN** con el catálogo cargado se inserta una línea de historial con `desde_estado` nulo y `hasta_estado` `PENDIENTE`
- **THEN** la fila se guarda

#### Scenario: Sin CHECK de estados
- **WHEN** se listan las restricciones CHECK de `orden_trabajo` y `historial_estado_orden`
- **THEN** ninguna contiene la lista de códigos de estado

### Requirement: Integridad referencial del dominio
Cada referencia entre tablas del ERD SHALL ser una clave foránea; las columnas de referencia opcionales (`asignacion_rol.otorgada_por`, `cliente.usuario_id`, `orden_trabajo.mecanico_id`, `movimiento_stock.orden_id`, `historial_estado_orden.desde_estado`) MUST admitir nulo y las demás MUST NOT. Borrar una fila referenciada MUST fallar salvo en la composición orden–ítem.

#### Scenario: Vehículo de un cliente inexistente
- **WHEN** se inserta un vehículo con un `cliente_id` que no existe
- **THEN** la base rechaza la escritura con una violación de clave foránea

#### Scenario: Borrar un repuesto usado
- **WHEN** se intenta borrar físicamente un repuesto que tiene ítems de orden o movimientos
- **THEN** la base rechaza el borrado con una violación de clave foránea

#### Scenario: Orden sin mecánico
- **WHEN** se inserta una orden con `mecanico_id` nulo
- **THEN** la fila se guarda

### Requirement: Composición orden–ítem
Un ítem SHALL existir sólo dentro de su orden: `item_orden.orden_id` MUST NOT ser nulo, y eliminar una orden MUST eliminar sus ítems, tanto al borrar desde el modelo como directamente en la base. Quitar un ítem de la colección de su orden MUST eliminarlo.

#### Scenario: Ítem sin orden
- **WHEN** se inserta un ítem con `orden_id` nulo
- **THEN** la base rechaza la escritura con una violación de NOT NULL

#### Scenario: Borrado de la orden en la base
- **WHEN** se borra con SQL una orden que tiene dos ítems y ningún historial ni movimiento
- **THEN** los dos ítems dejan de existir

#### Scenario: Ítem quitado de la orden
- **WHEN** desde el modelo se quita un ítem de la colección de ítems de una orden precargada y se confirma
- **THEN** la fila del ítem ya no existe

### Requirement: Índice en cada clave foránea
Toda columna con clave foránea SHALL tener un índice cuya primera columna sea ella (propio o como prefijo de un índice único). La tabla `intento_acceso` MUST tener un índice `(email, ip, cuando)` para el conteo de intentos (RN08).

#### Scenario: Claves foráneas indexadas
- **WHEN** se cruzan las claves foráneas del esquema con sus índices
- **THEN** cada columna de clave foránea es la primera columna de al menos un índice no parcial

#### Scenario: Índice de intentos
- **WHEN** se inspeccionan los índices de `intento_acceso`
- **THEN** existe uno sobre `(email, ip, cuando)` en ese orden

### Requirement: Nombres de restricción estables
Toda restricción e índice del esquema SHALL tener un nombre determinista derivado de la tabla y sus columnas (o de un nombre declarado), igual en cada base generada desde las migraciones, para que una operación asocie una violación concreta a su mensaje propio. La unicidad del correo MUST llamarse `uq_usuario_email`.

#### Scenario: Nombre de la unicidad del correo
- **WHEN** se inserta un correo repetido y se lee el nombre de la restricción violada
- **THEN** el nombre es `uq_usuario_email`

#### Scenario: Mismo nombre en otra base
- **WHEN** se aplica el esquema sobre dos bases vacías distintas y se listan los nombres de restricciones e índices
- **THEN** ambas listas son idénticas

### Requirement: Navegación en ambos extremos
Cada relación que la API lee SHALL ser navegable desde los dos extremos: usuario↔asignaciones, usuario↔cliente, cliente↔vehículos, vehículo↔órdenes, mecánico↔órdenes asignadas, orden↔ítems, repuesto↔ítems, orden↔historial de estados, estado↔órdenes, repuesto↔movimientos y repuesto↔historial de precios. `Usuario.cliente` MUST devolver un objeto o nada, nunca una lista.

#### Scenario: Usuario.cliente es un objeto
- **WHEN** se lee, con precarga, el cliente de un usuario que tiene ficha
- **THEN** se obtiene esa ficha como objeto único, y desde ella `cliente.usuario` devuelve el mismo usuario

#### Scenario: Usuario sin ficha
- **WHEN** se lee, con precarga, el cliente de un usuario que no tiene ficha
- **THEN** se obtiene nada (no una lista vacía)

### Requirement: Sin carga perezosa
Ninguna relación SHALL cargarse implícitamente al accederla: leer una relación que no fue precargada MUST fallar de inmediato con un error explícito, sin emitir una consulta. Las relaciones precargadas por quien consulta MUST leerse sin consultas adicionales.

#### Scenario: Relación no precargada
- **WHEN** se obtiene una orden sin precargar sus ítems y se accede a sus ítems
- **THEN** se produce un error explícito de carga no permitida y no se envía ninguna consulta a la base

#### Scenario: Relación precargada
- **WHEN** se obtiene una orden precargando sus ítems y se accede a ellos
- **THEN** se obtienen los ítems sin consultas adicionales

### Requirement: Enums de dominio coherentes con la base
El código SHALL nombrar los estados de orden con un enum cuyos valores son exactamente PENDIENTE, EN_REPARACION, TERMINADA y CANCELADA (las filas que carga el seed) y los roles con un enum cuyos valores son exactamente los del CHECK de `asignacion_rol`. Las columnas guardan el texto del código, legible igual en psql que en la API.

#### Scenario: Valores del enum de roles
- **WHEN** se comparan los valores del enum de roles con los valores admitidos por el CHECK de `asignacion_rol.rol`
- **THEN** son el mismo conjunto

#### Scenario: Estado guardado como texto
- **WHEN** con el catálogo cargado se guarda una orden con el estado PENDIENTE del enum y se la consulta con psql
- **THEN** `orden_trabajo.estado` contiene el texto `PENDIENTE`
