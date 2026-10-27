# unit-of-work Specification

## Purpose

Fija los límites transaccionales de cada operación de negocio: todas sus escrituras se confirman juntas o ninguna, y quedan definidos quién crea, abre, confirma, revierte y cierra la sesión.

## Requirements

### Requirement: Todo o nada al salir del bloque
Una operación abierta con el Unit of Work SHALL confirmar todas sus escrituras al salir normalmente del bloque y MUST revertirlas todas si el bloque termina con una excepción, que se propaga sin modificar.

#### Scenario: Salida normal confirma
- **WHEN** dentro del bloque se escriben filas en dos tablas y el bloque termina sin error
- **THEN** ambas escrituras quedan visibles desde otra conexión

#### Scenario: Excepción revierte todo
- **WHEN** dentro del bloque se escribe una fila y luego se lanza una excepción
- **THEN** ninguna escritura del bloque queda en la base y la misma excepción llega al llamador

#### Scenario: Error de integridad a mitad del bloque
- **WHEN** la segunda de dos escrituras viola una restricción
- **THEN** tampoco queda la primera (sin filas sueltas, RN02/RN13/RN20)

### Requirement: Fallo al confirmar
Si la confirmación misma falla, el Unit of Work SHALL revertir y propagar el error, sin dejar escrituras parciales.

#### Scenario: Confirmación rechazada
- **WHEN** la confirmación falla por un error de la base
- **THEN** no queda ninguna escritura del bloque y el error se propaga

### Requirement: Un rollback fallido no oculta el error original
Si el rollback mismo falla, el Unit of Work SHALL registrar el fallo en el log del servidor (con traza y sin datos sensibles) y MUST dejar propagar sin cambios la excepción original del bloque (o el error de confirmación).

#### Scenario: Rollback que falla
- **WHEN** el bloque termina con una excepción y el rollback también lanza una excepción
- **THEN** al llamador llega la excepción original del bloque y el fallo del rollback queda en el log

### Requirement: Una sesión compartida por todos los repositorios
El Unit of Work de cada módulo SHALL componer los repositorios que sus operaciones necesitan, todos con la misma sesión que recibió.

#### Scenario: Escrituras de dos repositorios en un bloque
- **WHEN** una operación escribe con dos repositorios del mismo Unit of Work y luego falla
- **THEN** se revierten las escrituras de ambos

### Requirement: El Unit of Work no crea ni cierra la sesión
El Unit of Work SHALL recibir una sesión ya creada y MUST NOT cerrarla; la sesión la crea y la cierra la dependencia de sesión por petición.

#### Scenario: Sesión utilizable tras el bloque
- **WHEN** termina el bloque del Unit of Work
- **THEN** la sesión sigue abierta hasta que termina la petición, y entonces se cierra

### Requirement: Construido por el router, abierto por el servicio
El Unit of Work de una petición SHALL construirse por inyección de dependencias en la capa de rutas y entregarse al servicio sin abrir; el servicio MUST abrirlo y MUST NOT construirlo. Ningún repositorio confirma.

#### Scenario: Inspección del código
- **WHEN** se buscan en `app/` llamadas a `commit()` y construcciones de Unit of Work
- **THEN** `commit()` sólo aparece en el Unit of Work base (y en la sesión propia declarada de `intento_acceso`), y los Unit of Work sólo se construyen en dependencias

### Requirement: Sin apertura anidada
Abrir un Unit of Work que ya está abierto SHALL fallar como error de programación, para que un bloque interno no confirme antes de tiempo el trabajo del externo.

#### Scenario: Bloque dentro de bloque
- **WHEN** se abre el mismo Unit of Work dentro de su propio bloque
- **THEN** se lanza un error de programación y el bloque externo revierte

#### Scenario: Bloques sucesivos
- **WHEN** se abre el Unit of Work, se cierra y se vuelve a abrir en la misma petición
- **THEN** cada bloque es una transacción independiente

### Requirement: Única escritura fuera del Unit of Work
La única escritura del sistema que no comparte la transacción de su petición SHALL ser el registro de `intento_acceso`, con sesión y transacción propias que se confirman siempre; el código MUST declararlo en un comentario junto con su costo.

#### Scenario: Excepción documentada
- **WHEN** se revisa el código de escritura de `intento_acceso` (C-07)
- **THEN** usa su propia sesión, confirma siempre y tiene el comentario que declara la excepción y que deja filas aunque la petición falle
