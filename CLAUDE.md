# Taller mecánico — Instrucciones para Agentes

> Este archivo (y su copia `CLAUDE.md`) es lo PRIMERO que todo agente lee al entrar al repo.
> Generado a partir de `knowledge-base/` y `CHANGES.md`. No editar a mano sin re-sincronizar ambos archivos.

API asincrónica para un taller mecánico (clientes, vehículos, órdenes de trabajo, stock y acceso por roles). TP integrador de Programación III (caps. 1–6). Consigna original: `docs/TP_Cap1a6_Consigna.pdf`.

---

## Stack Tecnológico

| Capa | Tecnología | Versión mínima |
|------|------------|----------------|
| Lenguaje | Python | 3.12 |
| Framework web | FastAPI (todos los handlers `async def`) | 0.111 |
| Modelos de tabla | SQLModel | 0.0.45 |
| ORM / motor | SQLAlchemy 2.0 asincrónico | 2.0 |
| Driver | asyncpg | 0.30 |
| Base de datos | PostgreSQL | 16 |
| Migraciones | Alembic (plantilla asincrónica) | 1.13 |
| Configuración | pydantic-settings | 2.0 |
| Hash de contraseñas | bcrypt | 4.0 |
| Token | PyJWT | 2.8 |
| Servidor | uvicorn (de `fastapi[standard]`) | — |

Arquitectura en capas por módulo: **Router → Service → UoW → Repository → Model**. Módulos: `health`, `usuarios`, `clientes`, `repuestos`, `ordenes`.

Detalle completo: [knowledge-base/02_descripcion_general.md](knowledge-base/02_descripcion_general.md)

---

## Base de Conocimiento

La fuente de verdad del dominio vive en `knowledge-base/`. **Leé el archivo relevante ANTES de implementar.**

| Archivo | Cuándo leerlo |
|---------|---------------|
| [01_vision_y_objetivos.md](knowledge-base/01_vision_y_objetivos.md) | Propósito, alcance y pesos de evaluación |
| [03_actores_y_roles.md](knowledge-base/03_actores_y_roles.md) | Auth, RBAC, matriz endpoint↔rol↔códigos (validada) |
| [04_modelo_de_datos.md](knowledge-base/04_modelo_de_datos.md) | Entidades, restricciones, migraciones, seed |
| [05_reglas_de_negocio.md](knowledge-base/05_reglas_de_negocio.md) | Reglas RN01–RN20 |
| [06_funcionalidades.md](knowledge-base/06_funcionalidades.md) | Historias por épica y casos C-01…C-19 |
| [07_flujos_principales.md](knowledge-base/07_flujos_principales.md) | Flujos E2E (login, órdenes, stock) |
| [08_arquitectura_propuesta.md](knowledge-base/08_arquitectura_propuesta.md) | Patrones, estructura obligatoria, seguridad, variables de entorno |
| [09_decisiones_y_supuestos.md](knowledge-base/09_decisiones_y_supuestos.md) | Decisiones ya tomadas (token 1800 s, bcrypt 12, asyncpg…) |
| [10_preguntas_abiertas.md](knowledge-base/10_preguntas_abiertas.md) | Estado de las preguntas abiertas (las de prioridad Alta están resueltas) |

---

## Skills Disponibles

Las skills de **proyecto** están versionadas en el repo (`.agents/skills/`, con symlink en `.claude/skills/`, y `skills-lock.json`): todo el equipo las recibe al clonar. Las de **usuario** viven en `~/.claude/skills` de cada persona y **no** están en el repo.

| Agente | Rol | Skills de proyecto (en el repo) | Skills de usuario (opcionales, cada uno las instala) |
|--------|-----|--------------------------------|------------------------------------------------------|
| **Backend Core** | FastAPI / SQLModel / UoW / migraciones | `fastapi`, `fastapi-templates`, `sqlalchemy-alembic-expert-best-practices-code-review` | `fastapi-python`, `supabase-postgres-best-practices` |
| **Backend Seguridad** | Auth, JWT, RBAC, cookies | `fastapi` | `auth-implementation-patterns` |
| **Verificación** | Casos `.http`, sólo-agregado | — | `python-testing-patterns`, `tdd` |
| **Orquestación** | OPSX / SDD / docs | (comandos `/opsx:*` en `.claude/commands/opsx/`) | `kb-creator`, `roadmap-generator`, `agent-instruction` |

Cargá la skill correspondiente al contexto ANTES de escribir código. Sin pytest en este TP: la verificación es por `.http` y `test/solo_agregado.sql`.

> Los compact rules de cada skill los resuelve el orquestador desde `.atl/skill-registry.md` (generado por `skill-registry`; no versionado — no está en el repo). Esta tabla solo mapea skill→rol.

---

## Roadmap de Changes

El plan completo está en [CHANGES.md](CHANGES.md). Resumen:

- **Total**: 16 changes en 6 fases (Fundación → Capas/modelo/migraciones → Auth y autorización → Clientes y repuestos → Órdenes → Verificación y entregables).
- **Camino crítico** (9): `C-01 → C-02 → C-03 → C-07 → C-08 → C-10 → C-13 → C-14 → C-16`.
- **Primer change**: `C-01` (foundation-setup).

**Antes de cualquier `/opsx:propose`**: leé [CHANGES.md](CHANGES.md), identificá las dependencias del change y los archivos de "Leer antes".

---

## Reglas Duras (específicas del proyecto)

> Reglas globales ya definidas en `~/.claude/CLAUDE.md` (orquestador, governance, TDD, engram): el proyecto las hereda. Acá viven solo las reglas **específicas de este proyecto** + las universales que el global no cubra.

Son contrato; romperlas es un defecto.

**Código**
- NUNCA `commit()` en un repositorio, UoW construido dentro de un servicio, ni sesión cerrada por el UoW → los repos hacen `flush()`, el router construye el UoW y el servicio lo abre con `async with`. Única excepción declarada (en comentario): `intento_acceso` usa sesión y transacción propias, confirmadas siempre (RN08).
- NUNCA handler sin `async def` ni bcrypt en el bucle de eventos → `to_thread` + semáforo, y calcular el hash antes de abrir la transacción.
- NUNCA lectura con carga perezosa ni SQL armado con datos del usuario → precarga declarada en el método del repositorio y parámetros ligados.
- NUNCA schema de entrada sin `extra="forbid"`, `password_hash` en una respuesta ni texto de la base en un error → traducir `IntegrityError` a mensajes propios; ninguna entrada inválida termina en 500.

**Datos y secretos**
- NUNCA `create_all`, ni credenciales o clave de firma con valor por defecto o dentro del repo → el esquema se crea sólo con Alembic y los secretos salen del entorno (`.env` no se versiona; `env.example` sin secretos).
- NUNCA `float` para dinero ni `datetime` sin zona → `NUMERIC`/`Decimal` y `timestamptz`.

**Proceso**
- NUNCA commitear, pushear ni buildear sin que el usuario lo pida.
- Commits con *conventional commits* (`feat:`, `fix:`, `docs:`…) y sin líneas de co-autoría de IA.

---

## Flujo de Trabajo

```
1. Leer la KB relevante (knowledge-base/)        → entender el dominio
2. Identificar el change en CHANGES.md           → respetar dependencias
3. /opsx:propose C-NN-nombre                     → proposal + design + specs + tasks
4. Implementar las tasks (cargando skills)       → respetando las reglas duras
5. /opsx:archive C-NN-nombre + marcar [x]        → cerrar el change
```

Aplicar TODAS las reglas duras en cada paso. Ante conflicto entre la KB y este archivo, las reglas duras prevalecen.
