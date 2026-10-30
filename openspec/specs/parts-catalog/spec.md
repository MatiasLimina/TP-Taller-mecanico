# parts-catalog Specification

## Purpose

Define el catálogo de repuestos del taller: quién lo consulta y quién lo mantiene, cómo se da de alta, busca, edita y da de baja un repuesto, y qué contrato de entrada y salida respeta cada ruta de `/repuestos`.

## Requirements

### Requirement: Acceso al catálogo por rol
Las rutas de `/repuestos` SHALL pertenecer al grupo protegido. `GET /repuestos` y `GET /repuestos/{id}` MUST exigir un rol vigente ADMIN, RECEPCION o MECANICO; `POST`, `PATCH` y `DELETE` MUST exigir ADMIN vigente. Sin sesión → 401; cambio de contraseña pendiente → 403; sin el rol → 403, antes de validar el cuerpo o buscar el recurso.

#### Scenario: Sin sesión
- **WHEN** se llama a `GET /repuestos` sin cookie
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`

#### Scenario: Cliente sin rol de personal
- **WHEN** un usuario con sólo el rol CLIENTE llama a `GET /repuestos`
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}`

#### Scenario: Lectura para el personal
- **WHEN** un usuario con rol vigente RECEPCION o MECANICO llama a `GET /repuestos` o a `GET /repuestos/{id}` de un repuesto vigente
- **THEN** la respuesta es 200

#### Scenario: Escritura sólo ADMIN
- **WHEN** un usuario con rol RECEPCION o MECANICO (sin ADMIN) llama a `POST /repuestos`, `PATCH /repuestos/{id}` o `DELETE /repuestos/{id}` con un cuerpo válido
- **THEN** la respuesta es 403 y no se escribe ninguna fila

#### Scenario: Permiso antes que contrato
- **WHEN** se llama a `POST /repuestos` sin cookie y con un campo no declarado
- **THEN** la respuesta es 401, no 422

### Requirement: Contrato de salida del repuesto
Toda respuesta que devuelve un repuesto SHALL tener exactamente `id`, `codigo`, `descripcion`, `precio` y `stock`, igual para los tres roles de personal. `precio` MUST serializarse como texto decimal con dos decimales (p. ej. `"8500.00"`). La respuesta MUST NOT incluir `borrado_en` ni datos de movimientos o historiales.

#### Scenario: Forma de la salida
- **WHEN** se lee un repuesto con precio 8500 y stock 10
- **THEN** el cuerpo es `{"id": <id>, "codigo": "...", "descripcion": "...", "precio": "8500.00", "stock": 10}` y no tiene otras claves

#### Scenario: OpenAPI sin campos internos
- **WHEN** se consulta `/openapi.json`
- **THEN** ningún esquema de respuesta de `/repuestos` declara `borrado_en`

### Requirement: Alta de repuesto
`POST /repuestos` SHALL aceptar `{codigo, descripcion, precio, stock_inicial?}` y responder 201 con el repuesto creado, con `stock` igual a `stock_inicial` (0 si se omite). El contrato MUST rechazar con 422 todo campo no declarado, incluido `stock`.

#### Scenario: Alta con stock inicial
- **WHEN** un ADMIN envía `{"codigo": "FIL-ACE-01", "descripcion": "Filtro de aceite", "precio": 8500, "stock_inicial": 10}`
- **THEN** la respuesta es 201 con `codigo` `"FIL-ACE-01"`, `precio` `"8500.00"` y `stock` 10

#### Scenario: Alta sin stock inicial
- **WHEN** un ADMIN da de alta un repuesto sin `stock_inicial`
- **THEN** la respuesta es 201 con `stock` 0

#### Scenario: Stock en el cuerpo
- **WHEN** el cuerpo del alta incluye `"stock": 5`
- **THEN** la respuesta es 422 `extra_forbidden` y no se crea el repuesto

