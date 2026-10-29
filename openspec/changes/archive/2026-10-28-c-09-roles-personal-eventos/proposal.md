# Proposal — C-09 roles-personal-eventos

## Why

C-08 dejó lista la autorización (`requiere_rol`, grupo `rutas_protegidas`), pero el grupo protegido está vacío y nadie puede administrar al personal: no hay forma de dar de alta un empleado con contraseña provisoria, de asignarle o revocarle un rol con vigencia, ni de consultar el historial de seguridad. Sin eso quedan sin cumplir RN03 (una asignación abierta por rol, 409), RN05 (autoprotección del ADMIN y siempre al menos un administrador vigente sin vencimiento) y la parte del Ejercicio 5 que pide que el historial de seguridad registre altas y cambios de rol; tampoco hay evidencia `.http` sobre una ruta protegida real de los casos PDF C-07 (revocar o vencer un rol → 403 con la misma cookie; vencimientos inválidos → 422), C-08 (autoprotección) y C-09 (403 por cambio pendiente fuera de `/auth`), que C-08 difirió acá (S-05, S-06).

## What Changes

- `POST /usuarios` (ADMIN): alta de personal con contraseña provisoria; el usuario nace activo, con `debe_cambiar_password = true` y sin roles. Correo repetido → 409 con mensaje propio. El hash se calcula antes de abrir la transacción y el alta queda en `evento_seguridad` en el mismo Unit of Work.
- `POST /usuarios/{id}/roles` (ADMIN): asigna un rol con vencimiento opcional; el vencimiento sin zona horaria o no futuro → 422; el mismo rol ya vigente → 409 (RN03, garantizado por el índice único parcial existente); un rol abierto pero vencido se cierra (`revocada_en`) y se abre una fila nueva en la misma transacción. Usuario inexistente → 404.
- `GET /usuarios/{id}/roles` (ADMIN): roles vigentes del usuario y el historial completo de sus asignaciones (revocadas y vencidas incluidas). Usuario inexistente → 404.
- `DELETE /usuarios/{id}/roles/{rol}` (ADMIN): revoca sin borrar (escribe `revocada_en`). Sin ese rol vigente → 404. Un ADMIN no puede revocarse su propio ADMIN → 409 (RN05). Revocar `ADMIN` responde 409 si después no quedaría al menos un ADMIN vigente **sin vencimiento** de un usuario activo (los ADMIN con `vence_en` no cuentan), también con revocaciones simultáneas (bloqueo de filas en la transacción). Asignar `ADMIN` con vencimiento sigue permitido.
- `GET /eventos?page&size` (ADMIN): historial de seguridad paginado con el envoltorio común, del más reciente al más antiguo.
- `evento_seguridad` registra, con el correo del ADMIN como actor, cada alta de personal, asignación (incluida la reasignación de un rol vencido) y revocación, atómico con la operación. El evento de cambio de contraseña ya lo escribe C-08; el de datos iniciales (actor `SISTEMA`) es de C-06.
- `main.py`: los routers `/usuarios` y `/eventos` se montan en `rutas_protegidas` **antes** de `app.include_router(rutas_protegidas)`, con `requiere_rol(Rol.ADMIN)` a nivel de router.
- `test/personal.http` (nuevo): casos de este change y la evidencia diferida de C-08: 401 sin sesión, 403 por cambio pendiente y 403 por rol sobre una ruta protegida real (PDF C-09), PDF C-07 y C-08.
- No existe `GET /usuarios` (IN-02): el listado de usuarios no se implementa.

Fuera de alcance: `seed.py` y el evento `SISTEMA` de datos iniciales (C-06); desactivar o reactivar usuarios; resetear la contraseña de otro usuario; cambiar `nombre`/`email` de un usuario; filtros en `/eventos`; restringir la asignación de `ADMIN` con vencimiento (el primer ADMIN — hoy por `psql`, después el de C-06 — debe crearse sin vencimiento) — ver design.md S-09.

## Capabilities

### New Capabilities
- `staff-accounts`: alta de personal por un ADMIN (`POST /usuarios`): contrato, contraseña provisoria con cambio obligatorio, correo repetido, alta atómica con su evento; y la ausencia deliberada de `GET /usuarios`.
- `role-assignment`: asignación con vencimiento, consulta y revocación de roles (`/usuarios/{id}/roles`): RN03, reasignación de un rol vencido, revocación sin borrar con efecto inmediato sobre sesiones abiertas, autoprotección y mínimo de un ADMIN vigente sin vencimiento, también bajo concurrencia (RN05).
- `security-events`: qué operaciones dejan línea en `evento_seguridad` (actor, acción, atomicidad) y su consulta paginada `GET /eventos`.

### Modified Capabilities
(ninguna: `access-control`, `list-pagination`, `error-translation`, `unit-of-work` y `data-repositories` se usan tal como están; ver design.md S-07 sobre el alcance de "listado" en `list-pagination`)

## Impact

- **Código modificado**: `app/modules/usuarios/{schemas,repository,unit_of_work,service,router}.py` (piezas nuevas de personal, roles y eventos, sin tocar registro/login/sesión), `main.py` (montaje en `rutas_protegidas`).
- **Código nuevo**: `test/personal.http`.
- **Sin cambios**: modelos y migraciones (el índice único parcial `uq_asignacion_rol_usuario_id_rol`, `vence_en`/`revocada_en` `timestamptz` y `evento_seguridad` existen desde C-03; no hace falta una tercera migración), `app/core/*` (`requiere_rol`, `PaginacionDep`, `Pagina`, `IdRuta`, errores 403/404/409/422 ya existen), `test/solo_agregado.sql`.
- **Dependencias**: ninguna nueva.
- **Downstream**: C-06 (seed) puede usar `POST /usuarios`/roles como referencia del formato de eventos; C-10…C-15 cuelgan sus routers de `rutas_protegidas` igual que este change; C-16 integra `test/personal.http`.
- **Governance**: CRÍTICO (gestión de roles y auditoría). Ninguna línea de código se escribe sin aprobación humana explícita del plan y de los supuestos S-01…S-13 de `design.md` (supuestos confirmados por el usuario el 2026-10-28; S-09 con la alternativa B).
