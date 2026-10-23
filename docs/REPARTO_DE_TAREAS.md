# Reparto de tareas — Taller mecánico (equipo de 3)

> Documento de coordinación del equipo. Deriva de [CHANGES.md](../CHANGES.md) (16 changes, 8 gates, camino crítico de 9) y de las reglas de [AGENTS.md](../AGENTS.md).
> **Lo que manda son las dependencias** de `CHANGES.md`; los "pasos" de abajo son orientativos.

## 1. Integrantes

| Rol en este documento | Nombre | GitHub |
|-----------------------|--------|--------|
| **Integrante A** — Núcleo y datos | Mati | _completar_ |
| **Integrante B** — Autenticación y órdenes | Nico | _completar_ |
| **Integrante C** — Seguridad base, repuestos y seed | Lauti | _completar_ |

## 2. Resumen del reparto

| Integrante | Changes a su cargo | Peso en la nota | Governance máx. |
|------------|--------------------|-----------------|-----------------|
| **A** | C-01, C-02, C-03, C-04, C-09, C-15 | Ej.1 (8 %), Ej.2 (14 %), Ej.6 base (20 %), Ej.7 migración | CRITICO |
| **B** | C-07, C-08, C-13, C-14 | Ej.4 (16 %), Ej.5 (14 %), núcleo de Ej.6 | CRITICO |
| **C** | C-05, C-06, C-10, C-11, C-12 | Ej.4 base, Ej.3 (10 %), Ej.7 | CRITICO |
| **Los 3** | C-16 (por módulo) | Cierre y entregables | BAJO |

> **Diferencia con `CHANGES.md`:** el plan de 3 agentes de ese archivo deja al Integrante C sin trabajo hasta el paso 5 y carga a B con C-05 y C-10. Acá `C-05 security-core` pasa a C (arranca en paralelo con C-02 apenas cierra C-01) y `C-10 clientes-vehiculos` también, para equilibrar la carga. Las dependencias no cambian.

## 3. Detalle por integrante

### Integrante A — Núcleo y datos
| Change | Nombre | Governance | Depende de | Entrega |
|--------|--------|------------|------------|---------|
| C-01 | foundation-setup | MEDIO | — | Estructura, `Settings`, motor/lifespan, health, Alembic async |
| C-02 | core-repository-uow | ALTO | C-01 | `BaseRepository`, `SoftDeleteRepository`, `UnitOfWork`, paginación, manejo de `IntegrityError` |
| C-03 | domain-models-migration | CRITICO | C-02 | 13 modelos + migración 1 autogenerada |
| C-04 | append-only-trigger-migration | ALTO | C-03 | Migración 2 manual (trigger) + `test/solo_agregado.sql` |
| C-09 | roles-personal-eventos | CRITICO | C-08 | `POST /usuarios`, roles con vigencia, `GET /eventos` |
| C-15 | ordenes-lecturas-sin-n-plus-1 | MEDIO | C-13 | Listados y detalle de órdenes sin N+1, `/mis-ordenes` |

**Responsable además de:** el cimiento compartido (`app/core/`), la cadena de migraciones de Alembic y el ciclo `upgrade → downgrade → upgrade`.

### Integrante B — Autenticación y órdenes
| Change | Nombre | Governance | Depende de | Entrega |
|--------|--------|------------|------------|---------|
| C-07 | auth-registro-login | CRITICO | C-02, C-03, C-05 | Registro, login (429, hash ficticio, `intento_acceso`), logout |
| C-08 | auth-session-guards | CRITICO | C-07 | `get_usuario_actual`, `requiere_rol`, dos grupos de rutas, `/auth/yo`, cambio de contraseña |
| C-13 | ordenes-alta-estados | ALTO | C-10, C-11 | Alta de orden con ítems, catálogo de estados |
| C-14 | ordenes-transiciones | CRITICO | C-13, C-12 | Iniciar, terminar (stock atómico + `BackgroundTasks`), cancelar |

**Mientras espera sus dependencias** (pasos 1–3): preparar el esqueleto de los `.http` de auth (casos C-02 a C-09 de la consigna), leer los flujos 1, 2, 5 y 6 de `knowledge-base/07_flujos_principales.md` y revisar los PR de A y C.

**Camino crítico:** B concentra C-07, C-08, C-13 y C-14, que son parte de los 9 changes que no se pueden paralelizar. Un retraso de B retrasa todo el proyecto.

### Integrante C — Seguridad base, repuestos y seed
| Change | Nombre | Governance | Depende de | Entrega |
|--------|--------|------------|------------|---------|
| C-05 | security-core | CRITICO | C-01 | bcrypt en `to_thread` + semáforo, JWT, cookie HttpOnly, hash ficticio |
| C-06 | seed-script | MEDIO | C-04, C-05 | `seed.py` idempotente (catálogo primero) |
| C-10 | clientes-vehiculos | MEDIO | C-08 | Clientes, vehículos con baja lógica, `/mis-vehiculos` |
| C-11 | repuestos-catalogo | MEDIO | C-08 | CRUD de repuestos, búsqueda con parámetros ligados |
| C-12 | repuestos-stock-precios | ALTO | C-11 | Reposición, movimientos, historial de precios |

