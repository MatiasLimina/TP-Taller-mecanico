# Preguntas Abiertas

## Inconsistencias detectadas

### IN-01 — [RESUELTA] Tablas del PDF desalineadas en la extracción de texto
> Resuelta: el usuario aportó la tabla visual; `03` está validada.
**Fuente A (texto extraído):** la tabla "Endpoints de referencia" mezcla filas, roles y códigos en columnas separadas. **Fuente B (necesaria):** el PDF visual. **Impacto:** la matriz de permisos/códigos de `03` es reconstrucción. **Resolución propuesta:** abrir el PDF y validar fila por fila antes de implementar routers.

### IN-02 — [RESUELTA] Módulo `usuarios` vs `GET /usuarios`
> Resuelta: la tabla del PDF no incluye `GET /usuarios`; no se implementa.
**Observación:** la consigna lista `GET /usuarios/{id}/roles` y `GET /eventos`; no queda claro si existe `GET /usuarios` (listado). **Resolución propuesta:** implementar sólo lo listado (`POST /usuarios`, roles, eventos).

### IN-03 — Versión de bcrypt
**Observación:** requisito mínimo 4.0, pero el texto describe el comportamiento "desde la versión 5" (excepción si >72 bytes). **Resolución propuesta:** validar ≤ 72 bytes en el contrato, independientemente de la versión.

### IN-04 — Sobreentrega en la orden #2 del seed
**Observación:** la orden 2 pide 4 bujías con stock 2 (a propósito, para C-11). Tras C-12 (reponer) el flujo de terminación debe funcionar. No es un error: es dato de prueba; documentado para evitar "corregirlo".

## Preguntas abiertas (priorizadas)
| Prioridad | Pregunta | Bloquea | Decisor |
|-----------|----------|---------|---------|
| ✅ Resuelta | Matriz endpoint↔rol↔códigos validada con el PDF (IN-01) | — | Usuario |
| ✅ Resuelta | Nombres de variables de entorno: se mantienen los propuestos (`SECRET_KEY`, `BCRYPT_COST`, `COOKIE_SECURE`, etc.) | — | Usuario |
| ✅ Resuelta | `movimiento_stock.cantidad` con signo: entradas positivas, salidas negativas | — | Usuario |
| ✅ Resuelta | `GET /usuarios` no existe en la consigna (IN-02) | — | Usuario |
| ✅ Resuelta | Defaults de `env.example`: token 1800 s, BCRYPT_COST 12, semáforo 4, pool 5/10, COOKIE_SECURE=false | — | Usuario |
| ✅ Resuelta | Sin pytest: sólo `.http` y `solo_agregado.sql`, como pide la consigna | — | Usuario |
| ✅ Resuelta | Driver: asyncpg (`postgresql+asyncpg://`) | — | Usuario |

## [DISCOVERY]
Todos los campos de discovery (`problem`, `system_type`, `domain`, `scale`, `stack`, `needs_infra`) se infirieron con confianza razonable de la consigna; `scale` = `team` (taller pequeño; la consigna no fija volumen) con confianza media. Confirmar si importa para decisiones de pool.
