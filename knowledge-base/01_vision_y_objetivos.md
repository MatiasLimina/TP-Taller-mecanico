# Visión y Objetivos

## Propósito del sistema
API asincrónica para el trabajo diario de un taller mecánico: gestión de clientes y vehículos, órdenes de trabajo con repuestos, control de stock y acceso por roles. Es un Trabajo Práctico integrador (Programación III, Tecnicatura Universitaria en Programación, capítulos 1 a 6) que debe demostrar FastAPI + SQLModel/SQLAlchemy async + PostgreSQL + Alembic + autenticación/autorización + Repository/Unit of Work.

Fuente: `docs/TP_Cap1a6_Consigna.pdf` (22 páginas).

## Objetivos de aprendizaje (lo que el TP debe demostrar)
1. API asincrónica en capas: Router → Service → UoW → Repository → Model.
2. Modelo con asociación, composición, uno a uno y tabla de catálogo traducido a esquema versionado con Alembic (incluye una migración escrita a mano).
3. Autenticación con bcrypt + JWT en cookie HttpOnly, sin bloquear el servidor y sin revelar qué cuentas existen.
4. Autorización con roles consultados en la base en cada petición, con vigencia; distinguir siempre 401 de 403.
5. Escrituras de una operación de negocio en una sola transacción.
6. Delegar en la base lo que la base garantiza: unicidad, FKs, CHECKs, sólo-agregado.

## Objetivos por actor
| Actor | Objetivo principal | Secundarios |
|-------|--------------------|-------------|
| RECEPCION | Dar de alta clientes y vehículos y abrir órdenes | Cancelar órdenes, consultar repuestos |
| MECANICO | Tomar una orden, repararla y terminarla | Consultar repuestos y órdenes |
| ADMIN | Mantener catálogo de repuestos, reponer stock, administrar personal y roles | Auditar eventos de seguridad, terminar/cancelar cualquier orden |
| CLIENTE | Registrarse solo y consultar el estado de sus vehículos | Cancelar sus órdenes pendientes |

## Alcance
- Módulos mínimos: `health`, `usuarios`, `clientes`, `repuestos`, `ordenes`.
- Registro, login (cookie HttpOnly), logout, `/auth/yo`, cambio de contraseña (obligatorio opcional).
- Roles con vigencia (alta, vencimiento, revocación sin borrar).
- CRUD de clientes, vehículos (baja lógica), repuestos (baja lógica, stock sólo por movimientos, historial de precios).
- Órdenes: alta con ítems (composición), iniciar / terminar / cancelar, historial de estados.
- Terminar orden descuenta stock y registra movimientos en una sola transacción; aviso simulado con `BackgroundTasks`.
- Historiales de sólo agregado impuestos por trigger de base.
- Límite de intentos de login (429 + Retry-After).
- Migraciones Alembic (autogenerada + manual), `seed.py`, archivos `.http` de prueba.

## Fuera de alcance
- Concurrencia (capítulo 7): no se evalúa la actualización perdida de stock entre órdenes simultáneas (no hay bloqueo ni aislamiento elevado).
- Colas de tareas con Redis (capítulo 8): el aviso es `BackgroundTasks` en el mismo proceso; se pierde si el proceso se reinicia y no reintenta (aceptado).
- Segundo mecanismo de sólo-agregado por permisos del rol de base (sección 6.9): no se pide (un solo rol de base).
- Frontend: no hay.

## Métricas de éxito (criterios de evaluación)
| Criterio | Peso |
|----------|------|
| Ej.1 Proyecto, configuración y ciclo de vida | 8 % |
| Ej.2 Modelos, relaciones y migraciones | 14 % |
| Ej.3 Contratos y CRUD | 10 % |
| Ej.4 Autenticación | 16 % |
| Ej.5 Autorización | 14 % |
| Ej.6 Repositorios y Unit of Work | 20 % |
| Ej.7 Integridad: sólo agregado e intento de acceso | 10 % |
| Ej.8 Lecturas sin N+1 y asincronía | 8 % |

Condición bloqueante: un proyecto que no levanta, que no crea el esquema con `alembic upgrade head` sobre base vacía o que contiene credenciales reales en el repo **no se corrige** hasta subsanar.
