# order-states Specification

## Purpose

Define el catálogo de estados de una orden de trabajo (RN19): sus filas son los únicos estados posibles, la API lo expone sólo para leer y en orden, y es requisito para crear órdenes.

## Requirements


### Requirement: Consulta del catálogo de estados
`GET /estados-orden` SHALL estar en el grupo protegido, aceptarse para cualquier usuario autenticado sin importar sus roles (también un CLIENTE o un usuario sin roles de personal), y devolver 200 con un arreglo JSON de todas las filas de `estado_orden`, cada una exactamente `{"codigo", "descripcion", "posicion", "es_final"}`, ordenadas por `posicion` ascendente. Sin sesión → 401; con cambio de contraseña pendiente → 403. Un catálogo vacío MUST responder 200 `[]`.

#### Scenario: Catálogo cargado
- **WHEN** el catálogo tiene PENDIENTE (1), EN_REPARACION (2), TERMINADA (3, final) y CANCELADA (4, final) y un usuario sólo CLIENTE pide `GET /estados-orden`
- **THEN** la respuesta es 200 con esos cuatro estados en ese orden, `es_final` `false`, `false`, `true`, `true`

#### Scenario: Orden por posición, no por código
- **WHEN** el catálogo tiene sólo EN_REPARACION (2), TERMINADA (3) y CANCELADA (4)
- **THEN** la respuesta los devuelve por `posicion`: EN_REPARACION, TERMINADA, CANCELADA

#### Scenario: Catálogo vacío
- **WHEN** `estado_orden` no tiene filas
- **THEN** la respuesta es 200 `[]`

#### Scenario: Sin sesión o con cambio pendiente
- **WHEN** se pide `GET /estados-orden` sin cookie, o con la sesión de un usuario que debe cambiar la contraseña
- **THEN** la respuesta es 401, o 403 `Debe cambiar la contraseña antes de continuar`, respectivamente

### Requirement: El catálogo no se edita desde la API
La API MUST NOT ofrecer ninguna ruta que cree, modifique o borre filas de `estado_orden`; la única operación del catálogo es la lectura. Los estados de una orden y de su historial SHALL ser siempre filas del catálogo (lo garantiza la clave foránea).

#### Scenario: Escritura del catálogo
- **WHEN** se envía `POST`, `PATCH`, `PUT` o `DELETE` a `/estados-orden`
- **THEN** la respuesta es 405 y el catálogo no cambia

#### Scenario: Estado del alta
- **WHEN** se crea una orden
- **THEN** su `estado` y el `hasta_estado` de su primera línea de historial son el código `PENDIENTE` del catálogo
