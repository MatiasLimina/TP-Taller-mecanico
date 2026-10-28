# Spec Delta — security-events

## Purpose

Define el historial de seguridad: qué operaciones dejan una línea en `evento_seguridad`, con qué actor y en qué transacción, y cómo un administrador lo consulta paginado con `GET /eventos`.

## ADDED Requirements

### Requirement: Operaciones que dejan evento
`evento_seguridad` SHALL recibir una línea por cada auto-registro, alta de personal, asignación o revocación de rol aceptada y cambio de contraseña exitoso, escrita en la misma transacción que la operación. Los intentos de login y las operaciones rechazadas MUST NOT dejar línea.

#### Scenario: Operación aceptada
- **WHEN** se acepta un alta de personal, una asignación o una revocación de rol
- **THEN** existe exactamente una línea nueva en `evento_seguridad` por esa operación

#### Scenario: Operación rechazada
- **WHEN** un alta responde 409 por correo repetido o una revocación responde 404
- **THEN** la cantidad de líneas de `evento_seguridad` no cambia

#### Scenario: Login
- **WHEN** un login responde 200 o 401
- **THEN** no se agrega ninguna línea en `evento_seguridad` (los intentos van a `intento_acceso`)

### Requirement: Actor y acción del evento
Cada línea SHALL tener `cuando` con zona horaria, `actor` igual al correo normalizado de quien hizo la operación (el ADMIN en las operaciones de personal y roles; el propio usuario en el auto-registro y el cambio de contraseña) y una `accion` en texto propio que nombra la operación y, si afecta a otro usuario, su correo y el rol. `actor` es texto, no una referencia a `usuario`.

#### Scenario: Actor de una operación de ADMIN
- **WHEN** `jefa@personal.example.com` da de alta a `nuevo@personal.example.com`
- **THEN** la línea tiene `actor` `jefa@personal.example.com` y una `accion` que nombra el alta de personal y `nuevo@personal.example.com`

#### Scenario: Sin datos secretos
- **WHEN** se lee cualquier línea de `evento_seguridad`
- **THEN** ni `actor` ni `accion` contienen contraseñas, hashes ni tokens

### Requirement: Consulta del historial sólo para ADMIN
`GET /eventos` SHALL pertenecer al grupo protegido y exigir `ADMIN` vigente en la base: sin sesión 401, con cambio de contraseña pendiente 403 por cambio pendiente y sin `ADMIN` vigente 403 por permiso.

#### Scenario: Sin sesión
- **WHEN** se llama a `GET /eventos` sin cookie
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`

#### Scenario: Cliente
- **WHEN** un usuario con sólo `CLIENTE` vigente llama a `GET /eventos`
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}`

#### Scenario: ADMIN con cambio pendiente
- **WHEN** un usuario con `ADMIN` vigente y `debe_cambiar_password` verdadero llama a `GET /eventos`
- **THEN** la respuesta es 403 `{"detail": "Debe cambiar la contraseña antes de continuar"}`, y después de cambiar la contraseña la cookie nueva obtiene 200

### Requirement: Historial paginado, del más reciente al más antiguo
`GET /eventos` SHALL aceptar sólo `page` y `size`, con las reglas y el envoltorio comunes de los listados (`items`, `total`, `page`, `size`, `pages`; 422 por página o tamaño inválidos o inexistentes). Cada ítem MUST ser `{id, cuando, actor, accion}`, ordenados del más reciente al más antiguo (id descendente).

#### Scenario: Primera página
- **WHEN** un ADMIN pide `GET /eventos?size=2` y hay al menos tres eventos
- **THEN** la respuesta es 200 con 2 ítems, el primero el evento de id más alto, y `total` igual a la cantidad de líneas de `evento_seguridad`

#### Scenario: Último evento primero
- **WHEN** un ADMIN asigna un rol y enseguida pide `GET /eventos?size=1`
- **THEN** el único ítem es el evento de esa asignación

#### Scenario: Tamaño excesivo
- **WHEN** se pide `GET /eventos?size=500`
- **THEN** la respuesta es 422

#### Scenario: Página inexistente
- **WHEN** hay 1 página y se pide `page=2`
- **THEN** la respuesta es 422 `{"detail": "La página 2 no existe: hay 1"}`
