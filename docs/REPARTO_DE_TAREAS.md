# Reparto de tareas — Taller mecánico (equipo de 3)

> Documento de coordinación del equipo. Deriva de [CHANGES.md](../CHANGES.md) (16 changes, 8 gates, camino crítico de 9) y de las reglas de [AGENTS.md](../AGENTS.md).
> **Lo que manda son las dependencias** de `CHANGES.md`; los "pasos" de abajo son orientativos.

## 1. Integrantes y herramientas

| Nombre | Rol | Herramientas de IA | GitHub |
|--------|-----|--------------------|--------|
| **Mati** | Diseño, partes críticas y revisión | Claude Pro (Claude Code) y otras suscripciones pagas de respaldo | _completar_ |
| **Lauti** | Implementación | GitHub Copilot (plan de estudiantes), Gemini, modelos gratuitos de OpenCode | _completar_ |
| **Nico** | Implementación y verificación | GitHub Copilot (plan de estudiantes), Gemini, modelos gratuitos de OpenCode | _completar_ |

## 2. Criterio del reparto

El reparto anterior asignaba changes enteros (diseño + código) a cada integrante. Lauti y Nico no tienen un plan pago de IA, así que se cambió el criterio: **separar diseñar de ejecutar**.

- **Diseñar** (`/opsx:propose`: proposal, design, specs, tasks) es lo que más exige al modelo y donde un error cuesta más. Lo hace **Mati** para todos los changes.
- **Ejecutar** (`apply`) un `tasks.md` bien detallado lo resuelve bien un modelo más chico. Lo hacen **Lauti y Nico**, salvo los changes CRITICO, que también hace Mati.
- **Revisar**: Mati revisa todos los PR y hace los `archive`.

## 3. Resumen del reparto

C-01 a C-05 ya están cerrados (C-01 a C-04: Mati; C-05: Lauti).

| Integrante | `propose` | `apply` | Governance máx. que implementa |
|------------|-----------|---------|-------------------------------|
| **Mati** | Todos (C-06…C-16) | C-07, C-08, C-09, C-13, C-14 | CRITICO |
| **Lauti** | — | C-06, C-10, C-15 | MEDIO |
| **Nico** | — | C-11, C-12, C-16 | ALTO (C-12, con revisión de Mati) |

## 4. Detalle por integrante

### Mati — Diseño, partes críticas y revisión
| Change | Nombre | Governance | Depende de | Entrega |
|--------|--------|------------|------------|---------|
| C-07 | auth-registro-login | CRITICO | C-02, C-03, C-05 | Registro, login (429, hash ficticio, `intento_acceso`), logout |
| C-08 | auth-session-guards | CRITICO | C-07 | `get_usuario_actual`, `requiere_rol`, dos grupos de rutas, `/auth/yo`, cambio de contraseña |
| C-09 | roles-personal-eventos | CRITICO | C-08 | `POST /usuarios`, roles con vigencia, `GET /eventos` |
| C-13 | ordenes-alta-estados | ALTO | C-10, C-11 | Alta de orden con ítems, catálogo de estados |
| C-14 | ordenes-transiciones | CRITICO | C-13, C-12 | Iniciar, terminar (stock atómico + `BackgroundTasks`), cancelar |

**Además:** los `propose` de todos los changes, la revisión de los PR de Lauti y Nico, los `archive` y la cadena de migraciones de Alembic.

**Cuello de botella:** C-07 y C-08 bloquean a todos. Mientras los hace, adelanta los `propose` de C-06, C-10 y C-11 para que estén listos apenas cierre C-08.

### Lauti — Implementación
| Change | Nombre | Governance | Depende de | Entrega |
|--------|--------|------------|------------|---------|
| C-06 | seed-script | MEDIO | C-04, C-05 | `seed.py` idempotente (catálogo primero) |
| C-10 | clientes-vehiculos | MEDIO | C-08 | Clientes, vehículos con baja lógica, `/mis-vehiculos` |
| C-15 | ordenes-lecturas-sin-n-plus-1 | MEDIO | C-13 | Listados y detalle de órdenes sin N+1, `/mis-ordenes` |

C-06 puede **arrancar ya** (C-04 y C-05 están cerrados). Lauti hizo C-05, así que ya conoce el hash y el token que usa el seed.