### Requirement: Validación del contrato de alta
El código SHALL recortarse y pasarse a mayúsculas y MUST tener 1 a 30 caracteres de letras A–Z, dígitos y guiones simples internos. La descripción SHALL recortarse y tener 1 a 200 caracteres. El precio MUST ser decimal mayor que 0, con hasta 10 dígitos y 2 decimales. `stock_inicial` MUST ser entero de 0 a 100000. Lo inválido → 422, nunca 500.

#### Scenario: Normalización del código y la descripción
- **WHEN** el alta envía `"codigo": " fil-ace-01 "` y `"descripcion": "  Filtro de aceite "`
- **THEN** el repuesto queda con `codigo` `"FIL-ACE-01"` y `descripcion` `"Filtro de aceite"`

#### Scenario: Código con caracteres no admitidos
- **WHEN** el código es vacío, sólo espacios, `"FIL ACE"`, `"FIL_ACE"` o tiene 31 caracteres
- **THEN** la respuesta es 422 sobre `codigo`

#### Scenario: Precio fuera de contrato
- **WHEN** el precio es 0, negativo, tiene 3 decimales, tiene más de 10 dígitos o no es un número
- **THEN** la respuesta es 422 sobre `precio` y no se crea el repuesto

#### Scenario: Stock inicial fuera de contrato
- **WHEN** `stock_inicial` es -1, 1.5 o 100001
- **THEN** la respuesta es 422 sobre `stock_inicial`

### Requirement: Código único entre repuestos vigentes
Dar de alta un repuesto cuyo código (ya normalizado) pertenece a otro repuesto vigente SHALL responder 409 `Ya existe un repuesto vigente con el código <CODIGO>` sin crear filas, también con altas simultáneas. El código de un repuesto dado de baja MUST poder reutilizarse.

#### Scenario: Código vigente repetido
- **WHEN** existe el repuesto vigente `FIL-ACE-01` y se da de alta otro con código `"fil-ace-01"`
- **THEN** la respuesta es 409 `{"detail": "Ya existe un repuesto vigente con el código FIL-ACE-01"}` y no se crea repuesto ni movimiento

#### Scenario: Altas simultáneas del mismo código
- **WHEN** dos altas con el mismo código llegan a la vez
- **THEN** una responde 201 y la otra 409, nunca 500

#### Scenario: Código de un repuesto dado de baja
- **WHEN** el repuesto `BUJ-01` está dado de baja y se da de alta otro con código `BUJ-01`
- **THEN** la respuesta es 201 con un `id` nuevo y el repuesto dado de baja sigue en la tabla

### Requirement: Listado paginado del catálogo
`GET /repuestos` SHALL devolver sólo repuestos vigentes, ordenados por `id` ascendente, con el envoltorio común de listados (`page`, `size`, página vacía, página inexistente → 422).

#### Scenario: Primera página
- **WHEN** hay 3 repuestos vigentes y se pide `size=2`
- **THEN** la respuesta es 200 con los 2 de menor `id`, `total` 3 y `pages` 2

#### Scenario: Catálogo vacío
- **WHEN** no hay repuestos vigentes
- **THEN** la respuesta es 200 con `items` vacío, `total` 0 y `pages` 1

#### Scenario: Página inexistente
- **WHEN** hay 2 páginas y se pide `page=3`
- **THEN** la respuesta es 422 `{"detail": "La página 3 no existe: hay 2"}`

