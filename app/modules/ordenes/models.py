"""Modelos del dominio órdenes: catálogo de estados, orden de trabajo, ítems e historial de estados.

Mismas reglas que `app/modules/usuarios/models.py` (convención de nombres desde
`app.core.modelo_base`, relaciones con `lazy="raise"`, referencias entre módulos por texto,
sin `onupdate`): ver el docstring de ese módulo.

Estados de una orden:
- `EstadoOrden` es la tabla catálogo (filas: `codigo` de texto como PK, `descripcion`, `posicion`,
  `es_final`); `CodigoEstado` es el enum del código (contrato de la API y vocabulario del servicio).
- `orden_trabajo.estado` y `historial_estado_orden.desde_estado`/`hasta_estado` son FK a
  `estado_orden.codigo`: la base rechaza un estado que no esté en el catálogo, sin CHECK con la lista.
- Las columnas se anotan como `str`, NO con el enum: anotar con un `Enum` crearía un tipo ENUM nativo
  de PostgreSQL. La base guarda el texto del código (`PENDIENTE`), legible igual en psql que en la API.
- La migración crea el catálogo vacío. El seed (C-06) carga sus filas iterando `CodigoEstado`; agregar
  un estado exige tocar el enum, el seed y el servicio.

Composición orden-ítem: `item_orden.orden_id` es NOT NULL con `ON DELETE CASCADE`; en el ORM
`OrdenTrabajo.items` borra los ítems huérfanos y no los carga al borrar (`passive_deletes`), la
base los elimina. Las demás FK quedan con la acción por defecto (`NO ACTION`): borrar algo
referenciado falla, lo que protege historiales y movimientos.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, UniqueConstraint, func
from sqlmodel import Field, Relationship, SQLModel

from app.core.modelo_base import LAZY_RAISE, ahora_utc

if TYPE_CHECKING:
    from app.modules.clientes.models import Vehiculo
    from app.modules.repuestos.models import Repuesto
    from app.modules.usuarios.models import Usuario


class CodigoEstado(StrEnum):
    PENDIENTE = "PENDIENTE"
    EN_REPARACION = "EN_REPARACION"
    TERMINADA = "TERMINADA"
    CANCELADA = "CANCELADA"


class EstadoOrden(SQLModel, table=True):
    __tablename__ = "estado_orden"

    codigo: str = Field(primary_key=True)
    descripcion: str
    posicion: int = Field(unique=True)
    es_final: bool

    ordenes: list["OrdenTrabajo"] = Relationship(
        back_populates="estado_catalogo", sa_relationship_kwargs=dict(LAZY_RAISE)
    )


class OrdenTrabajo(SQLModel, table=True):
    __tablename__ = "orden_trabajo"
    __table_args__ = (CheckConstraint("total >= 0", name="total_no_negativo"),)

    id: int | None = Field(default=None, primary_key=True)
    vehiculo_id: int = Field(foreign_key="vehiculo.id", index=True)
    mecanico_id: int | None = Field(default=None, foreign_key="usuario.id", index=True)
    estado: str = Field(foreign_key="estado_orden.codigo", index=True)
    falla: str
    creada_en: datetime = Field(
        default_factory=ahora_utc, sa_column_kwargs={"server_default": func.now()}
    )
    # Sin default: lo calcula siempre el servicio (RN10).
    total: Decimal = Field(max_digits=12, decimal_places=2)

    # El atributo no puede llamarse `estado`: es la columna.
    estado_catalogo: "EstadoOrden" = Relationship(
        back_populates="ordenes", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
    vehiculo: "Vehiculo" = Relationship(
        back_populates="ordenes", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
    mecanico: Optional["Usuario"] = Relationship(
        back_populates="ordenes_asignadas", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
    items: list["ItemOrden"] = Relationship(
        back_populates="orden",
        cascade_delete=True,
        passive_deletes=True,
        sa_relationship_kwargs={**LAZY_RAISE, "order_by": "ItemOrden.id"},
    )
    historial: list["HistorialEstadoOrden"] = Relationship(
        back_populates="orden",
        sa_relationship_kwargs={**LAZY_RAISE, "order_by": "HistorialEstadoOrden.id"},
    )


class ItemOrden(SQLModel, table=True):
    __tablename__ = "item_orden"
    # La unicidad (orden_id, repuesto_id) ya indexa `orden_id` como primera columna.
    __table_args__ = (
        UniqueConstraint("orden_id", "repuesto_id"),
        CheckConstraint("cantidad > 0", name="cantidad_positiva"),
        CheckConstraint("precio_unitario > 0", name="precio_unitario_positivo"),
    )

    id: int | None = Field(default=None, primary_key=True)
    orden_id: int = Field(foreign_key="orden_trabajo.id", ondelete="CASCADE")
    repuesto_id: int = Field(foreign_key="repuesto.id", index=True)
    cantidad: int
    precio_unitario: Decimal = Field(max_digits=10, decimal_places=2)

    orden: "OrdenTrabajo" = Relationship(
        back_populates="items", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
    repuesto: "Repuesto" = Relationship(
        back_populates="items", sa_relationship_kwargs=dict(LAZY_RAISE)
    )


class HistorialEstadoOrden(SQLModel, table=True):
    __tablename__ = "historial_estado_orden"

    id: int | None = Field(default=None, primary_key=True)
    orden_id: int = Field(foreign_key="orden_trabajo.id", index=True)
    # Nulo en la primera línea de una orden (todavía no tenía estado previo).
    desde_estado: str | None = Field(default=None, foreign_key="estado_orden.codigo", index=True)
    hasta_estado: str = Field(foreign_key="estado_orden.codigo", index=True)
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    cuando: datetime = Field(
        default_factory=ahora_utc, sa_column_kwargs={"server_default": func.now()}
    )

    orden: "OrdenTrabajo" = Relationship(
        back_populates="historial", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
