# Spec Delta — role-assignment

## Purpose

Define cómo un administrador asigna, consulta y revoca los roles de un usuario con vigencia: una sola asignación abierta por rol (RN03), revocación sin borrar con efecto inmediato sobre las sesiones abiertas (RN04) y la autoprotección que impide que el sistema quede sin al menos un administrador vigente sin vencimiento (RN05).

## ADDED Requirements

### Requirement: Operaciones de roles sólo para ADMIN
`POST /usuarios/{id}/roles`, `GET /usuarios/{id}/roles` y `DELETE /usuarios/{id}/roles/{rol}` SHALL pertenecer al grupo protegido y exigir `ADMIN` vigente en la base, con el orden de rechazos del grupo (401, 403 por cambio pendiente, 403 por permiso, 422). `{id}` MUST ser un id de ruta válido y `{rol}` uno de `ADMIN`, `RECEPCION`, `MECANICO`, `CLIENTE`; otro valor → 422.

#### Scenario: Sin rol ADMIN
- **WHEN** un usuario con sólo `CLIENTE` vigente llama a cualquiera de las tres operaciones
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}` y no cambia ninguna asignación

#### Scenario: Rol inexistente en la ruta
- **WHEN** un ADMIN llama a `DELETE /usuarios/{id}/roles/SUPERVISOR`
- **THEN** la respuesta es 422 y no cambia ninguna asignación

#### Scenario: Id no entero
- **WHEN** un ADMIN llama a `GET /usuarios/abc/roles`
- **THEN** la respuesta es 422 y el handler no se ejecuta

### Requirement: Usuario inexistente
Las tres operaciones SHALL responder 404 `{"detail": "El usuario no existe"}` cuando `{id}` no corresponde a ningún usuario, sin escribir nada.

#### Scenario: Asignar a un usuario inexistente
- **WHEN** un ADMIN asigna un rol al usuario `999999`, que no existe
- **THEN** la respuesta es 404 `{"detail": "El usuario no existe"}` y no se agrega ninguna fila

#### Scenario: Consultar o revocar en un usuario inexistente
- **WHEN** un ADMIN consulta los roles o revoca un rol del usuario `999999`
- **THEN** la respuesta es el mismo 404

### Requirement: Contrato de la asignación
`POST /usuarios/{id}/roles` SHALL aceptar sólo `rol` (obligatorio, uno de los cuatro) y `vence_en` (opcional o nulo). `vence_en` MUST traer zona horaria y ser posterior al instante de la petición; sin zona o no futuro → 422, no 409. Se guarda en UTC, con su fracción de segundo.

#### Scenario: Vencimiento sin zona horaria
- **WHEN** `vence_en` es `"2099-01-01T00:00:00"`
- **THEN** la respuesta es 422 sobre `vence_en` y no se agrega ninguna fila

#### Scenario: Vencimiento en el pasado
- **WHEN** `vence_en` es `"2020-01-01T00:00:00Z"`
- **THEN** la respuesta es 422 sobre `vence_en`, aunque el usuario tenga ese rol vigente

#### Scenario: Vencimiento con otra zona
- **WHEN** `vence_en` es `"2099-01-01T00:00:00-03:00"`
- **THEN** la asignación se crea y la respuesta muestra `vence_en` igual a `2099-01-01T03:00:00Z`

#### Scenario: Campo no declarado
- **WHEN** el cuerpo incluye además `revocada_en` u `otorgada_por`
- **THEN** la respuesta es 422 que nombra el campo sobrante

#### Scenario: Rol fuera del catálogo
- **WHEN** `rol` es `"SUPERVISOR"` o `"admin"`
- **THEN** la respuesta es 422 sobre `rol`

### Requirement: Asignación de un rol
Una asignación aceptada SHALL responder 201 con `{id, usuario_id, rol, desde, vence_en, revocada_en, otorgada_por, vigente}` y abrir una fila con `desde` en el instante de la operación, el vencimiento pedido, `revocada_en` nulo y `otorgada_por` igual al ADMIN que la hizo.

#### Scenario: Asignación sin vencimiento
- **WHEN** un ADMIN asigna `MECANICO` a un usuario que nunca lo tuvo, sin `vence_en`
- **THEN** la respuesta es 201 con `rol: "MECANICO"`, `vence_en: null`, `revocada_en: null`, `vigente: true` y `otorgada_por` igual al id del ADMIN

#### Scenario: Efecto sobre una sesión abierta
- **WHEN** a un usuario con la sesión abierta se le asigna `ADMIN`
- **THEN** su petición siguiente a una ruta de ADMIN con la misma cookie se ejecuta, aunque el token no liste ese rol

#### Scenario: Rol que tuvo y le revocaron
- **WHEN** a un usuario se le revocó `ADMIN` y un ADMIN se lo vuelve a asignar
- **THEN** la respuesta es 201 con una fila nueva y la revocada sigue intacta

### Requirement: Una asignación abierta por rol
Asignar un rol que el usuario ya tiene vigente SHALL responder 409 `{"detail": "El usuario ya tiene el rol <ROL> vigente"}` sin escribir nada, aunque el pedido traiga otro vencimiento (RN03). La base MUST garantizarlo también ante asignaciones simultáneas.

#### Scenario: Rol vigente repetido
- **WHEN** un ADMIN asigna `MECANICO` a un usuario que ya lo tiene vigente
- **THEN** la respuesta es 409 `{"detail": "El usuario ya tiene el rol MECANICO vigente"}` y el usuario sigue con una sola fila abierta de `MECANICO`

#### Scenario: Asignaciones simultáneas del mismo rol
- **WHEN** dos asignaciones del mismo rol al mismo usuario llegan a la vez
- **THEN** una responde 201 y la otra 409, nunca 500, y queda una sola fila abierta

### Requirement: Reasignación de un rol vencido
Si el usuario tiene el rol con una fila abierta pero vencida, asignarlo SHALL cerrar esa fila (`revocada_en` en el instante de la operación) y abrir una nueva, en la misma transacción, respondiendo 201 con la fila nueva. Ninguna fila se borra.

#### Scenario: Rol vencido reasignado
- **WHEN** la fila abierta de `ADMIN` de un usuario tiene `vence_en` en el pasado y un ADMIN se lo asigna de nuevo
- **THEN** la respuesta es 201; la fila vencida queda con `revocada_en` igual al `desde` de la nueva, y el usuario tiene exactamente una fila abierta de `ADMIN`, vigente

#### Scenario: Sesión abierta tras la reasignación
- **WHEN** el usuario del rol vencido repite con la misma cookie una petición que exige ese rol después de la reasignación
- **THEN** la petición se ejecuta

### Requirement: Consulta de los roles de un usuario
`GET /usuarios/{id}/roles` SHALL responder 200 `{usuario_id, email, nombre, roles_vigentes, asignaciones}`: `roles_vigentes` con los roles no revocados y sin vencer en ese instante, y `asignaciones` con todas las filas del usuario (vigentes, vencidas y revocadas) en orden de `desde`, cada una con `vigente` calculado en ese instante. No es paginada.

#### Scenario: Historial completo
- **WHEN** un usuario tuvo `ADMIN` revocado, otro `ADMIN` vencido y tiene uno vigente
- **THEN** `asignaciones` trae las tres filas, sólo la última con `vigente: true`, y `roles_vigentes` es `["ADMIN"]`

#### Scenario: Usuario sin roles
- **WHEN** se consulta un usuario recién dado de alta como personal
- **THEN** la respuesta es 200 con `roles_vigentes: []` y `asignaciones: []`

#### Scenario: Sin datos sensibles
- **WHEN** se consulta cualquier usuario
- **THEN** la respuesta no contiene `password_hash` ni ningún dato de la cuenta fuera de los declarados

### Requirement: Revocación sin borrar
`DELETE /usuarios/{id}/roles/{rol}` SHALL escribir `revocada_en` en la fila vigente de ese rol y responder 200 con la asignación revocada (`vigente: false`); la fila MUST seguir existiendo. Si el usuario no tiene ese rol vigente (nunca lo tuvo, ya revocado o vencido), MUST responder 404 `{"detail": "El usuario no tiene el rol <ROL> vigente"}` sin escribir nada.

#### Scenario: Revocar un rol vigente
- **WHEN** un ADMIN revoca el `MECANICO` vigente de un usuario
- **THEN** la respuesta es 200 con `revocada_en` en el instante de la operación y `vigente: false`, y la fila sigue en `asignacion_rol`

#### Scenario: Revocar dos veces
- **WHEN** se repite la revocación del mismo rol
- **THEN** la respuesta es 404 `{"detail": "El usuario no tiene el rol MECANICO vigente"}` y `revocada_en` conserva el valor de la primera

#### Scenario: Revocar un rol vencido
- **WHEN** la única fila abierta del rol está vencida
- **THEN** la respuesta es el mismo 404 y la fila no cambia

### Requirement: Revocación con efecto inmediato
Revocar un rol SHALL quitar el permiso a las sesiones ya abiertas del usuario: su petición siguiente con la misma cookie a una ruta que exige sólo ese rol MUST responder 403, aunque el token todavía lo liste (RN04).

#### Scenario: Misma cookie después de revocar
- **WHEN** un segundo ADMIN con la sesión abierta lista `GET /eventos` (200) y otro ADMIN, sin vencimiento, le revoca `ADMIN`
- **THEN** su siguiente `GET /eventos` con la misma cookie responde 403 `{"detail": "No tiene permiso para realizar esta operación"}`, y `GET /auth/yo` muestra `ADMIN` en `roles_token` pero no en `roles_vigentes`

#### Scenario: Misma cookie después de vencer
- **WHEN** la fila vigente de `ADMIN` de ese usuario pasa a tener `vence_en` en el pasado
- **THEN** su siguiente `GET /eventos` con la misma cookie responde 403

### Requirement: Un ADMIN no se revoca su propio ADMIN
Un ADMIN que pide revocar su propio rol `ADMIN` SHALL recibir 409 `{"detail": "Un administrador no puede revocarse su propio rol ADMIN"}`, sin escribir nada (RN05). Sus otros roles sí puede revocárselos.

#### Scenario: Autorrevocación
- **WHEN** un ADMIN llama a `DELETE /usuarios/{su id}/roles/ADMIN`
- **THEN** la respuesta es 409 con el mensaje de autoprotección y su fila de `ADMIN` sigue vigente

#### Scenario: Otro rol propio
- **WHEN** un ADMIN que también tiene `MECANICO` vigente se revoca `MECANICO`
- **THEN** la respuesta es 200

### Requirement: Siempre un administrador vigente sin vencimiento
Una revocación de `ADMIN` SHALL responder 409 `{"detail": "No se puede revocar: el sistema quedaría sin administradores vigentes sin vencimiento"}`, sin escribir nada, si después de la revocación no quedaría al menos una asignación `ADMIN` vigente sin vencimiento (`vence_en` nulo, `revocada_en` nulo) de un usuario activo (RN05). Las asignaciones `ADMIN` con `vence_en` MUST NOT contar para esta regla, aunque estén vigentes. Si no existe ninguna asignación `ADMIN` sin vencimiento, toda revocación de `ADMIN` MUST responder ese 409. La regla MUST valer también con revocaciones simultáneas: nunca se confirman dos que juntas dejen sin administradores vigentes sin vencimiento. Asignar `ADMIN` con `vence_en` SHALL seguir permitido, sin regla adicional.

#### Scenario: Un ADMIN con vencimiento revoca al único ADMIN sin vencimiento
- **WHEN** el único ADMIN sin vencimiento es `jefa` y otro ADMIN, con `vence_en` futuro, pide `DELETE /usuarios/{jefa}/roles/ADMIN`
- **THEN** la respuesta es 409 con el mensaje de sin administradores vigentes sin vencimiento, la fila de `ADMIN` de `jefa` sigue vigente y no se agrega ninguna línea en `evento_seguridad`

#### Scenario: Queda otro ADMIN sin vencimiento
- **WHEN** hay dos ADMIN sin vencimiento y un ADMIN con `vence_en` futuro revoca el `ADMIN` de uno de ellos
- **THEN** la respuesta es 200 y el otro ADMIN sin vencimiento sigue vigente

#### Scenario: Dos administradores sin vencimiento se revocan entre sí a la vez
- **WHEN** los dos únicos ADMIN sin vencimiento piden al mismo tiempo revocar el `ADMIN` del otro
- **THEN** una revocación responde 200 y la otra 409 con el mensaje de sin administradores vigentes sin vencimiento, y queda exactamente un ADMIN vigente sin vencimiento

#### Scenario: Asignar ADMIN con vencimiento
- **WHEN** un ADMIN asigna `ADMIN` a otro usuario con `vence_en` futuro
- **THEN** la respuesta es 201 con ese `vence_en` y `vigente: true`; RN05 no agrega ningún rechazo a la asignación

### Requirement: Cambios de rol en el historial de seguridad
Toda asignación aceptada (también la reasignación de un rol vencido) y toda revocación aceptada SHALL agregar, en la misma transacción, una línea en `evento_seguridad` con el correo del ADMIN como actor y una acción que nombra la operación, el rol y el correo del usuario afectado. Un rechazo (403, 404, 409, 422) MUST NOT agregar líneas.

#### Scenario: Evento de asignación
- **WHEN** un ADMIN asigna `MECANICO` a `nuevo@personal.example.com`
- **THEN** hay una línea nueva con ese ADMIN como actor y una acción que contiene `MECANICO` y `nuevo@personal.example.com`

#### Scenario: Evento de revocación
- **WHEN** un ADMIN revoca un rol
- **THEN** hay una línea nueva que nombra la revocación, el rol y el correo afectado

#### Scenario: Rechazo sin evento
- **WHEN** una asignación responde 409 por rol vigente repetido o una revocación responde 409 por autoprotección o por quedar sin administradores vigentes sin vencimiento
- **THEN** no se agrega ninguna línea en `evento_seguridad`

#### Scenario: Falla al registrar el evento
- **WHEN** la escritura del evento falla dentro de una asignación o revocación
- **THEN** la asignación o revocación tampoco queda guardada
