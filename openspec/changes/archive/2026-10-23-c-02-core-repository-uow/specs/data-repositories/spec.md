# Spec Delta — data-repositories

## Purpose

Define el acceso a datos genérico que comparten todas las entidades: lectura por id, listado y conteo coherentes, escrituras que nunca confirman la transacción, y borrado lógico que oculta los dados de baja sin perder sus datos.

## ADDED Requirements

### Requirement: Repositorio ligado a una sesión y a una entidad
Cada repositorio SHALL operar sobre una única sesión y una única entidad, ambas recibidas al construirlo; dos repositorios construidos con la misma sesión MUST ver las escrituras no confirmadas del otro.

#### Scenario: Repositorios que comparten sesión
- **WHEN** un repositorio agrega una fila y otro repositorio construido con la misma sesión la busca por id antes de confirmar
- **THEN** la encuentra

#### Scenario: Otra conexión no ve lo no confirmado
- **WHEN** un repositorio agregó una fila y la transacción todavía no se confirmó
- **THEN** una consulta desde otra conexión no ve esa fila

### Requirement: Escrituras sin confirmar
Agregar, actualizar y borrar SHALL enviar el cambio a la base dentro de la transacción en curso (de modo que las restricciones se evalúen en ese momento y los ids generados queden disponibles) y MUST NOT confirmar la transacción.

#### Scenario: Id disponible tras agregar
- **WHEN** se agrega una entidad nueva sin id
- **THEN** al volver la operación la entidad tiene el id asignado por la base

#### Scenario: Restricción violada al escribir
- **WHEN** se agrega una entidad que viola una restricción de unicidad
- **THEN** el error de integridad se produce en esa misma operación, no recién al confirmar

#### Scenario: Revertir deshace lo escrito
- **WHEN** se agrega, actualiza o borra una fila y luego la transacción se revierte
- **THEN** la base queda como estaba antes

### Requirement: Lectura por id
Buscar por id SHALL devolver la entidad si existe y nada (ausencia, no error) si no existe.

#### Scenario: Id existente
- **WHEN** se busca por id una fila existente
- **THEN** se obtiene esa entidad

#### Scenario: Id inexistente
- **WHEN** se busca por id un valor que no está en la tabla
- **THEN** se obtiene ausencia y no se lanza error

### Requirement: Listado y conteo con los mismos filtros
Listar SHALL devolver las entidades en un orden determinista (por id ascendente salvo que el método declare otro) admitiendo desplazamiento y límite; contar MUST aplicar exactamente los mismos filtros que el listado, sin desplazamiento ni límite.

#### Scenario: Página intermedia
- **WHEN** hay 5 filas y se lista con desplazamiento 2 y límite 2
- **THEN** se obtienen las filas 3 y 4 en orden de id, y el conteo da 5

#### Scenario: Tabla vacía
- **WHEN** la tabla no tiene filas
- **THEN** el listado es vacío y el conteo es 0

### Requirement: Actualización parcial
Actualizar SHALL modificar sólo los campos recibidos y dejar intactos los demás; MUST rechazar, sin escribir, un campo que la entidad no tiene o el intento de cambiar el id.

#### Scenario: Sólo cambia lo enviado
- **WHEN** se actualiza una entidad enviando sólo un campo
- **THEN** ese campo cambia y el resto conserva su valor

#### Scenario: Campo desconocido
- **WHEN** se intenta actualizar un campo que la entidad no declara
- **THEN** la operación falla como error de programación y no se escribe nada

### Requirement: Borrado físico
Borrar SHALL eliminar la fila dentro de la transacción en curso; una restricción de clave foránea que lo impida MUST manifestarse en esa operación.

#### Scenario: Borrar una fila
- **WHEN** se borra una entidad y se confirma
- **THEN** buscarla por id da ausencia

### Requirement: Dados de baja ocultos
En las entidades con borrado lógico, la lectura por id, el listado y el conteo SHALL excluir las filas con fecha de baja; MUST existir una lectura por id explícita que también devuelva las dadas de baja.

#### Scenario: Baja oculta en lecturas comunes
- **WHEN** una fila tiene fecha de baja
- **THEN** no aparece al buscarla por id, ni en el listado, ni en el conteo

#### Scenario: Lectura incluyendo bajas
- **WHEN** se busca por id una fila dada de baja con la lectura que incluye bajas
- **THEN** se obtiene la entidad con su fecha de baja y todos sus datos

### Requirement: Borrado lógico
Dar de baja SHALL registrar la fecha y hora actuales con zona horaria y conservar la fila con todos sus datos; MUST NOT borrar físicamente ni confirmar la transacción. Sólo existe en los repositorios de entidades con borrado lógico.

#### Scenario: Baja conserva los datos
- **WHEN** se da de baja una entidad y se confirma
- **THEN** la fila sigue en la tabla con su fecha de baja en UTC con zona y sus demás columnas sin cambios

#### Scenario: Entidad sin borrado lógico
- **WHEN** se usa el repositorio genérico de una entidad sin fecha de baja
- **THEN** no ofrece la operación de baja lógica ni la lectura incluyendo bajas

### Requirement: Consultas sin SQL armado ni carga perezosa
Toda consulta de un repositorio SHALL pasar los valores como parámetros ligados; las relaciones que una lectura devuelva MUST precargarse en el mismo método que hace la lectura, nunca por carga perezosa posterior.

#### Scenario: Valor malicioso como dato
- **WHEN** se busca con un texto como `' OR '1'='1`
- **THEN** se trata como valor literal y no devuelve filas que no coincidan

#### Scenario: Consultas visibles en consola
- **WHEN** la aplicación corre con `SQL_ECHO=true` y un repositorio lista entidades
- **THEN** la consola muestra la consulta con marcadores de parámetro y los valores aparte
