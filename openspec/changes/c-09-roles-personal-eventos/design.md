# Design — C-09 roles-personal-eventos

## Context

Estado actual (motivación en proposal.md — Why):

- **Autorización (C-08)**: `app/core/dependencies.py` tiene `UsuarioActualDep` y `requiere_rol(*roles)`; la dependencia interna ya pide `exigir_password_al_dia`, así que el orden 401 → 403 cambio → 403 rol vale aunque se use a nivel de router. `requiere_rol` abre el `UsuariosUoW` de la petición (caché por petición: el handler recibe la misma instancia y abre bloques **sucesivos**, nunca anidados). `main.py` tiene `rutas_protegidas = APIRouter(dependencies=[Depends(exigir_password_al_dia)])`, vacío, y el comentario que obliga a incluir los routers antes de `app.include_router(rutas_protegidas)`.
- **Modelo (C-03)**: `AsignacionRol(id, usuario_id, rol, desde, vence_en, revocada_en, otorgada_por)` con `UTCDateTime` (`timestamptz`), CHECK `ck_asignacion_rol_rol_valido` e índice único parcial `uq_asignacion_rol_usuario_id_rol (usuario_id, rol) WHERE revocada_en IS NULL`. **Una fila vencida sigue "abierta" para el índice**: por eso reasignar un rol vencido obliga a cerrar la fila previa antes de insertar (lo que pide la consigna). `EventoSeguridad(id, cuando, actor, accion)` sin restricciones. No hace falta migración.
- **Sólo agregado (C-04)**: el disparador cubre `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto`; **no** `evento_seguridad` ni `asignacion_rol` (ver Riesgos).
- **Módulo usuarios (C-07/C-08)**: `UsuarioRepository.get_by_id/get_by_email`, `AsignacionRolRepository.roles_vigentes(usuario_id, ahora)` (sólo la columna), `UsuariosUoW` con `usuarios`, `asignaciones`, `intentos`, `clientes` y `eventos = BaseRepository(session, EventoSeguridad)`; `schemas.py` con `CorreoNormalizado`, `PasswordRegistro`, `Nombre`; `service.py` con `MENSAJE_CORREO_REPETIDO`, `MENSAJE_SIN_PERMISO`, `UsuarioActual(id, email, …)`; `router.py` con un solo `router` (`/auth`, grupo abierto).
- **Core**: `PaginacionDep`, `Pagina[T]`, `verificar_pagina`, `armar_pagina` (C-02); `IdRuta` (1..2147483647); `NoEncontrado`/`Conflicto`/`SinPermiso`/`EntradaInvalida`; `restriccion_violada(exc)`; `get_session` con `expire_on_commit=False` (identity map: una relectura simple no refresca una instancia ya cargada).
- **Sin seed (C-06 pendiente)**: no hay ningún ADMIN en una base recién migrada; los `.http` se preparan con `/auth/registro` + `psql`, como `test/sesion.http`. Ese primer ADMIN se crea **sin `vence_en`** (RN05 con la regla de S-09).

## Goals / Non-Goals

**Goals:**

- Montar las primeras rutas reales de `rutas_protegidas` y dejar el patrón que copian C-10…C-15.
- RN03 garantizado por la base (índice parcial) con traducción a 409 propio; RN05 garantizado por el servicio **también bajo concurrencia**, sin migraciones.
- Cada escritura (alta, asignación, revocación) atómica con su línea de `evento_seguridad`.
- bcrypt del alta fuera de toda transacción (DD-06).

**Non-Goals:**

- Restringir la asignación de `ADMIN` con vencimiento (se permite; S-09), desactivar usuarios, resetear contraseñas ajenas, editar usuarios, filtros de `/eventos`, `GET /usuarios` (IN-02).
- Proteger `evento_seguridad` contra `UPDATE`/`DELETE` en la base (requeriría tocar la migración del disparador; la consigna fija dos migraciones).

## Decisions

