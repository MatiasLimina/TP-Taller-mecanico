# Reparto de tareas — Taller mecánico (equipo de 3)

> **Fuente única del reparto.** Quién hace qué vive SÓLO en este archivo. [CHANGES.md](../CHANGES.md) tiene el alcance y las dependencias de cada change, y un campo `Responsable` que tiene que coincidir con la tabla de la sección 3.
> **Lo que manda son las dependencias** de `CHANGES.md`; los "pasos" de abajo son orientativos.
>
> Última actualización del reparto: **2026-10-28** (Nico pasa a diseñar C-10…C-16 y a implementar las órdenes; Mati toma repuestos; Lauti suma el cierre C-16).

## 1. Integrantes y herramientas

| Nombre | Rol | Herramientas de IA | GitHub |
|--------|-----|--------------------|--------|
| **Mati** | Partes críticas, revisión y `archive` | Claude Pro (Claude Code) | [@MatiasLimina](https://github.com/MatiasLimina) |
| **Nico** (Nicolás Lionel Monjelardi) | Diseño (`propose` C-10…C-16) y órdenes | Claude (plan pago, Claude Code) + GitHub Copilot (plan de estudiantes), Gemini | [@nicolasmonjelardi](https://github.com/nicolasmonjelardi) |
| **Lauti** (Lautaro Agustín Agüero) | Implementación y cierre | GitHub Copilot (plan de estudiantes), Gemini, modelos gratuitos de OpenCode | [@LautaroAguero01](https://github.com/LautaroAguero01) |

## 2. Criterio del reparto

Se separa **diseñar** de **ejecutar**:

- **Diseñar** (`/opsx:propose`: proposal, design, specs, tasks) es lo que más exige al modelo y donde un error cuesta más. Lo hacen quienes tienen Claude: **Mati** (C-06…C-09) y **Nico** (C-10…C-16).
- **Ejecutar** (`apply`) un `tasks.md` bien detallado lo resuelve bien un modelo más chico. **Lauti** implementa changes ya especificados; Mati y Nico implementan los de governance ALTO/CRITICO.
- **Revisar**: Mati revisa todos los PR y hace los `archive`. Cuando Nico hace el `propose` y el `apply` del mismo change (C-13, C-14), Mati revisa **los dos** antes del merge, porque si no nadie más mira ese diseño.

## 3. Resumen del reparto (tabla canónica)

C-01 a C-09 ya están cerrados.

| Change | Nombre | Governance | `propose` | `apply` | Estado |
|--------|--------|------------|-----------|---------|--------|
| C-01 | foundation-setup | MEDIO | Mati | Mati | ✓ |
| C-02 | core-repository-uow | ALTO | Mati | Mati | ✓ |
| C-03 | domain-models-migration | CRITICO | Mati | Mati | ✓ |
| C-04 | append-only-trigger-migration | ALTO | Mati | Mati | ✓ |
| C-05 | security-core | CRITICO | Lauti | Lauti | ✓ |
| C-06 | seed-script | MEDIO | Mati | **Lauti** | ✓ |
| C-07 | auth-registro-login | CRITICO | Mati | Mati | ✓ |
| C-08 | auth-session-guards | CRITICO | Mati | Mati | ✓ |
| C-09 | roles-personal-eventos | CRITICO | Mati | Mati | ✓ |
| C-10 | clientes-vehiculos | MEDIO | Nico | **Lauti** | ✓ |
| C-11 | repuestos-catalogo | MEDIO | Nico | **Mati** | ✓ |
| C-12 | repuestos-stock-precios | ALTO | Nico | **Mati** | ✓ |
| C-13 | ordenes-alta-estados | ALTO | Nico | **Nico** (revisión de Mati) | ✓ |
| C-14 | ordenes-transiciones | CRITICO | Nico | **Nico** (revisión de Mati) | ✓ |
| C-15 | ordenes-lecturas-sin-n-plus-1 | MEDIO | Nico | **Lauti** | ✓ |
| C-16 | verificacion-http-readme | BAJO | Nico | **Lauti** (cierre) + cada uno los `.http` de su módulo (ver §6) | pendiente |

| Integrante | `propose` pendientes | `apply` pendientes | Governance máx. que implementa |
|------------|----------------------|--------------------|-------------------------------|
| **Mati** | — | — | ALTO (ya hizo los CRITICO de auth) |
| **Nico** | C-15, C-16 | — | CRITICO (C-14, con revisión de Mati) |
| **Lauti** | — | C-15, C-16 | MEDIO |

## 4. Detalle por integrante (lo que falta)

### Mati — Partes críticas, revisión y cierre
| Change | Governance | Depende de | Entrega |
|--------|------------|------------|---------|
| C-11 | MEDIO | C-08 | CRUD de repuestos, búsqueda con parámetros ligados, punto único de escritura de stock |
| C-12 | ALTO | C-11 | Reposición, movimientos, historial de precios |

**Además:** revisión de todos los PR (en especial los `propose` y `apply` de Nico), los `archive` y marcar `[x]` en `CHANGES.md`.

### Nico — Diseño y órdenes
| Change | Governance | Depende de | Entrega |
|--------|------------|------------|---------|
| `propose` C-10…C-16 | — | — | proposal, design, specs y tasks de cada change |
| C-13 | ALTO | C-10, C-11 | Alta de orden con ítems, catálogo de estados |
| C-14 | CRITICO | C-13, C-12 | Iniciar, terminar (stock atómico + `BackgroundTasks`), cancelar |

**Cuello de botella:** los `propose` de C-10 y C-11. Lauti y Mati no pueden arrancar C-10/C-11 hasta tenerlos. Si Nico todavía no tiene el entorno listo (ver §7.1), Mati hace esos dos `propose` para no frenar al resto.

### Lauti — Implementación y cierre
| Change | Governance | Depende de | Entrega |
|--------|------------|------------|---------|
| C-06 | MEDIO | C-04, C-05 | `seed.py` idempotente (catálogo primero) |
| C-10 | MEDIO | C-08 | Clientes, vehículos con baja lógica, `/mis-vehiculos` |
| C-15 | MEDIO | C-13 | Listados y detalle de órdenes sin N+1, `/mis-ordenes` |
| C-16 | BAJO | C-06, C-09, C-14, C-15 | Cierre: README desde cero, ciclo de migraciones, chequeo de secretos (ver §6) |

C-06 ya tiene el `propose` hecho (rama `feat/C-06-seed-script`): se puede **arrancar ya**.

## 5. Orden de trabajo (pasos orientativos)

| Paso | Mati | Lauti | Nico |
|------|------|-------|------|
| 1-4 | C-01 a C-04 ✓ | C-05 ✓ | — |
| 5 | C-07 ✓ | — | Casos `.http` de C-16 por adelantado (matriz endpoint↔rol) |
| 6 | C-08 ✓ | — | (cont. casos `.http`) |
| 7 | C-09 ✓ · `propose` de C-06 ✓ | C-06 | `propose` de C-10, C-11, C-12 |
| 8 | C-11 | C-10 | `propose` de C-13, C-14, C-15, C-16 |
| 9 | C-12 | (cont. C-10) | C-13 |
| 10 | Revisión de C-13 | C-15 | C-14 |
| 11 | Revisión de C-14, revisión final + `archive` | C-16 (cierre) | `.http` de órdenes |

Gates (de `CHANGES.md`): GATE 4 = C-08 (fork: C-09, C-10, C-11) · GATE 5 = C-11 (C-12; C-13 si además C-10) · GATE 6 = C-13 y C-12 (C-14, C-15) · GATE 7 = C-06, C-09, C-14, C-15 (C-16).

## 6. C-16 — Entregables finales

Cada uno escribe los `.http` del módulo que implementó; Lauti integra y cierra.

| Parte | Quién |
|-------|-------|
| `.http` de usuarios/auth (ya existen: `auth.http`, `sesion.http`, `personal.http`) | Mati (ya hechos) |
| `.http` de clientes, vehículos y lecturas de órdenes; evidencia C-15 (consultas fijas del detalle con `SQL_ECHO=true`) | Lauti |
| `.http` de repuestos, stock y precios | Mati |
| `.http` de órdenes (alta, iniciar, terminar, cancelar); evidencia C-14 (`solo_agregado.sql` en psql) | Nico |
| `README.md` desde cero, ciclo `upgrade`/`downgrade`/`upgrade`, chequeo de secretos | Lauti |

Condición bloqueante de la consigna: `alembic upgrade head` sobre base vacía, sin credenciales reales en el repo. Lo verifican **los tres** antes de entregar.

## 7. Guía de herramientas

### 7.1 Nico (Claude Code)

Para hacer `propose` con `/opsx:propose` necesita el mismo entorno que Mati, que **no se versiona**: el `CLAUDE.md` global con OPSX, engram y el `.atl/skill-registry.md` (se genera con la skill `skill-registry`). Las skills de proyecto ya vienen con el repo (`.agents/skills/`).

### 7.2 Lauti (y cualquiera que trabaje sin Claude)

| Herramienta | Usarla para | Evitarla para |
|-------------|-------------|---------------|
| **GitHub Copilot** (modo agente en VS Code) | Implementar las tareas del `tasks.md` una por una, con el archivo abierto. Los modelos "premium" tienen un cupo mensual: guardarlos para lo difícil (C-15) | Tareas mecánicas que puede hacer un modelo gratis (gasta cupo) |
| **Modelos gratuitos de OpenCode** | Tareas mecánicas: schemas de Pydantic, CRUDs que copian un patrón ya hecho, casos `.http`, `seed.py` | Decisiones de diseño o lógica con transacciones (stock, permisos) |
| **Gemini** (ventana de contexto grande) | Leer la KB entera o un diff completo y revisarlo contra las reglas duras **antes** de abrir el PR; preguntar "qué significa esto" sobre el dominio | Escribir código directamente en el repo sin el `tasks.md` como guía |
| **Quien hizo el `propose`** (Mati o Nico) | Cuando algo se traba: después de **2 intentos fallidos** con el mismo error, avisarle en vez de seguir insistiendo | — |

### 7.3 Que el agente conozca las reglas del proyecto

- **OpenCode** y **Copilot** leen `AGENTS.md` de la raíz del repo: ahí están las reglas duras. Verificar que el agente lo tenga en cuenta (si no, pedírselo explícitamente en el prompt).
- **Gemini CLI** busca por defecto un `GEMINI.md`; configurarlo para que lea `AGENTS.md` o pasárselo como contexto en el prompt.
- Los comandos `/opsx:*` son de Claude Code. Sin Claude, el equivalente es el CLI de OpenSpec, que funciona con cualquier herramienta:

```bash
openspec instructions apply --change "<nombre-del-change>"
```

Eso imprime las instrucciones de implementación del change; se le pasan al agente junto con el `tasks.md`.

### 7.4 Flujo por change (para quien implementa)

1. Quien hace el `propose` (Mati o Nico) lo deja commiteado en la rama `feat/C-NN-<nombre>` y avisa.
2. Hacer `git pull` y pasarse a esa rama.
3. Leer `proposal.md` y `design.md` del change en `openspec/changes/<nombre>/`. No hace falta entender todo, pero sí saber qué se construye y por qué.
4. Pedirle al agente **una tarea por vez** del `tasks.md` (ver el prompt de 7.5). No pedirle "implementá todo el change".
5. Después de cada tarea: correr el caso `.http` que indique la tarea y `ruff check .`. Si pasa, marcar `[x]` en `tasks.md` y commitear (`feat(C-NN): ...`).
6. Al terminar todas las tareas: pedirle a Gemini una revisión del diff contra `AGENTS.md` (ver 7.5), corregir lo que encuentre y abrir el PR hacia `main`.
7. Mati revisa, mergea y hace el `archive`.

### 7.5 Prompts de referencia

Para implementar una tarea (Copilot u OpenCode):

```text
Leé AGENTS.md y estos archivos del change:
openspec/changes/<nombre>/proposal.md, design.md y tasks.md.
Implementá SOLAMENTE la tarea <X.Y> del tasks.md.
No modifiques archivos que la tarea no menciona.
Respetá las reglas duras de AGENTS.md (capas Router → Service → UoW → Repository,
async def, flush y no commit en repositorios, extra="forbid" en schemas de entrada).
Si algo de la tarea es ambiguo, preguntame antes de decidir.
```

Para revisar antes del PR (Gemini):

```text
Te paso AGENTS.md, el design.md del change y el diff completo (git diff main).
Revisá el diff SOLO contra las "Reglas Duras" de AGENTS.md y el design.md.
Listá cada incumplimiento con archivo, línea y la regla que rompe.
No propongas mejoras de estilo ni refactors.
```

### 7.6 Errores típicos de los modelos chicos en este proyecto

Revisar especialmente esto antes de abrir un PR:

- `session.commit()` dentro de un repositorio o un servicio (va `flush()`; el commit lo hace el UoW).
- Handlers sin `async def`, o bcrypt llamado directo sin `to_thread`.
- Relaciones leídas sin precarga (`selectinload`/`joinedload` en el repositorio): genera carga perezosa y falla en async.
- Schemas de entrada sin `model_config = ConfigDict(extra="forbid")`.
- `float` para precios (va `Decimal`) o `datetime` sin zona horaria.
- SQL armado con f-strings con datos del usuario.
- Crear una migración nueva: **no se puede**. La consigna admite sólo las dos migraciones que ya existen; si algo parece necesitar un cambio de esquema, avisar a Mati.

## 8. Reglas de trabajo en equipo

1. **Una rama por change**: `feat/C-NN-<nombre>`. La crea quien hace el `propose`; quien implementa trabaja sobre esa misma rama.
2. **Flujo por change:** `propose` (Mati o Nico) → implementar (según §3) → PR → revisión y `archive` (Mati) → marcar `[x]` en `CHANGES.md`.
3. **Governance:** CRITICO y ALTO se diseñan y revisan antes de escribir código. C-13 y C-14 (los implementa Nico) no se mergean sin la revisión de Mati del `propose` y del `apply`.
4. **Pull requests:** todo change va por PR hacia `main`. Mati revisa los de Lauti y Nico; Nico o Lauti revisan los de Mati (C-11, C-12), así todos conocen el código.
5. **Si una tarea es ambigua**, no se deja que el modelo decida: se avisa a quien hizo el `propose` y se reescribe la tarea en el `tasks.md`.
6. **Commits:** conventional commits (`feat:`, `fix:`, `docs:`), sin líneas de co-autoría de IA. Un commit por tarea o unidad lógica.
7. **No avanzar** sobre un change cuyas dependencias no estén mergeadas en `main`.
8. **Antes de commitear:** `ruff check .` y `git diff --check` en verde.
9. **Cambios de reparto:** se editan **sólo acá** (§3) y se actualiza el campo `Responsable` del change en `CHANGES.md` en el mismo commit.

## 9. Puntos de conflicto a coordinar

| Archivo compartido | Riesgo | Cómo evitarlo |
|--------------------|--------|---------------|
| `main.py` | Todos registran su router | Cambio mínimo (una línea por módulo); resolver el merge sin reordenar |
| `migrations/versions/` | Romper la condición de "sólo dos migraciones" | **Nadie** crea migraciones nuevas (ver §7.6) |
| `requirements.txt` y `env.example` | Dependencias o variables nuevas simultáneas | Avisar en el PR; mergear en orden |
| `app/core/*` | Cambiar el cimiento rompe a los demás | Sólo Mati modifica `repository.py`, `unit_of_work.py`, `paginacion.py` y `dependencies.py`; `security.py` (de Lauti) no se toca sin revisión de Mati |
| `app/modules/repuestos/*` | C-11/C-12 (Mati) definen el punto único de escritura de stock que usa C-14 (Nico) | Nico usa ese punto único, no escribe `stock` por su cuenta |
| `CHANGES.md` | Dos personas marcando `[x]` | Se marca en el `archive`, que hace Mati |
| `seed.py` | Lo usan todos los `.http` | Lo mantiene Lauti; los demás piden datos nuevos por PR |

## 10. Pendientes de equipo
- [x] Completar los usuarios de GitHub en la sección 1.
- [ ] Confirmar el reparto del 28/10 con Lauti y Nico.
- [ ] Nico: entorno de Claude Code listo para `propose` (§7.1).
- [ ] Lauti: verificar que su agente (Copilot / OpenCode / Gemini) lee `AGENTS.md`.
- [ ] Definir el canal y la frecuencia de sincronización (qué se avisa al cerrar un gate o al dejar listo un `propose`).
- [ ] Cada integrante con su PostgreSQL 16 local y su propio `.env` (no versionado).
