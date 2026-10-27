# Spec Delta — auth-session

## Purpose

Define cómo se identifica al usuario de cada petición a partir de la cookie de sesión, cuándo una sesión deja de valer (RN07) y qué devuelve `GET /auth/yo`. Es la base sobre la que se deciden los permisos (`access-control`).

## ADDED Requirements

### Requirement: Sesión leída sólo de la cookie
Toda ruta que exija autenticación SHALL tomar el token únicamente de la cookie `access_token`. Sin esa cookie, o con la cookie vacía, la petición MUST responder 401 `{"detail": "Se requiere iniciar sesión"}`. El encabezado `Authorization` MUST ignorarse siempre, traiga lo que traiga.

#### Scenario: Sin cookie
- **WHEN** se llama a `GET /auth/yo` sin cookie
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`

#### Scenario: Token válido en Authorization Bearer
- **WHEN** se llama a `GET /auth/yo` sin cookie y con `Authorization: Bearer <token>`, donde `<token>` es el valor de una cookie recién entregada por el login
- **THEN** la respuesta es el mismo 401 que sin cookie

#### Scenario: Cookie y Authorization a la vez
- **WHEN** la petición trae una cookie válida y además `Authorization: Bearer basura`
- **THEN** se autentica con la cookie y el encabezado no cambia el resultado

#### Scenario: Cookie vacía
- **WHEN** la petición trae `Cookie: access_token=`
- **THEN** la respuesta es 401 `{"detail": "Se requiere iniciar sesión"}`

### Requirement: Sesión rechazada por token o por cuenta
Con cookie presente, la petición SHALL responder 401 `{"detail": "La sesión no es válida o venció"}` si el token es inválido, está alterado, venció o fue firmado con otra clave; si el usuario del token no existe; o si está inactivo. El mismo cuerpo MUST usarse en todos estos casos, sin revelar cuál ocurrió.

#### Scenario: Token alterado
- **WHEN** la cookie trae un token con un carácter cambiado
- **THEN** la respuesta es 401 `{"detail": "La sesión no es válida o venció"}`

#### Scenario: Token vencido
- **WHEN** la cookie trae un token cuyo `exp` ya pasó
- **THEN** la respuesta es el mismo 401

#### Scenario: Usuario inexistente
- **WHEN** la cookie trae un token bien firmado cuyo `sub` no corresponde a ningún usuario
- **THEN** la respuesta es el mismo 401

#### Scenario: Usuario desactivado con la sesión abierta
- **WHEN** un usuario inicia sesión y después su cuenta pasa a `activo` falso
- **THEN** la petición siguiente con la misma cookie responde el mismo 401

### Requirement: Sesiones anteriores al cambio de contraseña
Si el usuario tiene `password_cambiada_en`, una sesión cuyo `iat` sea anterior a ese instante SHALL responder 401 `{"detail": "La sesión no es válida o venció"}`. La comparación MUST hacerse con la fracción de segundo completa de ambos valores, sin truncar; un `iat` igual o posterior al cambio MUST valer (RN07).

#### Scenario: Sesión del mismo segundo, anterior al cambio
- **WHEN** un usuario inicia sesión y, dentro del mismo segundo, cambia su contraseña
- **THEN** la cookie del login responde 401 aunque su `iat` y `password_cambiada_en` coincidan al segundo

#### Scenario: Usuario que nunca cambió la contraseña
- **WHEN** el usuario tiene `password_cambiada_en` nulo
- **THEN** su sesión vale mientras el token sea válido y la cuenta esté activa

#### Scenario: Sesión posterior al cambio
- **WHEN** el usuario inicia sesión después de haber cambiado la contraseña
- **THEN** la cookie del nuevo login vale

### Requirement: Datos de la sesión actual
`GET /auth/yo` SHALL estar en el grupo abierto, exigir sesión válida y responder 200 con `{id, email, nombre, debe_cambiar_password, roles_vigentes, roles_token}`: `roles_vigentes` consultados en la base en esa petición y `roles_token` tal como los trae el token. La respuesta MUST NOT incluir `password_hash`, el token ni otros datos de la cuenta.

#### Scenario: Usuario recién registrado
- **WHEN** un cliente registrado e iniciado llama a `GET /auth/yo`
- **THEN** la respuesta es 200 con su id, correo y nombre, `debe_cambiar_password: false`, `roles_vigentes: ["CLIENTE"]` y `roles_token: ["CLIENTE"]`

#### Scenario: Roles cambiados después del login
- **WHEN** después del login se revoca un rol del usuario o se le abre uno nuevo
- **THEN** `roles_vigentes` refleja la base en esa petición y `roles_token` sigue mostrando los roles del login

#### Scenario: Cambio de contraseña pendiente
- **WHEN** un usuario con `debe_cambiar_password` verdadero llama a `GET /auth/yo`
- **THEN** la respuesta es 200 con `debe_cambiar_password: true`, no 403

#### Scenario: Sin sesión válida
- **WHEN** se llama a `GET /auth/yo` sin cookie o con una sesión rechazada
- **THEN** la respuesta es el 401 correspondiente y no se lee ningún rol