### D1 — Dónde vive cada pieza (estructura obligatoria del módulo)

| Archivo | Contenido nuevo |
|---------|-----------------|
| `app/modules/usuarios/schemas.py` | `PersonalAltaEntrada`, `PersonalSalida`, `AsignacionRolEntrada` (+ tipo `Vencimiento`), `AsignacionSalida`, `RolesUsuarioSalida`, `EventoSalida` |
| `app/modules/usuarios/repository.py` | `AsignacionRolRepository.abierta_para_actualizar`, `.admins_sin_vencimiento_para_actualizar`, `.historial`; `EventoSeguridadRepository.listar_recientes` |
| `app/modules/usuarios/unit_of_work.py` | `self.eventos = EventoSeguridadRepository(session)` (antes `BaseRepository`) |
| `app/modules/usuarios/service.py` | `alta_personal`, `asignar_rol`, `roles_de_usuario`, `revocar_rol`, `listar_eventos`; mensajes y acciones |
| `app/modules/usuarios/router.py` | `router_personal` (`/usuarios`) y `router_eventos` (`/eventos`), ambos con `dependencies=[Depends(solo_admin)]` |
| `main.py` | `rutas_protegidas.include_router(router_personal)` y `(router_eventos)` **antes** de `app.include_router(rutas_protegidas)` |
| `test/personal.http` | casos del change (D9) |

`app/core/*` no cambia. Ver S-12.

### D2 — Una sola instancia de `requiere_rol(Rol.ADMIN)`

```python
# router.py
solo_admin = requiere_rol(Rol.ADMIN)                     # UNA función: FastAPI la cachea por petición
AdminDep = Annotated[UsuarioActual, Depends(solo_admin)]

router_personal = APIRouter(prefix="/usuarios", tags=["personal"], dependencies=[Depends(solo_admin)])
router_eventos  = APIRouter(prefix="/eventos",  tags=["eventos"],  dependencies=[Depends(solo_admin)])

@router_personal.post("", status_code=201)
async def alta(datos: PersonalAltaEntrada, actual: AdminDep, uow: UsuariosUoWDep) -> PersonalSalida: ...
```

- A nivel de router, ninguna ruta nueva se olvida del rol; el handler pide `AdminDep` (la **misma** función) para recibir al actor, sin una segunda consulta de roles.
- Por petición autorizada: 1 `SELECT` de usuario (`autenticar`) + 1 de roles (`exigir_roles`) + lo de la operación.
- *Alternativa descartada*: `Depends(requiere_rol(Rol.ADMIN))` en cada ruta — cada llamada crea otra función, FastAPI no la cachea con la del router y se consultan los roles dos veces.

### D3 — `POST /usuarios` (spec `staff-accounts`)

```
password_hash = await hash_password(datos.password_provisoria)      # ANTES del bloque (DD-06)
try:
    async with uow:
        usuario = await uow.usuarios.add(Usuario(email, nombre, password_hash, debe_cambiar_password=True))
        await uow.eventos.add(EventoSeguridad(actor=actual.email, accion=f"Alta de personal: {usuario.email}"))
        salida = PersonalSalida.model_validate(usuario)              # adentro, con valores cargados
except IntegrityError as exc:
    if restriccion_violada(exc) == "uq_usuario_email": raise Conflicto(MENSAJE_CORREO_REPETIDO) from None
    raise
```

- Sin consulta previa del correo: la decide `uq_usuario_email` (también con altas simultáneas → 409).
- Sin roles ni ficha (S-02, S-03). `activo` toma el default `true`.

### D4 — `POST /usuarios/{id}/roles` (asignar, reasignar vencido)

```python
Vencimiento = Annotated[datetime, AfterValidator(_vencimiento_valido)]
# _vencimiento_valido: tzinfo/utcoffset nulos → ValueError("El vencimiento debe indicar la zona horaria")
#                      <= datetime.now(UTC)   → ValueError("El vencimiento debe ser una fecha futura")
#                      devuelve valor.astimezone(UTC)

class AsignacionRolEntrada(EntradaBase):
    rol: Rol
    vence_en: Vencimiento | None = None
```

