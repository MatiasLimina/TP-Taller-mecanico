# Proposal — C-02 core-repository-uow

## Why

C-01 dejó la sesión por petición (`get_session` / `SessionDep`) pero nadie confirma ni revierte: el comentario de `app/core/database.py` delega la transacción "al UoW (C-02)". Todos los módulos de dominio (C-03 en adelante) necesitan el mismo cimiento —repositorio genérico, Unit of Work, paginación, contrato de DTOs y traducción de errores— y la consigna lo evalúa explícitamente: Ej.6 "Repositorios y Unit of Work" pesa 20 % y el Ej.3 exige `extra="forbid"`, el envoltorio de listados y que ninguna entrada inválida termine en 500. Si este cimiento se arma mal, el defecto se hereda en los cinco módulos; por eso va segundo en el camino crítico (GATE 1) y con governance ALTO.

## What Changes

- `app/core/repository.py`: `BaseRepository[T]` (recibe sesión **y** clase del modelo en el constructor; `get_by_id`, `get_all`, `count`, `add`, `update`, `delete`; las escrituras hacen `flush()`, nunca `commit()`; consulta base reutilizable para que `count` use los mismos filtros que la página) y `SoftDeleteRepository[T]` (hereda; excluye los dados de baja; agrega `get_by_id_including_deleted` y `soft_delete`, que no existen en la base).
- `app/core/unit_of_work.py`: `UnitOfWork` base, gestor de contexto asincrónico que confirma al salir, revierte ante excepción, **no** cierra la sesión (no la creó) y rechaza la apertura anidada. Patrón documentado para el UoW de cada módulo (repos compuestos con la misma sesión) y para la dependencia que lo construye en el router.
- `app/core/paginacion.py`: parámetros `page` (≥ 1, def. 1) y `size` (1–100, def. 20) como dependencia, envoltorio genérico `{items, total, page, size, pages}`, cálculo de páginas (0 resultados → 1 página vacía) y 422 «La página N no existe: hay M» al pedir más allá de la última.
- Contrato de DTOs (archivo nuevo en `app/core/`): base de entrada con `extra="forbid"`, base de salida que lee atributos del modelo y **rechaza al definirse** cualquier DTO de salida que declare `password_hash`, y tipo de id de ruta acotado al rango de `INTEGER` (un id gigante da 422, no 500).
- Traducción de errores (archivo nuevo en `app/core/`): excepciones de aplicación (no encontrado → 404, conflicto → 409, entrada inválida → 422) y manejadores globales registrados en `main.py`: `IntegrityError` → 409/422 con mensaje propio según el tipo de restricción, errores de dato de la base → 422, validación de FastAPI → 422 **sin eco del valor enviado**, cualquier otro error → 500 genérico; nunca texto de la base ni traza (RN18). Utilidad para que cada módulo traduzca una restricción concreta a su mensaje (p. ej. correo repetido).
- `main.py`: registra los manejadores globales (una línea; no toca el lifespan ni los grupos de rutas).
- Sin endpoints nuevos ni tablas: los primeros consumidores reales llegan con C-03/C-07/C-10.

## Capabilities

### New Capabilities
- `data-repositories`: acceso a datos genérico por entidad: lectura por id, listado y conteo con los mismos filtros, escritura sin confirmar, borrado físico y borrado lógico con exclusión de dados de baja.
- `unit-of-work`: límites transaccionales de una operación: todo o nada, quién crea, abre, confirma, revierte y cierra.
- `list-pagination`: parámetros, envoltorio y reglas de páginas de todos los listados de la API.
- `api-contracts`: reglas comunes de los contratos de entrada y salida (campos no declarados rechazados, `password_hash` nunca expuesto, ids de ruta válidos).
- `error-translation`: forma y códigos de las respuestas de error, traducción de violaciones de integridad y garantía de que ninguna entrada inválida termina en 500 ni expone la base.

### Modified Capabilities
- (ninguna — `runtime-lifecycle` ya especifica una sesión por petición cerrada al terminar; C-02 la usa sin cambiar ese requisito)

## Impact

- **Código nuevo**: `app/core/repository.py`, `app/core/unit_of_work.py`, `app/core/paginacion.py`, `app/core/schemas.py` y `app/core/errores.py` (nombres a confirmar, ver design — Checkpoints).
- **Código modificado**: `main.py` (registro de manejadores); `app/core/database.py` sólo se toca si hace falta ajustar el comentario de `get_session`.
- **Base de datos**: ninguna migración. La verificación usa una base descartable propia (ver design D10), nunca la base de desarrollo.
- **Downstream**: C-03 (modelos con `borrado_en` timestamptz y restricciones con nombre explícito para la traducción de mensajes), C-07 (registro en un solo UoW, RN02; `intento_acceso` con sesión propia — excepción declarada, no usa este UoW), C-10/C-11/C-13 (repos, UoW por módulo, paginación), C-15 (precarga en métodos del repo), C-16 (`.http` de 409/422/paginación).
- **Equipo** (docs/REPARTO_DE_TAREAS.md): sólo el integrante A modifica `repository.py`, `unit_of_work.py` y `paginacion.py`; los contratos que se fijan acá (excepciones, DTO base, forma del error) los usan B y C, por eso se consultan antes de escribir código.
- **Nombre del change**: el CLI exige minúsculas → `c-02-core-repository-uow` (= `C-02 core-repository-uow` de CHANGES.md).
