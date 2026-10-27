"""Modelos del dominio repuestos: repuesto, movimiento de stock e historial de precios.

Mismas reglas que `app/modules/usuarios/models.py` (convención de nombres desde
`app.core.modelo_base`, relaciones con `lazy="raise"`, referencias entre módulos por texto,
sin `onupdate`): ver el docstring de ese módulo.

- Dinero: `Decimal` con `max_digits`/`decimal_places` -> `NUMERIC(10, 2)`; nunca `float`.
- `movimiento_stock` e `historial_precio_repuesto` son de sólo agregado (el trigger lo impone
  C-04). Sus FK `usuario_id` y `orden_id` se leen como id: no tienen relación ORM.
- Baja lógica de `repuesto` (`borrado_en`, compatible con `SoftDeleteRepository`): el código es
  único sólo entre repuestos vigentes (índice único parcial).
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Index, func, text
from sqlmodel import Field, Relationship, SQLModel

from app.core.modelo_base import LAZY_RAISE, ahora_utc

if TYPE_CHECKING:
    from app.modules.ordenes.models import ItemOrden


class Repuesto(SQLModel, table=True):
    __tablename__ = "repuesto"
    __table_args__ = (
        CheckConstraint("precio > 0", name="precio_positivo"),
        CheckConstraint("stock >= 0", name="stock_no_negativo"),
        # Unicidad sólo entre repuestos vigentes (RN01, DD-02): dar de baja libera el código.
        Index(
            "uq_repuesto_codigo",
            "codigo",
            unique=True,
            postgresql_where=text("borrado_en IS NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    codigo: str
    descripcion: str
    precio: Decimal = Field(max_digits=10, decimal_places=2)
    stock: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    borrado_en: datetime | None = None

    items: list["ItemOrden"] = Relationship(
        back_populates="repuesto", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
    movimientos: list["MovimientoStock"] = Relationship(
        back_populates="repuesto", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
    historial_precios: list["HistorialPrecioRepuesto"] = Relationship(
        back_populates="repuesto", sa_relationship_kwargs=dict(LAZY_RAISE)
    )


class MovimientoStock(SQLModel, table=True):
    __tablename__ = "movimiento_stock"
    __table_args__ = (CheckConstraint("cantidad <> 0", name="cantidad_no_nula"),)

    id: int | None = Field(default=None, primary_key=True)
    repuesto_id: int = Field(foreign_key="repuesto.id", index=True)
    orden_id: int | None = Field(default=None, foreign_key="orden_trabajo.id", index=True)
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    # Con signo: positivo entra stock, negativo sale (SU-04).
    cantidad: int
    motivo: str
    cuando: datetime = Field(
        default_factory=ahora_utc, sa_column_kwargs={"server_default": func.now()}
    )

    repuesto: "Repuesto" = Relationship(
        back_populates="movimientos", sa_relationship_kwargs=dict(LAZY_RAISE)
    )


class HistorialPrecioRepuesto(SQLModel, table=True):
    __tablename__ = "historial_precio_repuesto"
    __table_args__ = (
        CheckConstraint("precio_nuevo > 0", name="precio_nuevo_positivo"),
        CheckConstraint("precio_nuevo <> precio_anterior", name="precio_distinto"),
    )

    id: int | None = Field(default=None, primary_key=True)
    repuesto_id: int = Field(foreign_key="repuesto.id", index=True)
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    precio_anterior: Decimal = Field(max_digits=10, decimal_places=2)
    precio_nuevo: Decimal = Field(max_digits=10, decimal_places=2)
    cuando: datetime = Field(
        default_factory=ahora_utc, sa_column_kwargs={"server_default": func.now()}
    )

    repuesto: "Repuesto" = Relationship(
        back_populates="historial_precios", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