```
ahora = datetime.now(UTC)
try:
    async with uow:
        usuario = await uow.usuarios.get_by_id(id)              → None: NoEncontrado("El usuario no existe")
        abierta = await uow.asignaciones.abierta_para_actualizar(id, rol)   # SELECT … FOR UPDATE
        if abierta and _vigente(abierta, ahora):               → Conflicto(f"El usuario ya tiene el rol {rol} vigente")
        if abierta:                                            # abierta pero vencida → cerrarla (flush antes del INSERT)
            await uow.asignaciones.update(abierta, {"revocada_en": ahora})
        nueva = await uow.asignaciones.add(AsignacionRol(usuario_id=id, rol=rol, desde=ahora,
                                                         vence_en=datos.vence_en, otorgada_por=actual.id))
        await uow.eventos.add(EventoSeguridad(actor=actual.email, accion=_accion_asignacion(...)))
        salida = AsignacionSalida(..., vigente=True)
except IntegrityError as exc:
    if restriccion_violada(exc) == "uq_asignacion_rol_usuario_id_rol": raise Conflicto(<mismo mensaje>) from None
    raise
```

- `_vigente(a, ahora) = a.revocada_en is None and (a.vence_en is None or a.vence_en > ahora)` — misma definición que `roles_vigentes` (una sola función en el servicio para `vigente` de las salidas).
- `abierta_para_actualizar(usuario_id, rol)`: `WHERE usuario_id = :id AND rol = :rol AND revocada_en IS NULL … FOR UPDATE`, con `populate_existing=True` (la fila puede estar en el identity map). Con dos reasignaciones simultáneas del mismo vencido, la segunda espera el bloqueo; al seguir, PostgreSQL reevalúa el `WHERE` (la fila ya está cerrada → no la devuelve) y su `INSERT` choca con la fila nueva de la primera → 409. Con dos asignaciones nuevas simultáneas, el índice parcial decide → 409.
- El 409 se traduce **fuera** del bloque (el rollback ya ocurrió); el mensaje usa `rol` del contrato, no atributos de entidades expiradas.
- `update` genérico hace `flush()`: el `UPDATE` de cierre llega a la base antes del `INSERT` y el índice no lo rechaza.

### D5 — `DELETE /usuarios/{id}/roles/{rol}` y RN05 bajo concurrencia

```
ahora = datetime.now(UTC)
async with uow:
    usuario = await uow.usuarios.get_by_id(id)                   → None: 404 "El usuario no existe"
    if rol is Rol.ADMIN and id == actual.id:                     → 409 autoprotección
    if rol is Rol.ADMIN:
        permanentes = await uow.asignaciones.admins_sin_vencimiento_para_actualizar()   # PRIMERO el conjunto
        #  SELECT asignacion_rol.* FROM asignacion_rol JOIN usuario ON …
        #  WHERE rol='ADMIN' AND revocada_en IS NULL AND vence_en IS NULL AND usuario.activo
        #  ORDER BY asignacion_rol.id FOR UPDATE OF asignacion_rol           (populate_existing)
    objetivo = await uow.asignaciones.abierta_para_actualizar(id, rol)   # DESPUÉS la fila objetivo
    if objetivo is None or not _vigente(objetivo, ahora):       → 404 "El usuario no tiene el rol {rol} vigente"
    if rol is Rol.ADMIN and not any(a.id != objetivo.id for a in permanentes):
                                                                 → 409 "quedaría sin administradores vigentes sin vencimiento"
    await uow.asignaciones.update(objetivo, {"revocada_en": ahora})
    await uow.eventos.add(EventoSeguridad(actor=actual.email, accion=f"Revocación del rol {rol} a {usuario.email}"))
    salida = AsignacionSalida(..., vigente=False)
```

