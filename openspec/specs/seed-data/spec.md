# seed-data Specification

## Purpose
Define la recarga del estado inicial conocido de la base de desarrollo y pruebas: cómo se vacía, qué datos exactos carga (catálogo, usuarios y roles, clientes, repuestos, órdenes e historiales) y qué garantías da (idempotencia, atomicidad, correos válidos, contraseñas de prueba fuera del entorno), para que los casos `.http` y la evidencia en psql partan siempre del mismo estado.

## Requirements

### Requirement: Recarga completa e idempotente
Ejecutar `python seed.py` sobre una base migrada a la última revisión SHALL dejar las 13 tablas del dominio con exactamente el estado inicial de esta especificación, sin importar qué contenían antes, y con los contadores de identidad reiniciados. La tabla de versión de Alembic MUST quedar intacta.

#### Scenario: Base recién migrada
- **WHEN** se ejecuta `python seed.py` sobre una base en la última revisión y sin filas
- **THEN** el comando termina con código 0 y las tablas tienen exactamente los datos de esta especificación

#### Scenario: Dos ejecuciones seguidas
- **WHEN** se ejecuta `python seed.py` dos veces seguidas
- **THEN** después de cada ejecución las mismas consultas devuelven las mismas filas con los mismos ids (salvo `password_hash` y las marcas de tiempo)

#### Scenario: Base con datos de pruebas y de sólo agregado
- **WHEN** la base ya tiene usuarios, órdenes, movimientos de stock e historiales cargados por la API o por los `.http`, y se ejecuta `python seed.py`
- **THEN** el comando termina con código 0 sin ningún rechazo de sólo agregado, no queda ninguna fila anterior y el estado es el mismo que sobre una base vacía

#### Scenario: Ids deterministas
- **WHEN** se ejecuta `python seed.py`
- **THEN** los usuarios tienen ids 1 a 7 en el orden `admin`, `admin2`, `recepcion`, `mecanico`, `mecanico2`, `cliente`, `nuevo`, y las órdenes tienen ids 1 y 2

#### Scenario: Versión del esquema conservada
- **WHEN** se ejecuta `python seed.py` y luego `alembic current`
- **THEN** `alembic current` muestra la misma revisión `(head)` que antes

### Requirement: Recarga atómica
El vaciado y la carga SHALL ocurrir en una única transacción: si cualquier paso falla, la base MUST quedar exactamente como estaba antes de ejecutar el seed y el comando MUST terminar con código distinto de 0.

#### Scenario: Falla a mitad de la carga
- **WHEN** la carga falla después de haber vaciado las tablas e insertado parte de los datos
- **THEN** el comando termina con código distinto de 0 y los conteos de todas las tablas del dominio son los mismos que antes de ejecutarlo

### Requirement: Protección de sólo agregado intacta
El vaciado del seed SHALL usar sólo la operación de vaciado completo de tablas, que la protección de sólo agregado permite, sin borrar fila por fila ni desactivar o eliminar disparadores. Después del seed la protección MUST seguir rechazando `UPDATE` y `DELETE` en las tres tablas.

#### Scenario: Protección vigente después del seed
- **WHEN** se ejecuta `python seed.py` y después `psql -f test/solo_agregado.sql`
- **THEN** el script muestra los mismos seis rechazos de sólo agregado y el rechazo por clave foránea que sobre una base vacía

### Requirement: Catálogo de estados
El seed SHALL cargar en `estado_orden`, antes que cualquier orden, exactamente cuatro filas, cada una con una descripción no vacía: `PENDIENTE` (posición 1), `EN_REPARACION` (2), `TERMINADA` (3, final) y `CANCELADA` (4, final). Los códigos MUST coincidir con los del enum de estados del código.

#### Scenario: Filas del catálogo
- **WHEN** después del seed se consulta `SELECT codigo, posicion, es_final FROM estado_orden ORDER BY posicion`
- **THEN** el resultado es `PENDIENTE 1 false`, `EN_REPARACION 2 false`, `TERMINADA 3 true`, `CANCELADA 4 true`