### Nico — Implementación y verificación
| Change | Nombre | Governance | Depende de | Entrega |
|--------|--------|------------|------------|---------|
| C-11 | repuestos-catalogo | MEDIO | C-08 | CRUD de repuestos, búsqueda con parámetros ligados |
| C-12 | repuestos-stock-precios | ALTO | C-11 | Reposición, movimientos, historial de precios (revisión de Mati antes del merge) |
| C-16 | verificacion-http-readme | BAJO | C-06, C-09, C-14, C-15 | `.http` de todos los casos, README desde cero, evidencias |

Los casos `.http` de C-16 se pueden **empezar ya**, escribiéndolos a partir de la matriz endpoint↔rol↔código de [03_actores_y_roles.md](../knowledge-base/03_actores_y_roles.md) y de los casos de [06_funcionalidades.md](../knowledge-base/06_funcionalidades.md). Cuando cada endpoint exista, sólo hay que ajustarlos y correrlos.

## 5. Orden de trabajo (pasos orientativos)

| Paso | Mati | Lauti | Nico |
|------|------|-------|------|
| 1-4 | C-01 a C-04 ✓ | C-05 ✓ | — |
| 5 | C-07 · `propose` de C-06, C-10, C-11 | C-06 | Casos `.http` de C-16 por adelantado |
| 6 | C-08 · `propose` de C-12, C-15 | (cont. C-06) | (cont. casos `.http`) |
| 7 | C-09 | C-10 | C-11 |
| 8 | C-13 (necesita C-10 y C-11) | (cont. C-10) | C-12 |
| 9 | C-14 | C-15 | (cont. C-12) |
| 10 | Revisión final + `archive` | `.http` de clientes y lecturas de órdenes | C-16: cierre (README, ciclo de migraciones, evidencias) |

Gates (de `CHANGES.md`): GATE 2 = C-03 (fork: C-04, C-07, C-06) · GATE 3 = C-07 · GATE 4 = C-08 (fork: C-09, C-10, C-11) · GATE 5 = C-11 · GATE 6 = C-13 y C-12 · GATE 7 = C-09, C-14, C-15, C-06.

## 6. C-16 — Entregables finales

| Parte | Quién |
|-------|-------|
| `.http` de clientes, vehículos y lecturas de órdenes | Lauti |
| `.http` de usuarios/auth y órdenes (alta, terminar, cancelar) | Mati los revisa; Nico los arma desde la matriz |
| `.http` de repuestos, `README.md` desde cero, evidencia C-14 (psql) y C-15 (consultas fijas del detalle), ciclo de migraciones, chequeo de secretos | Nico |

Condición bloqueante de la consigna: `alembic upgrade head` sobre base vacía, sin credenciales reales en el repo. Lo verifican **los tres** antes de entregar.

## 7. Guía de herramientas para Lauti y Nico

### 7.1 Para qué usar cada una

| Herramienta | Usarla para | Evitarla para |
|-------------|-------------|---------------|
| **GitHub Copilot** (modo agente en VS Code) | Implementar las tareas del `tasks.md` una por una, con el archivo abierto. Los modelos "premium" tienen un cupo mensual: guardarlos para lo difícil (C-12, C-15) | Tareas mecánicas que puede hacer un modelo gratis (gasta cupo) |
| **Modelos gratuitos de OpenCode** | Tareas mecánicas: schemas de Pydantic, CRUDs que copian un patrón ya hecho, casos `.http`, `seed.py` | Decisiones de diseño o lógica con transacciones (stock, permisos) |
| **Gemini** (ventana de contexto grande) | Leer la KB entera o un diff completo y revisarlo contra las reglas duras **antes** de abrir el PR; preguntar "qué significa esto" sobre el dominio | Escribir código directamente en el repo sin el `tasks.md` como guía |
| **Mati (Claude Pro)** | Cuando algo se traba: después de **2 intentos fallidos** con el mismo error, avisar a Mati en vez de seguir insistiendo | — |

### 7.2 Que el agente conozca las reglas del proyecto

- **OpenCode** y **Copilot** leen `AGENTS.md` de la raíz del repo: ahí están las reglas duras. Verificar que el agente lo tenga en cuenta (si no, pedírselo explícitamente en el prompt).
- **Gemini CLI** busca por defecto un `GEMINI.md`; configurarlo para que lea `AGENTS.md` o pasárselo como contexto en el prompt.
- Los comandos `/opsx:*` son de Claude Code. Sin Claude, el equivalente es el CLI de OpenSpec, que funciona con cualquier herramienta:

```bash
openspec instructions apply --change "<nombre-del-change>"
```

Eso imprime las instrucciones de implementación del change; se le pasan al agente junto con el `tasks.md`.

### 7.3 Flujo por change (para quien implementa)