- **Regla (S-09, alternativa B)**: después de revocar debe quedar al menos una asignación `ADMIN` **vigente sin vencimiento** (`vence_en IS NULL`, `revocada_en IS NULL`, dueño con `usuario.activo`). Las asignaciones `ADMIN` con `vence_en` **no cuentan**: el objetivo puede tenerlo o no, pero sólo las filas permanentes distintas del objetivo sostienen el invariante. Si no existe ningún ADMIN sin vencimiento, **toda** revocación de `ADMIN` responde 409 (comportamiento buscado). Asignar `ADMIN` con `vence_en` sigue permitido, sin regla extra.
- **El 409 es alcanzable secuencialmente**: un ADMIN con `vence_en` (A1) revoca a A2, el único ADMIN sin vencimiento → el conjunto bloqueado es `{A2}`, sin contar al objetivo queda vacío → 409. En cambio, si el actor no tiene vencimiento, él mismo queda en el conjunto (no puede ser el objetivo: autoprotección) y la revocación pasa.
- **Por qué hace falta el bloqueo**: la carrera — A revoca a B mientras B revoca a A, siendo los dos únicos ADMIN sin vencimiento; sin bloqueo ambos ven al otro en el conjunto y confirman → 0 permanentes. Con `FOR UPDATE` sobre **todas** las filas ADMIN vigentes sin vencimiento de usuarios activos, en orden de id, la segunda transacción espera; al seguir, PostgreSQL (READ COMMITTED) reevalúa el `WHERE` y descarta la fila que la primera revocó → el conjunto es `{su propia fila}`, que es el objetivo → 409.
- **Orden de bloqueo sin interbloqueos**: toda revocación de `ADMIN` bloquea primero el conjunto (orden de id) y después la fila objetivo. Si el objetivo es permanente ya está bloqueado; si tiene `vence_en`, queda fuera del conjunto y se bloquea después, siempre en ese orden. Las asignaciones bloquean una sola fila. Al revés (objetivo primero) dos revocaciones cruzadas se esperarían mutuamente (`40P01` → 500).
- Una asignación ADMIN sin vencimiento confirmada en paralelo no aparece en el conjunto bloqueado: sólo hace la cuenta más estricta (lado seguro).
- Orden de los rechazos fijo: 404 usuario → 409 autoprotección → 404 rol no vigente → 409 sin administradores sin vencimiento. La autoprotección va antes que buscar la fila: un ADMIN que pide revocarse recibe siempre el mensaje de autoprotección.
- *Alternativa*: `pg_advisory_xact_lock(<constante>)` antes de contar — más simple de leer y serializa también asignaciones si se quisiera, pero bloquea por una clave mágica que nada en el esquema documenta y serializa revocaciones de ADMIN que no compiten. *Alternativa*: aislamiento `SERIALIZABLE` en esta transacción — correcto, pero obliga a reintentar ante `40001` (hoy un 500) y el UoW no tiene esa política. Ver S-08.

### D6 — `GET /usuarios/{id}/roles`

Un bloque: `get_by_id` (404) y `asignaciones.historial(id)` (`ORDER BY desde, id`, entidades sin relaciones). Arma `RolesUsuarioSalida(usuario_id, email, nombre, roles_vigentes=sorted({a.rol for a in filas if _vigente(a, ahora)}), asignaciones=[…])`. Sin paginar (S-07).

### D7 — `GET /eventos`

`EventoSeguridadRepository.listar_recientes(offset, limit)` parte de `_consulta_base()` con `ORDER BY id DESC`; el total con `count()` heredado (mismos filtros: ninguno). Servicio con el flujo de `paginacion.py`: `total` → `verificar_pagina` → página → `armar_pagina([EventoSalida.model_validate(e) …])`. `PaginacionDep` da el 422 de `size`/`page` fuera de rango sin consultar la base.

### D8 — Mensajes, acciones y contratos de salida

