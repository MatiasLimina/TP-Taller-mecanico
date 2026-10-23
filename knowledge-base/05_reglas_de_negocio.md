# Reglas de Negocio

Los códigos `RNxx` son los de la consigna (se mantienen tal cual para trazabilidad con los casos de prueba C-xx). Se agrupan por dominio.

## Dominio: Identidad y unicidad
- **RN01**: El correo de un usuario y el documento de un cliente son únicos. La patente de un vehículo y el código de un repuesto son únicos entre los no dados de baja. *Garante:* UNIQUE e índices únicos parciales; 409 con mensaje propio. Sin consulta previa.
- **RN02**: El auto-registro crea usuario + rol CLIENTE + ficha de cliente: o las tres filas o ninguna. Si el documento ya es de un cliente del taller → 409 y no se apropia de esa ficha. *Garante:* un solo UoW.
- **RN03**: Un usuario tiene a lo sumo una asignación abierta por rol. *Garante:* índice único parcial; 409.

## Dominio: Autenticación y autorización (RN-AU)
- **RN04**: Los permisos se deciden con los roles vigentes en la base en cada petición; los del token son informativos. *Garante:* dependencia que consulta `asignacion_rol`.
- **RN05**: Un ADMIN no puede revocarse su propio rol ADMIN, y el sistema nunca queda sin administradores vigentes. *Garante:* servicio; 409.
- **RN06**: Con cambio de contraseña pendiente, sólo se pueden usar `/auth` y salud. *Garante:* dos grupos de rutas; 403.
- **RN07**: Al cambiar la contraseña, las sesiones emitidas antes dejan de valer (aunque sean del mismo segundo); la devuelta por el propio cambio, no. *Garante:* comparar `iat` con `password_cambiada_en` **sin truncar**; 401.
- **RN08**: Tras 5 intentos fallidos con el mismo correo desde la misma IP en 60 s, login → 429 con `Retry-After` **sin verificar la contraseña**. Un login correcto reinicia la cuenta (los fallos previos quedan en la tabla pero dejan de contar). *Garante:* conteo sobre `intento_acceso`.
- **RN09**: El login responde lo mismo y tarda lo mismo exista o no el correo. *Garante:* mismo mensaje; verificación contra hash ficticio.
- **RN17**: Lo propio sólo pide autenticación: un cliente ve sus vehículos y las órdenes de sus vehículos, ninguna otra. *Garante:* `/mis-*` y comprobación de dueño; 403.

## Dominio: Órdenes de trabajo
- **RN10**: Una orden nace PENDIENTE con ≥ 1 ítem y sin repuestos repetidos. El precio de cada ítem se copia del repuesto; el total lo calcula el servidor. Precio/total/estado/fecha no viajan en el cuerpo. *Garante:* DTO.
- **RN11**: Transiciones: PENDIENTE→EN_REPARACION (la inicia un mecánico, que queda asignado); EN_REPARACION→TERMINADA (el mecánico asignado o un ADMIN); PENDIENTE→CANCELADA. 409 si el estado no lo permite.
- **RN12**: Cancelan: recepción, administrador o el dueño del vehículo. El permiso se evalúa **antes** que el estado (403 antes que 409).
- **RN13**: Terminar descuenta el stock de cada ítem, deja un movimiento por salida y una línea de historial. Si un repuesto no alcanza → 409 y no queda ninguna de esas escrituras. *Garante:* un solo UoW.
- **RN16**: Un vehículo o repuesto dado de baja deja de aparecer y no se usa en órdenes nuevas, pero conserva sus datos. Un vehículo con órdenes abiertas (estado no final según catálogo) no se da de baja → 409. *Garante:* borrado lógico; `es_final`.
- **RN19**: Los estados posibles son las filas de `estado_orden`. El catálogo se consulta desde la API y no se edita. Si está vacío, crear una orden → 409 con mensaje propio. *Garante:* FK; repositorio de sólo lectura.

## Dominio: Stock y precios
- **RN14**: El stock sólo cambia vía movimientos: alta con stock inicial, reposición y terminación de órdenes. No se edita por PATCH. *Garante:* punto único de escritura de stock.
- **RN20**: Cada cambio de precio deja una línea en `historial_precio_repuesto` en la misma transacción. Un PATCH que no cambia el precio no deja línea. *Garante:* un solo UoW; CHECK `precio_nuevo <> precio_anterior`.

## Dominio: Integridad
- **RN15**: `historial_estado_orden`, `movimiento_stock` e `historial_precio_repuesto` son de sólo agregado: nadie modifica ni borra filas. *Garante:* trigger en la base, instalado por migración.
- **RN18**: Ningún error devuelve texto interno de la base; ninguna entrada inválida termina en 500. *Garante:* traducción de `IntegrityError`; validación en el contrato.

## Reglas globales de contrato (Ejercicio 3)
- Entradas con `extra="forbid"`; ninguna respuesta incluye `password_hash`; PATCH con `exclude_unset`.
- Códigos: 201 crear, 204 baja, 404 recurso de ruta inexistente, 409 choque con lo guardado, 422 contrato no cumplido.
- Listados `{items, total, page, size, pages}`: `page` ≥ 1, `size` 1–100 (def. 20), página más allá de la última → 422, `total` con los mismos filtros, 0 resultados → una página vacía.
- Todo campo que termina en bcrypt (registro, login, contraseña actual/nueva) ≤ **72 bytes** (bytes, no caracteres).
- Vencimiento de rol: con zona horaria y en el futuro; si no → 422 (no 409).
