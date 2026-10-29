# Proposal — C-10 clientes-vehiculos

## Why

Con C-08 y C-09 el grupo protegido ya autoriza por roles vigentes, pero el taller todavía no puede atender a nadie: la recepción no tiene cómo dar de alta la ficha de un cliente sin usuario (Jorge), ni registrar sus vehículos, ni darlos de baja cuando se venden, y un cliente autenticado no puede ver sus propios vehículos. Sin este módulo quedan sin cumplir RN01 (documento único, patente única entre vigentes), RN16 (baja lógica y bloqueo de la baja con órdenes abiertas según `es_final`) y RN17 (lo propio sólo pide sesión), falta el caso PDF C-19, y C-13/C-15 no tienen vehículos sobre los que abrir y leer órdenes.

## What Changes

- `POST /clientes` (RECEPCION, ADMIN): alta de una ficha de cliente sin usuario con `{nombre, documento, telefono}` (mismas reglas de recorte y largo que el registro de C-07). Documento repetido → 409 con mensaje propio, decidido por `uq_cliente_documento` sin consulta previa.
- `GET /clientes/{id}` (RECEPCION, ADMIN): la ficha con sus vehículos **vigentes**, precargados en el mismo método del repositorio (`selectinload` con criterio de vigencia), en orden de id. Cliente inexistente → 404.
- `POST /clientes/{id}/vehiculos` (RECEPCION, ADMIN): alta de un vehículo `{patente, marca, modelo, anio}`; la patente se normaliza (sin espacios ni guiones, en mayúsculas) y debe tener 6–8 letras o dígitos; `anio` 1950–2100 validado en el contrato (422). Cliente inexistente → 404; patente de otro vehículo vigente → 409 con mensaje propio, decidido por el índice único parcial `uq_vehiculo_patente`.
- `DELETE /vehiculos/{id}` (RECEPCION, ADMIN): baja lógica (`borrado_en`) → 204 sin cuerpo. Inexistente o ya dado de baja → 404. Con alguna orden en un estado que el catálogo `estado_orden` no marca `es_final` → 409 (RN16), con la fila del vehículo bloqueada durante la verificación. La patente queda libre para otro vehículo (PDF C-19).
- `GET /mis-vehiculos` (cualquier usuario autenticado): los vehículos vigentes de la ficha vinculada al usuario de la sesión, nunca los de otro (RN17); sin ficha → lista vacía. Arreglo simple, sin paginar (la matriz sólo lista 200).
- Módulo `app/modules/clientes/` completo (`schemas`, `repository`, `unit_of_work`, `service`, `router`), siguiendo el patrón Router → Service → UoW → Repository de `usuarios`; `main.py` monta sus tres routers en `rutas_protegidas`.
- `test/clientes.http` (nuevo): todos los casos del change, incluido el PDF C-19, con su propio estado conocido (limpieza `psql`, catálogo de estados y órdenes de prueba insertados por `psql`, porque C-06 y C-13 no existen todavía).

Fuera de alcance: modificar o borrar fichas de cliente, vincular una ficha existente a un usuario, editar vehículos, listar clientes, `seed.py` (C-06), cualquier ruta de órdenes (C-13…C-15) y el código de `app/modules/ordenes/` (sólo se leen sus modelos). El registro de C-07 (`UsuariosUoW` con `BaseRepository(session, Cliente)`) no se toca.

## Capabilities

### New Capabilities
- `customer-records`: fichas de cliente del taller administradas por el personal (`POST /clientes`, `GET /clientes/{id}`): quién puede, contrato, unicidad del documento y detalle con vehículos vigentes.
- `customer-vehicles`: vehículos de una ficha (`POST /clientes/{id}/vehiculos`, `DELETE /vehiculos/{id}`, `GET /mis-vehiculos`): contrato y normalización de la patente, unicidad entre vigentes, baja lógica bloqueada por órdenes abiertas según el catálogo (RN16) y consulta de lo propio (RN17).

### Modified Capabilities
(ninguna: `access-control`, `api-contracts`, `data-repositories`, `domain-data-model`, `error-translation`, `unit-of-work` y `auth-registration` se usan tal como están)

## Impact

- **Código nuevo**: `app/modules/clientes/{schemas,repository,unit_of_work,service,router}.py`, `test/clientes.http`.
- **Código modificado**: `main.py` (import de los tres routers y tres `rutas_protegidas.include_router(...)` antes de `app.include_router(rutas_protegidas)`, con el comentario de C-09 actualizado).
- **Sin cambios**: `app/core/*` (sólo Mati lo modifica; todo lo necesario existe: `SoftDeleteRepository`, `UnitOfWork`, `requiere_rol`, `UsuarioActualDep`, `IdRuta`, errores), modelos y migraciones (columnas, `uq_cliente_documento`, `uq_vehiculo_patente`, `ck_vehiculo_anio_rango` e índices existen desde C-03), `app/modules/usuarios/*`, `app/modules/ordenes/*`, `test/solo_agregado.sql`.
- **Dependencias**: ninguna nueva.
- **Downstream**: C-13 verifica "vehículo vigente" con `VehiculoRepository` y debe bloquear la fila del vehículo igual que la baja (design.md, Notas para C-13); C-15 usa la relación vehículo → cliente → usuario para la comprobación de dueño; C-06 carga a Laura y Jorge con patentes ya normalizadas; C-16 integra `test/clientes.http`.
- **Governance**: MEDIO. Se implementa por tareas con checkpoints; los supuestos S-01…S-18 de `design.md` están **confirmados por el usuario el 2026-10-29**.