| Situación | Código | `detail` |
|-----------|--------|----------|
| Usuario de la ruta inexistente | 404 | `El usuario no existe` |
| Rol ya vigente (también por la carrera del índice) | 409 | `El usuario ya tiene el rol <ROL> vigente` |
| Revocar un rol no vigente | 404 | `El usuario no tiene el rol <ROL> vigente` |
| ADMIN revoca su ADMIN | 409 | `Un administrador no puede revocarse su propio rol ADMIN` |
| Revocación de ADMIN que no dejaría ningún ADMIN vigente sin vencimiento | 409 | `No se puede revocar: el sistema quedaría sin administradores vigentes sin vencimiento` |
| Correo repetido en el alta | 409 | `El correo ya está registrado` (constante de C-07) |
| `vence_en` sin zona / no futuro | 422 | lista por campo con `El vencimiento debe indicar la zona horaria` / `… ser una fecha futura` |

Acciones de `evento_seguridad` (S-10): `Alta de personal: <correo>`, `Asignación del rol <ROL> a <correo>` (+ ` hasta <vence_en ISO UTC>` si vence; + ` (reemplaza una asignación vencida)` si cerró una), `Revocación del rol <ROL> a <correo>`. `actor` = `actual.email`.

Salidas (heredan `SalidaBase`): `PersonalSalida{id, email, nombre, activo, debe_cambiar_password}`, `AsignacionSalida{id, usuario_id, rol, desde, vence_en, revocada_en, otorgada_por, vigente}`, `RolesUsuarioSalida{usuario_id, email, nombre, roles_vigentes, asignaciones: list[AsignacionSalida]}`, `EventoSalida{id, cuando, actor, accion}`; `GET /eventos` responde `Pagina[EventoSalida]`.

### D9 — Verificación sin pytest (Strict TDD adaptado, como C-08 D10)

- **RED**: `test/personal.http` completo se escribe primero (tarea 1.1) y se corre contra el servidor actual: toda ruta `/usuarios…` y `/eventos` → 404. Se anota la línea de base.
- **GREEN**: cada grupo de tareas hace pasar su sección del `.http`.
- **TRIANGULATE**: cada regla con al menos dos casos (acepta / rechaza, o dos motivos de rechazo).
- **Safety net**: `test/health.http`, `test/auth.http`, `test/sesion.http` y `test/verificar_security_core.py` antes de tocar `schemas/repository/unit_of_work/service/router/main` y al final.
- Lo que un `.http` no muestra se comprueba con **un** script temporal `$env:TEMP\verificar_c09.py` (no versionado), con `httpx.AsyncClient(transport=ASGITransport(main.app))` dentro de `async with main.lifespan(main.app)`: (a) revocaciones cruzadas simultáneas entre los dos únicos ADMIN sin vencimiento (forzando la superposición: otra conexión toma `FOR UPDATE` sobre las filas ADMIN, se lanzan los dos `DELETE`, se suelta) → un 200 y un 409, queda 1 ADMIN sin vencimiento; (b) dos asignaciones simultáneas del mismo rol → 201 + 409, nunca 500, una fila abierta; (c) dos altas simultáneas del mismo correo → 201 + 409; (d) atomicidad: con `eventos.add` que lanza, no quedan usuario/asignación/cierre; (e) hash antes de la transacción (listener `before_cursor_execute`: ninguna sentencia del alta entre inicio y fin de bcrypt); (f) `/openapi.json` sin `password_hash` ni `password_provisoria` en respuestas y sin `GET /usuarios`. Precondición del script: ningún otro ADMIN vigente sin vencimiento en la base (lo comprueba y aborta si no).
- El 409 **secuencial** de RN05 (un ADMIN con `vence_en` revoca al único ADMIN sin vencimiento) y el 200 cuando queda otro sin vencimiento se ven en `test/personal.http` (sección H de tasks.md); el script se queda con la concurrencia.
- Preparación sin seed: el encabezado de `test/personal.http` limpia sus filas (correos `@personal.example.com`) y crea al primer ADMIN con `/auth/registro` + `INSERT` en `asignacion_rol` por `psql`, **sin `vence_en`** (S-13, S-09).

