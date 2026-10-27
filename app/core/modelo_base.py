"""Base compartida de los modelos de tabla (convención de nombres y utilidades).

Todos los `models.py` de `app/modules/*` importan este módulo ANTES de declarar una tabla:
al importarlo se fija `SQLModel.metadata.naming_convention`, y SQLAlchemy nombra cada
restricción e índice en el momento en que se adjunta a su tabla. Importarlo después dejaría
restricciones con nombres que dependen del motor (`usuario_email_key`) y el servicio ya no
podría asociar una violación con su mensaje (ver `restriccion_violada` en `app/core/errores.py`).

Con `%(constraint_name)s` en `ck`, un `CheckConstraint` sin `name` falla al generar el DDL:
no se puede olvidar nombrarlo.

Esquema sólo con Alembic: nada de este módulo crea tablas.
"""

from datetime import UTC, datetime

from sqlmodel import SQLModel

NAMING_CONVENTION: dict[str, str] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(column_0_label)s",
}

SQLModel.metadata.naming_convention = NAMING_CONVENTION

# Relaciones sin carga perezosa: leer una relación que nadie precargó lanza
# `InvalidRequestError` sin emitir SQL. La precarga (`selectinload`/`joinedload`) la declara el
# método del repositorio y anula el `raise` para esa consulta. Usar siempre copiando:
# `sa_relationship_kwargs={**LAZY_RAISE, ...}`.
LAZY_RAISE: dict[str, str] = {"lazy": "raise"}


def ahora_utc() -> datetime:
    """Instante actual con zona UTC (mismo criterio que `SoftDeleteRepository`)."""
    return datetime.now(UTC)
