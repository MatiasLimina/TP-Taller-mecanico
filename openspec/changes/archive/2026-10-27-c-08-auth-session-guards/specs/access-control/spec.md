# Spec Delta — access-control

## Purpose

Define qué rutas pide sesión y cuáles no, el bloqueo de las rutas protegidas mientras haya un cambio de contraseña pendiente (RN06) y la autorización por roles vigentes en la base en cada petición (RN04), con 401 y 403 siempre distintos.

## ADDED Requirements

### Requirement: Grupo abierto y grupo protegido
La API SHALL tener dos grupos de rutas. El abierto contiene `/health/*` y `/auth/*`; ahí cada ruta decide si pide sesión. Toda ruta de cualquier otro prefijo MUST pertenecer al grupo protegido, que exige una sesión válida (401 si no la hay) aunque la ruta no declare roles.

#### Scenario: Salud y auth sin sesión
- **WHEN** se llama sin cookie a `GET /health/live`, `POST /auth/login` o `POST /auth/logout`
- **THEN** se atienden con normalidad, sin 401 ni 403

#### Scenario: Ruta protegida sin sesión
- **WHEN** se llama sin cookie a una ruta del grupo protegido que no declara roles
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`

### Requirement: Bloqueo por cambio de contraseña pendiente
Mientras el usuario tenga `debe_cambiar_password` verdadero, toda ruta del grupo protegido SHALL responder 403 `{"detail": "Debe cambiar la contraseña antes de continuar"}`, sin ejecutar la operación. El control MUST aplicarse una sola vez para todo el grupo, no ruta por ruta, y MUST NOT aplicarse al grupo abierto (RN06).

#### Scenario: Ruta protegida con cambio pendiente
- **WHEN** un usuario con `debe_cambiar_password` verdadero llama a una ruta del grupo protegido
- **THEN** la respuesta es 403 `{"detail": "Debe cambiar la contraseña antes de continuar"}` y la operación no se ejecuta

#### Scenario: Rutas de auth con cambio pendiente
- **WHEN** ese mismo usuario llama a `GET /auth/yo` o a `POST /auth/cambiar-password`
- **THEN** se atienden con normalidad (sin 403)

#### Scenario: Después del cambio
- **WHEN** el usuario cambia la contraseña y repite la petición protegida con la cookie nueva
- **THEN** ya no recibe el 403 por cambio pendiente

### Requirement: Autorización por roles vigentes en la base
Una ruta protegida que exige roles SHALL consultar en la base, en esa misma petición, los roles vigentes del usuario (no revocados y sin vencer) y MUST responder 403 `{"detail": "No tiene permiso para realizar esta operación"}` si ninguno está entre los exigidos. Los roles del token MUST NOT intervenir en la decisión (RN04). Ningún rol tiene permisos implícitos sobre otro.

#### Scenario: Rol exigido presente
- **WHEN** un usuario con rol `ADMIN` vigente llama a una ruta que exige `ADMIN`
- **THEN** la operación se ejecuta

#### Scenario: Sin el rol exigido
- **WHEN** un usuario con sólo `CLIENTE` vigente llama a una ruta que exige `ADMIN` o `RECEPCION`
- **THEN** la respuesta es 403 `{"detail": "No tiene permiso para realizar esta operación"}`

#### Scenario: Rol revocado con la sesión abierta
- **WHEN** a un usuario se le revoca su único rol exigido después del login y repite la petición con la misma cookie
- **THEN** la respuesta es 403, aunque el token todavía liste ese rol

#### Scenario: Rol vencido
- **WHEN** la asignación del rol exigido tiene `vence_en` en el pasado
- **THEN** la respuesta es 403

#### Scenario: Rol abierto después del login
- **WHEN** a un usuario se le abre el rol exigido después del login, sin volver a iniciar sesión
- **THEN** la petición siguiente con la misma cookie se ejecuta, aunque el token no liste ese rol

#### Scenario: ADMIN no es comodín
- **WHEN** un usuario con sólo `ADMIN` vigente llama a una ruta que exige únicamente `MECANICO`
- **THEN** la respuesta es 403

### Requirement: Orden de los rechazos
En una ruta protegida, los controles SHALL evaluarse en este orden y responder con el primero que falle: sesión (401), cambio de contraseña pendiente (403), roles (403), y recién después la validación de parámetros y cuerpo (422) y la operación. Un cuerpo que no es JSON bien formado MUST responder 422 antes que cualquier control de sesión.

#### Scenario: Sin sesión y sin rol
- **WHEN** se llama sin cookie a una ruta que exige `ADMIN`
- **THEN** la respuesta es 401, no 403

#### Scenario: Cambio pendiente y sin rol
- **WHEN** un usuario con cambio pendiente y sin el rol exigido llama a la ruta
- **THEN** la respuesta es 403 con el mensaje del cambio pendiente

#### Scenario: Sin sesión y con parámetros inválidos
- **WHEN** se llama sin cookie a una ruta protegida con un parámetro de ruta que no es entero
- **THEN** la respuesta es 401, no 422

#### Scenario: Con sesión y con parámetros inválidos
- **WHEN** se llama con una sesión válida y el rol exigido a la misma ruta con un parámetro de ruta que no es entero
- **THEN** la respuesta es 422 y el handler no se ejecuta

#### Scenario: JSON mal formado sin sesión
- **WHEN** se envía sin cookie un cuerpo que no es JSON válido a una ruta que exige sesión
- **THEN** la respuesta es 422 por JSON inválido
