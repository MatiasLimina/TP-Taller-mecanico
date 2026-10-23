# Taller mecánico — Base de Conocimiento

Base de conocimiento generada a partir de `docs/TP_Cap1a6_Consigna.pdf` (TP Programación III, capítulos 1–6: API de órdenes de trabajo, stock y acceso con FastAPI + PostgreSQL).

## Índice de Archivos

| Archivo | Contenido |
|---------|-----------|
| [01_vision_y_objetivos.md](01_vision_y_objetivos.md) | Propósito, objetivos de aprendizaje, alcance, fuera de alcance, pesos de evaluación |
| [02_descripcion_general.md](02_descripcion_general.md) | Stack, capas, endpoints, requisitos no funcionales |
| [03_actores_y_roles.md](03_actores_y_roles.md) | Actores, roles con vigencia, matriz endpoint↔rol |
| [04_modelo_de_datos.md](04_modelo_de_datos.md) | Tablas, restricciones, ERD, seed |
| [05_reglas_de_negocio.md](05_reglas_de_negocio.md) | RN01–RN20 por dominio |
| [06_funcionalidades.md](06_funcionalidades.md) | Épicas e historias con criterios (casos C-01…C-19) |
| [07_flujos_principales.md](07_flujos_principales.md) | Login, autorización, registro, órdenes, stock, precios |
| [08_arquitectura_propuesta.md](08_arquitectura_propuesta.md) | Patrones, estructura obligatoria, seguridad, variables de entorno |
| [09_decisiones_y_supuestos.md](09_decisiones_y_supuestos.md) | DD-xx y SU-xx |
| [10_preguntas_abiertas.md](10_preguntas_abiertas.md) | Inconsistencias y preguntas priorizadas |

## Quick Start para Desarrolladores
1. Dominio → [01](01_vision_y_objetivos.md), [03](03_actores_y_roles.md)
2. Datos → [04](04_modelo_de_datos.md)
3. Reglas → [05](05_reglas_de_negocio.md)
4. Arquitectura → [02](02_descripcion_general.md), [08](08_arquitectura_propuesta.md)
5. Implementar → [07](07_flujos_principales.md), [06](06_funcionalidades.md)
6. Antes de codificar → [10](10_preguntas_abiertas.md) (¡verificar tablas de endpoints contra el PDF!)

## Resumen Ejecutivo
API asincrónica en capas (Router → Service → UoW → Repository → Model) para un taller mecánico, con PostgreSQL 16 y Alembic (dos migraciones, una manual con trigger de sólo agregado), autenticación bcrypt + JWT en cookie HttpOnly, autorización por roles vigentes consultados en base, y transacciones únicas para registro, terminación de órdenes (descuento de stock) y cambio de precio. Fuera de alcance: concurrencia (cap. 7) y colas (cap. 8).