## Risks / Trade-offs

- [El primer ADMIN debe nacer sin vencimiento] → con la regla de S-09 ninguna revocación puede dejar al sistema sin un ADMIN permanente, así que el vencimiento ya no vacía el sistema **por revocaciones**. Pero si nunca existió un ADMIN sin `vence_en` (porque el primero se creó con vencimiento), toda revocación de `ADMIN` responde 409 y, al vencer todos, el sistema queda sin administradores. Por eso el primer ADMIN — hoy por `psql` en el encabezado de `test/personal.http`, después el de `seed.py` (C-06) — se crea **sin `vence_en`**. Recuperación si igual ocurre: `psql` o `seed.py`.
- [Revocaciones razonables rechazadas] → un ADMIN con vencimiento no puede revocar al único ADMIN permanente, aunque haya otros ADMIN vigentes con vencimiento; es el costo aceptado de la alternativa B (S-09). Para quitarlo hay que asignar antes `ADMIN` sin vencimiento a otro usuario.
- [Actor que pierde ADMIN en vuelo] → una operación autorizada por `requiere_rol` puede terminar milisegundos después de que otra transacción le revocó el ADMIN al actor (la autorización y la operación son transacciones distintas, como en C-08). El bloqueo de D5 sí garantiza que siempre quede un ADMIN sin vencimiento; no se revalida al actor. Mismo criterio que DD-11.
- [Bloqueo de todas las filas ADMIN vigentes sin vencimiento] → serializa las revocaciones de ADMIN entre sí (son raras y cortas); no afecta logins, `requiere_rol` (lecturas sin bloqueo) ni asignaciones/revocaciones de otros roles.
- [`evento_seguridad` y `asignacion_rol` modificables por SQL] → la consigna sólo exige sólo-agregado en tres tablas (RN15); el historial de seguridad se puede editar desde `psql` con el rol de la aplicación. Se documenta; cerrar la vía exige otra migración (fuera de las dos que pide la consigna). Confirmado por el usuario (S-11): queda fuera de este change; si más adelante se quiere, va en un change aparte.
- [Vencimiento validado al recibir, no al insertar] → un `vence_en` milisegundos en el futuro puede quedar vencido al confirmar; la fila nace no vigente, sin daño (la próxima asignación la cierra).
- [Personal sin roles entre el alta y la asignación] → inocuo: además tiene el cambio de contraseña pendiente y sólo puede usar `/auth`.
- [`GET /usuarios` responde 405 antes de autenticar] → el router de FastAPI resuelve el método antes de las dependencias; revela que `/usuarios` existe (lo publica `/openapi.json` de todos modos).

## Migration Plan

Sin cambios de esquema ni de datos (índice parcial, columnas `timestamptz` y `evento_seguridad` existen desde C-03). Despliegue: archivos modificados + `test/personal.http`, reiniciar uvicorn. Rollback: revertir `main.py` y los cinco archivos del módulo; las filas de prueba se limpian con el bloque `psql` del encabezado de `test/personal.http`.

## Open Questions / Supuestos

No quedan preguntas abiertas: los trece supuestos fueron **confirmados por el usuario (2026-10-28)**, revisados uno por uno. Doce quedaron como se propusieron; **S-09 cambió a la alternativa B**. Cada uno conserva las alternativas descartadas y su costo.

