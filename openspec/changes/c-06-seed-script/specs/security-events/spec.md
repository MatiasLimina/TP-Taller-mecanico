# Spec Delta — security-events

## MODIFIED Requirements

### Requirement: Operaciones que dejan evento
`evento_seguridad` SHALL recibir una línea por cada auto-registro, alta de personal, asignación o revocación de rol aceptada y cambio de contraseña exitoso, escrita en la misma transacción que la operación, y una única línea por cada carga de los datos iniciales (`seed.py`), en la transacción de esa carga. Los intentos de login y las operaciones rechazadas MUST NOT dejar línea.

#### Scenario: Operación aceptada
- **WHEN** se acepta un alta de personal, una asignación o una revocación de rol
- **THEN** existe exactamente una línea nueva en `evento_seguridad` por esa operación

#### Scenario: Operación rechazada
- **WHEN** un alta responde 409 por correo repetido o una revocación responde 404
- **THEN** la cantidad de líneas de `evento_seguridad` no cambia

#### Scenario: Login
- **WHEN** un login responde 200 o 401
- **THEN** no se agrega ninguna línea en `evento_seguridad` (los intentos van a `intento_acceso`)

#### Scenario: Carga de los datos iniciales
- **WHEN** se ejecuta `python seed.py`
- **THEN** `evento_seguridad` queda con exactamente una línea, la de la carga, aunque el seed cree usuarios y asigne roles

### Requirement: Actor y acción del evento
Cada línea SHALL tener `cuando` con zona horaria, `actor` igual al correo normalizado de quien hizo la operación (el ADMIN en las operaciones de personal y roles; el propio usuario en el auto-registro y el cambio de contraseña) o el texto `SISTEMA` en la carga de los datos iniciales, y una `accion` en texto propio que nombra la operación y, si afecta a otro usuario, su correo y el rol. `actor` es texto, no una referencia a `usuario`.

#### Scenario: Actor de una operación de ADMIN
- **WHEN** `jefa@personal.example.com` da de alta a `nuevo@personal.example.com`
- **THEN** la línea tiene `actor` `jefa@personal.example.com` y una `accion` que nombra el alta de personal y `nuevo@personal.example.com`

#### Scenario: Actor de la carga inicial
- **WHEN** se lee la línea que deja `python seed.py`
- **THEN** tiene `actor` `SISTEMA` (que no es un usuario ni un correo) y `accion` `Carga de los datos iniciales`

#### Scenario: Sin datos secretos
- **WHEN** se lee cualquier línea de `evento_seguridad`
- **THEN** ni `actor` ni `accion` contienen contraseñas, hashes ni tokens