### Requirement: Búsqueda con parámetros ligados
El parámetro `q` SHALL filtrar los repuestos vigentes cuya descripción o código contenga el texto, sin distinguir mayúsculas; `total` y `pages` MUST contar con el mismo filtro. El texto MUST viajar como parámetro ligado: comillas, `%`, `_` y `\` se buscan literalmente. `q` vacío o sólo espacios no filtra; más de 100 caracteres → 422.

#### Scenario: Inyección inofensiva (PDF C-16)
- **WHEN** se pide `GET /repuestos?q=' OR '1'='1`
- **THEN** la respuesta es 200 con `items` vacío, `total` 0 y `pages` 1

#### Scenario: Búsqueda paginada con filtro (PDF C-16)
- **WHEN** existe un solo repuesto cuya descripción contiene «freno» y se pide `q=freno&size=1`
- **THEN** la respuesta es 200 con ese repuesto, `total` 1 y `pages` 1; con `page=2` la respuesta es 422

#### Scenario: Búsqueda por código sin distinguir mayúsculas
- **WHEN** se pide `q=pas-fre` y existe el repuesto `PAS-FRE-DEL`
- **THEN** la respuesta lo incluye

#### Scenario: Comodines como texto
- **WHEN** se pide `q=%` o `q=_` y ningún código ni descripción contiene ese carácter
- **THEN** la respuesta es una página vacía con `total` 0

#### Scenario: Texto de búsqueda demasiado largo
- **WHEN** `q` tiene 101 caracteres
- **THEN** la respuesta es 422

### Requirement: Detalle de un repuesto
`GET /repuestos/{id}` SHALL devolver el repuesto vigente con ese id. Un id inexistente o de un repuesto dado de baja MUST responder 404 `El repuesto no existe`; un id que no es entero entre 1 y 2147483647 → 422.

#### Scenario: Repuesto vigente
- **WHEN** un MECANICO pide el detalle de un repuesto vigente
- **THEN** la respuesta es 200 con el contrato de salida del repuesto

#### Scenario: Inexistente o dado de baja
- **WHEN** se pide `GET /repuestos/999999` o el id de un repuesto dado de baja
- **THEN** la respuesta es 404 `{"detail": "El repuesto no existe"}`

#### Scenario: Id inválido
- **WHEN** se pide `GET /repuestos/abc` o `GET /repuestos/0`
- **THEN** la respuesta es 422

### Requirement: Edición parcial de descripción y precio
`PATCH /repuestos/{id}` SHALL aceptar sólo `descripcion` y `precio`, con las mismas reglas del alta, y modificar sólo los campos enviados. `stock`, `codigo` o cualquier otro campo → 422; un campo enviado con `null` → 422; un cuerpo vacío → 200 sin cambios. Repuesto inexistente o dado de baja → 404.

#### Scenario: Sólo cambia lo enviado (PDF C-16)
- **WHEN** un ADMIN envía `{"descripcion": "Filtro de aceite sintético"}` a un repuesto con precio 8500.00
- **THEN** la respuesta es 200 con la nueva descripción y `precio` `"8500.00"` sin cambios

#### Scenario: PATCH del stock (PDF C-16)
- **WHEN** el cuerpo del PATCH incluye `"stock": 50`
- **THEN** la respuesta es 422 `extra_forbidden` y el stock no cambia

#### Scenario: Campo nulo
- **WHEN** el cuerpo es `{"precio": null}`
- **THEN** la respuesta es 422 y el precio no cambia

#### Scenario: Cuerpo vacío
- **WHEN** el cuerpo es `{}`
- **THEN** la respuesta es 200 con el repuesto sin cambios

#### Scenario: Repuesto dado de baja
- **WHEN** se envía un PATCH válido a un repuesto dado de baja o inexistente
- **THEN** la respuesta es 404 `{"detail": "El repuesto no existe"}`

### Requirement: Baja lógica de repuesto
`DELETE /repuestos/{id}` SHALL marcar el repuesto como dado de baja y responder 204 sin cuerpo, aunque tenga stock. La fila, su stock, sus movimientos y su historial de precios MUST conservarse. Un repuesto inexistente o ya dado de baja → 404, también si dos bajas llegan a la vez.

#### Scenario: Baja de un repuesto con stock
- **WHEN** un ADMIN da de baja un repuesto vigente con stock 4
- **THEN** la respuesta es 204, la fila sigue con `borrado_en` no nulo y stock 4, y sus movimientos siguen existiendo

#### Scenario: Deja de aparecer
- **WHEN** un repuesto fue dado de baja
- **THEN** no aparece en `GET /repuestos` (con o sin `q`) y `GET /repuestos/{id}` responde 404

#### Scenario: Segunda baja
- **WHEN** se da de baja un repuesto ya dado de baja, o dos bajas del mismo repuesto llegan a la vez
- **THEN** la segunda responde 404 `{"detail": "El repuesto no existe"}`