- **S-01 — Contrato del alta** — confirmado por el usuario (2026-10-28): `{email, nombre, password_provisoria}`; el ADMIN fija la provisoria (8 caracteres a 72 bytes, reglas del registro); 201 `{id, email, nombre, activo, debe_cambiar_password}` sin contraseña ni cookie. Descartado: el servidor genera la provisoria (`secrets.token_urlsafe`) y la devuelve una sola vez — el ADMIN no elige una débil, pero la respuesta transporta un secreto y no se puede volver a consultar. Descartado: campo `password` (igual que el registro) — consistente, pero no dice que es provisoria.
- **S-02 — Alta sin roles** — confirmado por el usuario (2026-10-28): el alta no asigna roles; se asignan con `POST /usuarios/{id}/roles`. Una sola regla de vencimiento/RN03 y un evento por operación. Descartado: `rol` (y `vence_en`) obligatorios en el alta, atómico — nunca hay personal sin rol, pero duplica validación, 409 y evento en dos endpoints.
- **S-03 — Correo de un cliente existente** — confirmado por el usuario (2026-10-28): 409 de correo repetido; a un cliente que pasa a ser personal se le asigna el rol sobre su id. Descartado: "promover" la cuenta existente desde `POST /usuarios` — mezcla alta con asignación y cambiaría la contraseña de un usuario ajeno.
- **S-04 — Contrato de la asignación** — confirmado por el usuario (2026-10-28): `{rol, vence_en?}`; cualquiera de los cuatro roles (CLIENTE incluido); `vence_en` con zona y futuro validado **en el contrato** (422 con lista por campo, como el resto de la validación), guardado en UTC. Descartado: validarlo en el servicio con `EntradaInvalida` (422 `{"detail": "…"}` de negocio). Descartado: aceptar sólo roles de personal (sin CLIENTE) — la matriz no lo restringe.
- **S-05 — Rol vigente repetido y reasignación** — confirmado por el usuario (2026-10-28): vigente → 409 aunque cambie el vencimiento (para extenderlo: revocar y asignar); abierto vencido → se cierra con `revocada_en = ahora` y se abre otra fila (un evento); se permite asignar a usuarios inactivos y a uno mismo (salvo ADMIN ya vigente). Descartado: que un vencimiento distinto actualice `vence_en` de la fila vigente (200) — reescribe historial y la consigna habla de abrir filas nuevas.
- **S-06 — Revocar un rol no vigente → 404** — confirmado por el usuario (2026-10-28): 404 `El usuario no tiene el rol <ROL> vigente` si nunca lo tuvo, ya fue revocado o está vencido (la fila vencida no se toca). Descartado: 409 para "ya revocado" — la matriz de DELETE sí lista 409, pero lo reservamos para RN05 y la asignación vigente "no existe". Descartado: cerrar también una fila abierta vencida (200).
- **S-07 — `GET /usuarios/{id}/roles` no paginado** — confirmado por el usuario (2026-10-28): objeto `{usuario_id, email, nombre, roles_vigentes, asignaciones}` con el historial completo; no se trata como "listado" de `list-pagination` (la matriz da sólo 200/404, sin `page`/`size`). Descartado: `Pagina[AsignacionSalida]` con `page`/`size` — cumple literal "todo listado" pero agrega un 422 que la matriz no tiene. Descartado: arreglo plano — choca con el envoltorio obligatorio de `list-pagination`. Seguimiento al archivar: ver "Notas para el archivo".
- **S-08 — RN05 bajo concurrencia: `SELECT … FOR UPDATE`** — confirmado por el usuario (2026-10-28): bloquear las filas ADMIN vigentes **sin vencimiento** de usuarios activos en orden de id (`populate_existing`) dentro de la transacción de la revocación, antes que la fila objetivo, y contar sobre ese conjunto (D5). Descartado: `pg_advisory_xact_lock` (más simple, clave mágica, serializa de más). Descartado: `SERIALIZABLE` (correcto, exige reintentos que el UoW no tiene; hoy daría 500).
- **S-09 — Qué cuenta para "nunca sin administradores" (RN05)** — confirmado por el usuario (2026-10-28) con la **alternativa B**: revocar `ADMIN` responde 409 si después de la revocación no quedaría al menos una asignación `ADMIN` vigente **sin vencimiento** (`vence_en IS NULL`, `revocada_en IS NULL`, dueño con `usuario.activo = true`). Los ADMIN con `vence_en` no cuentan para el invariante; la prohibición de autorrevocarse el `ADMIN` sigue igual; asignar `ADMIN` con `vence_en` sigue permitido, sin regla extra en la asignación; si no existe ningún ADMIN sin vencimiento, toda revocación de `ADMIN` → 409 (comportamiento buscado). Razón: el paso del tiempo no puede dejar al sistema sin administradores por una revocación aceptada, y el 409 se puede probar secuencialmente en el `.http`. Descartado (alternativa A, la propuesta original): contar cualquier asignación `ADMIN` no revocada y sin vencer **en el instante de la operación** — no agrega reglas que la consigna no pide y no rechaza revocaciones razonables, pero si el único ADMIN restante tiene `vence_en`, al llegar esa fecha el sistema queda sin administradores, y su 409 sólo es alcanzable con concurrencia. Descartado: no mirar `activo` (hoy nada desactiva usuarios, así que no cambia el resultado).
- **S-10 — Formato de los eventos** — confirmado por el usuario (2026-10-28): `actor` = correo del ADMIN; `accion` en texto con operación, rol y correo afectado (D8), sin columnas nuevas. Descartado: columnas `usuario_afectado_id`/`rol` en `evento_seguridad` — consultable, pero exige una tercera migración. Descartado: JSON en `accion` — legible por máquina, ilegible en `psql`.
- **S-11 — Orden de `GET /eventos` y alcance del sólo-agregado** — confirmado por el usuario (2026-10-28): id descendente (lo más reciente primero, lo que se mira en un historial), sin filtros; `evento_seguridad` sigue sin disparador de sólo agregado. Descartado: id ascendente (default de `data-repositories`). Descartado: extender el disparador a `evento_seguridad` (y `asignacion_rol` sólo-UPDATE de `revocada_en`) con una migración nueva — más integridad, pero contradice "exactamente dos migraciones".
- **S-12 — Ubicación del código y montaje** — confirmado por el usuario (2026-10-28): todo en los archivos existentes del módulo `usuarios` (estructura obligatoria: un `router.py` con tres `APIRouter`); `requiere_rol(Rol.ADMIN)` una vez a nivel de router y reutilizado como `AdminDep` (D2); routers incluidos en `rutas_protegidas` antes de `app.include_router(rutas_protegidas)`. Descartado: archivos nuevos (`personal_service.py`, `eventos/`) — separa mejor, pero se aparta de la estructura de la KB. Descartado: `requiere_rol` por ruta — se puede olvidar y consulta roles dos veces.
- **S-13 — Verificación y preparación sin seed** — confirmado por el usuario (2026-10-28): `test/personal.http` (correos `@personal.example.com`, primer ADMIN por `psql` **sin `vence_en`**) + script temporal `verificar_c09.py` para concurrencia, atomicidad y bcrypt (D9). Con la regla B de S-09 el 409 de RN05 es observable secuencialmente: el `.http` lo cubre (un segundo ADMIN con `vence_en` intenta revocar al único sin vencimiento → 409; con otro ADMIN sin vencimiento → 200) y el script se queda con las revocaciones cruzadas simultáneas. Descartado: esperar a C-06 y usar `admin@example.com` — hoy no existe el seed.

## Notas para el archivo

- **S-07**: al archivar, aclarar en la spec principal `list-pagination` que el envoltorio paginado rige para las colecciones que reciben `page`/`size`; `GET /usuarios/{id}/roles` devuelve un objeto con el historial completo y no es un "listado" en ese sentido.
- **S-11**: extender el sólo-agregado a `evento_seguridad`/`asignacion_rol` queda fuera; si se decide, va en un change aparte (exige migración).
- **S-09 / C-06**: el `seed.py` de C-06 debe crear al primer ADMIN **sin `vence_en`**; dejarlo anotado en la propuesta de C-06.
