# list-pagination Specification

## Purpose

Define los parámetros, el envoltorio y las reglas de páginas que comparten todos los listados de la API, para que cualquier cliente pagine igual en todos los módulos.

## Requirements

### Requirement: Envoltorio de listados
Todo listado SHALL responder un objeto con exactamente `items`, `total`, `page`, `size` y `pages`, donde `total` cuenta con los mismos filtros que la página y `pages` es la cantidad de páginas de tamaño `size`.

#### Scenario: Primera página
- **WHEN** hay 3 elementos que cumplen el filtro y se pide `size=2`
- **THEN** la respuesta tiene 2 `items`, `total` 3, `page` 1, `size` 2 y `pages` 2

#### Scenario: Total con filtro
- **WHEN** se filtra un listado y sólo 1 elemento cumple el filtro, con `size=1`
- **THEN** `total` es 1 y `pages` es 1

### Requirement: Parámetros de página acotados
`page` SHALL empezar en 1 con valor por defecto 1, y `size` SHALL valer entre 1 y 100 con valor por defecto 20; un valor fuera de rango o no entero MUST dar 422 sin ejecutar el listado.

#### Scenario: Valores por defecto
- **WHEN** se lista sin `page` ni `size`
- **THEN** la respuesta tiene `page` 1 y `size` 20

#### Scenario: Tamaño excesivo
- **WHEN** se pide `size=500`
- **THEN** la respuesta es 422 y no se consulta la base

#### Scenario: Página cero o no numérica
- **WHEN** se pide `page=0` o `page=abc`
- **THEN** la respuesta es 422

### Requirement: Cero resultados es una página vacía
Un listado sin resultados SHALL responder una página vacía: `items` vacío, `total` 0 y `pages` 1.

#### Scenario: Sin coincidencias
- **WHEN** ningún elemento cumple el filtro y se pide la página 1
- **THEN** la respuesta es 200 con `items` vacío, `total` 0, `page` 1 y `pages` 1

### Requirement: Página más allá de la última
Pedir una página mayor que `pages` SHALL responder 422 con el mensaje «La página N no existe: hay M», donde N es la pedida y M la cantidad de páginas.

#### Scenario: Página inexistente
- **WHEN** hay 2 páginas y se pide `page=3`
- **THEN** la respuesta es 422 con el mensaje «La página 3 no existe: hay 2»

#### Scenario: Página 2 sin resultados
- **WHEN** no hay resultados y se pide `page=2`
- **THEN** la respuesta es 422 con el mensaje «La página 2 no existe: hay 1»