1. Mati deja el `propose` commiteado en la rama `feat/C-NN-<nombre>` y avisa.
2. Hacer `git pull` y pasarse a esa rama.
3. Leer `proposal.md` y `design.md` del change en `openspec/changes/<nombre>/`. No hace falta entender todo, pero sí saber qué se construye y por qué.
4. Pedirle al agente **una tarea por vez** del `tasks.md` (ver el prompt de 7.4). No pedirle "implementá todo el change".
5. Después de cada tarea: correr el caso `.http` que indique la tarea y `ruff check .`. Si pasa, marcar `[x]` en `tasks.md` y commitear (`feat(C-NN): ...`).
6. Al terminar todas las tareas: pedirle a Gemini una revisión del diff contra `AGENTS.md` (ver 7.4), corregir lo que encuentre y abrir el PR hacia `main`.
7. Mati revisa, mergea y hace el `archive`.

### 7.4 Prompts de referencia

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

### 7.5 Errores típicos de los modelos chicos en este proyecto

Revisar especialmente esto antes de abrir un PR:

- `session.commit()` dentro de un repositorio o un servicio (va `flush()`; el commit lo hace el UoW).
- Handlers sin `async def`, o bcrypt llamado directo sin `to_thread`.
- Relaciones leídas sin precarga (`selectinload`/`joinedload` en el repositorio): genera carga perezosa y falla en async.
- Schemas de entrada sin `model_config = ConfigDict(extra="forbid")`.
- `float` para precios (va `Decimal`) o `datetime` sin zona horaria.
- SQL armado con f-strings con datos del usuario.
- Crear una migración nueva: **no hacerlo**; si hace falta cambiar el esquema, se le pide a Mati.

## 8. Reglas de trabajo en equipo

1. **Una rama por change**: `feat/C-NN-<nombre>`. Mati la crea con el `propose`; quien implementa trabaja sobre esa misma rama.
2. **Flujo por change:** `propose` (Mati) → implementar (según el reparto) → PR → revisión y `archive` (Mati) → marcar `[x]` en `CHANGES.md`.
3. **Governance:** CRITICO y ALTO se diseñan y revisan antes de escribir código. C-12 (ALTO) lo implementa Nico, pero no se mergea sin la revisión de Mati.
4. **Pull requests:** todo change va por PR hacia `main`. Mati revisa los de Lauti y Nico; Lauti o Nico revisan los de Mati (con ayuda de Gemini), así todos conocen el código crítico.
5. **Si una tarea es ambigua**, no se deja que el modelo decida: se avisa a Mati y se reescribe la tarea en el `tasks.md`.
6. **Commits:** conventional commits (`feat:`, `fix:`, `docs:`), sin líneas de co-autoría de IA. Un commit por tarea o unidad lógica.
7. **No avanzar** sobre un change cuyas dependencias no estén mergeadas en `main`.
8. **Antes de commitear:** `ruff check .` y `git diff --check` en verde.

## 9. Puntos de conflicto a coordinar

| Archivo compartido | Riesgo | Cómo evitarlo |
|--------------------|--------|---------------|
| `main.py` | Todos registran su router | Cambio mínimo (una línea por módulo); resolver el merge sin reordenar |
| `migrations/versions/` | Dos cabezas de Alembic si dos personas crean migraciones | **Solo Mati** crea migraciones. Si alguien necesita cambiar el esquema, se lo pide |
| `requirements.txt` y `env.example` | Dependencias o variables nuevas simultáneas | Avisar en el PR; mergear en orden |
| `app/core/*` | Cambiar el cimiento rompe a los demás | Solo Mati modifica `repository.py`, `unit_of_work.py`, `paginacion.py` y `dependencies.py`; `security.py` (de Lauti) no se toca sin revisión de Mati |
| `CHANGES.md` | Dos personas marcando `[x]` | Se marca en el `archive`, que hace Mati |
| `seed.py` | Lo usan todos los `.http` | Lo mantiene Lauti; los demás piden datos nuevos por PR |

## 10. Pendientes de equipo
- [ ] Completar los usuarios de GitHub en la sección 1.
- [ ] Confirmar el reparto nuevo con Lauti y Nico.
- [ ] Que Lauti y Nico verifiquen que su agente (Copilot / OpenCode / Gemini) lee `AGENTS.md`.
- [ ] Definir el canal y la frecuencia de sincronización (qué se avisa al cerrar un gate o al dejar listo un `propose`).
- [ ] Cada integrante con su PostgreSQL 16 local y su propio `.env` (no versionado).