**Atención:** C-05 es CRITICO y bloquea a B (C-07 lo necesita). Conviene que C lo cierre en el mismo tiempo que A cierra C-02 y C-03.

## 4. Orden de trabajo (pasos orientativos)

| Paso | A | B | C |
|------|---|---|---|
| 1 | C-01 | (preparación: `.http` de auth, lectura) | (preparación: lectura de C-05) |
| 2 | C-02 | (preparación) | C-05 |
| 3 | C-03 | (preparación) | C-05 (cierre) |
| 4 | C-04 | C-07 | — (revisar PR; adelantar `seed.py` con los datos) |
| 5 | C-09 (tras C-08) | C-08 | C-06 |
| 6 | C-09 | — (revisar PR) | C-10, C-11 |
| 7 | — | C-13 (necesita C-10 y C-11) | C-12 |
| 8 | C-15 | C-14 | — |
| 9 | C-16: usuarios, clientes y estados | C-16: órdenes | C-16: repuestos, README, ciclo de migraciones |

Gates (de `CHANGES.md`): GATE 0 = C-01 · GATE 1 = C-02 · GATE 2 = C-03 (fork: C-04, C-07, C-06) · GATE 3 = C-07 · GATE 4 = C-08 (fork: C-09, C-10, C-11) · GATE 5 = C-11 · GATE 6 = C-13 y C-12 · GATE 7 = C-09, C-14, C-15, C-06.

## 5. C-16 — Entregables finales (repartidos)

| Parte | Quién |
|-------|-------|
| `.http` de usuarios/auth, clientes y catálogo de estados (casos C-01 a C-09, C-17) | A |
| `.http` de órdenes: alta, terminar, cancelar (casos C-10 a C-13) | B |
| `.http` de repuestos, `README.md` desde cero, evidencia C-14 (psql) y C-15 (consultas fijas del detalle), ciclo de migraciones, chequeo de secretos (casos C-14 a C-16, C-18, C-19) | C |

Condición bloqueante de la consigna: `alembic upgrade head` sobre base vacía, sin credenciales reales en el repo. Lo verifican **los tres** antes de entregar.

## 6. Reglas de trabajo en equipo

1. **Una rama por change**: `feat/C-NN-<nombre>` (por ejemplo `feat/C-02-core-repository-uow`), creada desde `main` actualizada.
2. **Flujo por change:** `/opsx:propose C-NN-<nombre>` → implementar → `/opsx:archive C-NN-<nombre>` → marcar `[x]` en `CHANGES.md`.
3. **Governance:** en CRITICO y ALTO se propone y se espera revisión **antes** de escribir código.
4. **Pull requests:** todo change va por PR hacia `main` y lo revisa otra persona. En los CRITICO, revisa quien depende de ese change (ej.: B revisa C-05; A revisa C-07).
5. **Commits:** conventional commits (`feat:`, `fix:`, `docs:`), sin líneas de co-autoría de IA. Un commit por unidad lógica.
6. **No avanzar** sobre un change cuyas dependencias no estén mergeadas en `main`.
7. **Reglas duras** de `AGENTS.md`: capas y UoW, async y bcrypt, sin carga perezosa, contratos con `extra="forbid"`, solo Alembic, sin secretos en el repo.

## 7. Puntos de conflicto a coordinar

| Archivo compartido | Riesgo | Cómo evitarlo |
|--------------------|--------|---------------|
| `main.py` | Todos registran su router | Cambio mínimo (una línea por módulo); resolver el merge sin reordenar |
| `migrations/versions/` | Dos cabezas de Alembic si dos personas crean migraciones | **Solo A** crea migraciones (C-03 y C-04). Si alguien necesita cambiar el esquema, se lo pide a A |
| `requirements.txt` y `env.example` | Dependencias o variables nuevas simultáneas | Avisar en el PR; mergear en orden |
| `app/core/*` | Cambiar el cimiento rompe a los demás | Solo A modifica `repository.py`, `unit_of_work.py` y `paginacion.py`; C modifica `security.py`; B modifica `dependencies.py` |
| `CHANGES.md` | Dos personas marcando `[x]` | Marcar el checkbox en el mismo PR del change |
| `seed.py` | Lo usan todos los `.http` | Lo mantiene C; los demás piden datos nuevos por PR |

## 8. Pendientes de equipo
- [ ] Completar los usuarios de GitHub en la sección 1 (nombres ya cargados: A = Mati, B = Nico, C = Lauti).
- [ ] Confirmar el reparto A/B/C (editar este documento si cambia).
- [ ] Definir el canal y la frecuencia de sincronización (qué se avisa al cerrar un gate).
- [ ] Acordar quién crea la base de PostgreSQL 16 local de cada uno (cada integrante usa su propio `.env`, no versionado).