### Requirement: Usuarios y roles iniciales
El seed SHALL crear siete usuarios activos con hash bcrypt del costo configurado y una asignación abierta: `admin@example.com` y `admin2@example.com` (ADMIN), `recepcion@example.com` (RECEPCION), `mecanico@example.com` y `mecanico2@example.com` (MECANICO), `cliente@example.com` (CLIENTE) y `nuevo@example.com` (MECANICO, cambio de contraseña pendiente). Ninguna asignación MUST tener `vence_en`.

#### Scenario: Usuarios y roles
- **WHEN** después del seed se consultan `usuario` y `asignacion_rol`
- **THEN** hay siete usuarios activos, cada uno con exactamente una asignación abierta del rol indicado, sin `vence_en` ni `revocada_en`, y sólo `nuevo@example.com` tiene `debe_cambiar_password` verdadero

#### Scenario: Primer ADMIN sin vencimiento
- **WHEN** después del seed se cuentan las asignaciones `ADMIN` vigentes sin vencimiento de usuarios activos
- **THEN** son dos (`admin@` y `admin2@`), así que revocar el `ADMIN` de uno de ellos desde el otro está permitido por la regla de administradores

#### Scenario: Hash con el costo configurado
- **WHEN** se lee `password_hash` de cualquier usuario del seed
- **THEN** es un hash bcrypt (`$2b$`) con el costo de `BCRYPT_COST`, distinto para cada usuario, y nunca la contraseña en claro

### Requirement: Correos verificados antes de cargar
Cada correo del seed SHALL estar en minúsculas, sin espacios y con un dominio que la validación de correos de la API acepte. El seed MUST verificarlos antes de conectarse a la base y, si alguno no cumple, terminar con código distinto de 0 y un mensaje que nombra el correo, sin normalizarlo ni modificar la base.

#### Scenario: Correo con mayúsculas o espacios
- **WHEN** un correo del seed es `Admin@example.com` o ` admin@example.com`
- **THEN** el seed termina con error que nombra ese correo y la base no cambia

#### Scenario: Dominio de uso especial
- **WHEN** un correo del seed termina en `.local`, `.test` o `.localhost`
- **THEN** el seed termina con error que nombra ese correo y la base no cambia

### Requirement: Login con los usuarios del seed
Cada usuario del seed SHALL poder iniciar sesión por `POST /auth/login` con la contraseña de prueba definida en `seed.py`, y sus roles vigentes en la base MUST ser los de esta especificación.

#### Scenario: Login del personal y del cliente
- **WHEN** después del seed cada uno de los siete usuarios hace login con su contraseña de prueba
- **THEN** la respuesta es 200 y `GET /auth/yo` con esa cookie devuelve el rol indicado en `roles_vigentes`

#### Scenario: Cambio de contraseña pendiente
- **WHEN** `nuevo@example.com` inicia sesión y usa esa cookie en una ruta protegida
- **THEN** el login responde 200 con `debe_cambiar_password: true` y la ruta protegida responde 403 `Debe cambiar la contraseña antes de continuar`

### Requirement: Contraseñas de prueba fuera del entorno
Las contraseñas de los usuarios del seed SHALL ser valores de prueba definidos sólo en `seed.py` (y repetidos como datos de prueba en los `.http`), nunca en `.env`, `env.example` ni la configuración. El seed MUST obtener la conexión de la misma configuración del entorno que la aplicación y MUST NOT imprimir contraseñas, hashes ni la URL de la base.

#### Scenario: Salida del seed
- **WHEN** se ejecuta `python seed.py`
- **THEN** la salida es un resumen con la cantidad de filas cargadas y no contiene contraseñas, hashes ni la URL de conexión

