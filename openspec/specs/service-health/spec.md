# service-health Specification

## Purpose

Expone sondas públicas que distinguen "el proceso está vivo" de "el proceso está listo para atender porque la base contesta", sin filtrar detalles internos.

## Requirements

### Requirement: Sonda de vida sin tocar la base
`GET /health/live` SHALL responder 200 con un cuerpo JSON mientras el proceso atienda, sin consultar la base de datos. El endpoint SHALL ser público (no requiere cookie).

#### Scenario: Vivo con la base arriba
- **WHEN** se llama `GET /health/live` con PostgreSQL disponible
- **THEN** la respuesta es 200 con un JSON que indica que el proceso está vivo

#### Scenario: Vivo con la base caída
- **WHEN** se llama `GET /health/live` con PostgreSQL apagado
- **THEN** la respuesta sigue siendo 200 y no se intenta ninguna conexión

### Requirement: Sonda de disponibilidad con SELECT 1
`GET /health/ready` SHALL ejecutar `SELECT 1` contra la base y responder 200 si contesta, o 503 si no contesta o tarda más que un límite acotado de pocos segundos. El endpoint SHALL ser público.

#### Scenario: Listo
- **WHEN** se llama `GET /health/ready` con PostgreSQL disponible
- **THEN** la respuesta es 200 con un JSON que indica que la base está lista

#### Scenario: Base caída
- **WHEN** se llama `GET /health/ready` con PostgreSQL apagado o inalcanzable
- **THEN** la respuesta es 503 en pocos segundos, y `GET /health/live` sigue devolviendo 200

#### Scenario: Recuperación
- **WHEN** la base vuelve a estar disponible después de un 503
- **THEN** la siguiente llamada a `GET /health/ready` devuelve 200 sin reiniciar el proceso

### Requirement: Fallo de disponibilidad sin detalles internos
La respuesta 503 de `GET /health/ready` MUST NOT incluir texto del motor de base, del driver, host, usuario ni traza; SHALL contener sólo un mensaje propio en español.

#### Scenario: Cuerpo del 503
- **WHEN** `GET /health/ready` devuelve 503 por credenciales incorrectas o host inexistente
- **THEN** el cuerpo es un JSON con un mensaje propio, sin nombres de host, usuarios ni texto del driver