#### Scenario: Sin configuración
- **WHEN** se ejecuta `python seed.py` sin `POSTGRES_PASSWORD` o sin `SECRET_KEY` configurados
- **THEN** el comando falla con un error de configuración que nombra la variable faltante y no toca la base

### Requirement: Clientes y vehículos
El seed SHALL crear la ficha de Laura vinculada a `cliente@example.com` con dos vehículos vigentes, y la ficha de Jorge sin usuario con un vehículo vigente. Los documentos y patentes MUST ser únicos y no coincidir con los que usan los archivos `.http` existentes.

#### Scenario: Fichas y vehículos
- **WHEN** después del seed se consultan `cliente` y `vehiculo`
- **THEN** hay dos clientes: Laura con `usuario_id` de `cliente@example.com` y dos vehículos, Jorge con `usuario_id` nulo y un vehículo; ningún vehículo tiene `borrado_en`

### Requirement: Repuestos con stock inicial por movimiento
El seed SHALL crear cuatro repuestos vigentes — filtro de aceite (stock 10, precio 8500), pastillas de freno delanteras (4, 32000), bujía (2) y aceite 5W30 por litro (20, 12000) — y, por cada uno, un movimiento `Stock inicial` con cantidad positiva igual a su stock. El stock de cada repuesto MUST ser igual a la suma de sus movimientos.

#### Scenario: Stock coherente con los movimientos
- **WHEN** después del seed se compara `repuesto.stock` con `SUM(movimiento_stock.cantidad)` por repuesto
- **THEN** coinciden para los cuatro repuestos y hay exactamente cuatro movimientos, todos con motivo `Stock inicial` y sin orden

### Requirement: Historial de precio inicial
El seed SHALL dejar una línea en `historial_precio_repuesto` para el filtro de aceite con precio anterior 8000.00 y precio nuevo 8500.00, igual a su precio actual.

#### Scenario: Línea de precio
- **WHEN** después del seed se consulta `historial_precio_repuesto`
- **THEN** hay exactamente una línea, del filtro de aceite, `8000.00 → 8500.00`

### Requirement: Órdenes de ejemplo
El seed SHALL crear la orden 1 PENDIENTE del primer vehículo de Laura, sin mecánico, y la orden 2 EN_REPARACION del vehículo de Jorge asignada a `mecanico@example.com` con 4 bujías aunque haya 2 en stock (dato de prueba deliberado, IN-04). Cada orden MUST tener al menos un ítem, precios copiados del repuesto, total igual a la suma de sus ítems e historial de estados coherente con su estado.

#### Scenario: Orden 1 pendiente
- **WHEN** después del seed se consulta la orden 1
- **THEN** está en `PENDIENTE`, sin mecánico, con al menos un ítem, `total` igual a `SUM(cantidad * precio_unitario)` y una línea de historial `NULL → PENDIENTE`

#### Scenario: Orden 2 en reparación con sobreentrega
- **WHEN** después del seed se consulta la orden 2
- **THEN** está en `EN_REPARACION`, asignada a `mecanico@example.com`, con un ítem de 4 bujías, el stock de bujías es 2, el total es la suma de sus ítems y su historial es `NULL → PENDIENTE` y `PENDIENTE → EN_REPARACION`, en ese orden

#### Scenario: Stock no descontado
- **WHEN** después del seed se consultan los movimientos de stock
- **THEN** ninguno tiene `orden_id`: el stock se descuenta recién al terminar una orden

### Requirement: Evento de la carga inicial
El seed SHALL dejar en `evento_seguridad` exactamente una línea, con actor `SISTEMA` y acción `Carga de los datos iniciales`; no escribe eventos por cada usuario o rol que crea.

#### Scenario: Historial de seguridad después del seed
- **WHEN** un ADMIN del seed consulta `GET /eventos` inmediatamente después del seed
- **THEN** la página tiene `total` 1 y un único ítem con `actor` `SISTEMA` y `accion` `Carga de los datos iniciales`
