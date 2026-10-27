"""Modelos del dominio clientes: cliente y vehículo.

Mismas reglas que `app/modules/usuarios/models.py` (convención de nombres desde
`app.core.modelo_base`, relaciones con `lazy="raise"`, referencias entre módulos por texto,
sin `onupdate`): ver el docstring de ese módulo.

- `cliente.usuario_id` es UNIQUE y admite nulo: un usuario tiene a lo sumo una ficha y varias
  fichas pueden no tener usuario. Como la restricción UNIQUE ya indexa la columna, no se agrega
  un índice propio.
- Baja lógica de `vehiculo` (`borrado_en`, compatible con `SoftDeleteRepository`): la patente es
  única sólo entre vehículos vigentes (índice único parcial).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.core.modelo_base import LAZY_RAISE

if TYPE_CHECKING:
    from app.modules.ordenes.models import OrdenTrabajo
    from app.modules.usuarios.models import Usuario


class Cliente(SQLModel, table=True):
    __tablename__ = "cliente"

    id: int | None = Field(default=None, primary_key=True)
    usuario_id: int | None = Field(default=None, foreign_key="usuario.id", unique=True)
    nombre: str
    documento: str = Field(unique=True)
    telefono: str

    usuario: Optional["Usuario"] = Relationship(
        back_populates="cliente", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
    vehiculos: list["Vehiculo"] = Relationship(
        back_populates="cliente", sa_relationship_kwargs=dict(LAZY_RAISE)
    )


class Vehiculo(SQLModel, table=True):
    __tablename__ = "vehiculo"
    __table_args__ = (
        CheckConstraint("anio BETWEEN 1950 AND 2100", name="anio_rango"),
        # Unicidad sólo entre vehículos vigentes (RN01, DD-02): vender un auto libera la patente.
        Index(
            "uq_vehiculo_patente",
            "patente",
            unique=True,
            postgresql_where=text("borrado_en IS NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    cliente_id: int = Field(foreign_key="cliente.id", index=True)
    patente: str
    marca: str
    modelo: str
    anio: int
    borrado_en: datetime | None = None

    cliente: "Cliente" = Relationship(
        back_populates="vehiculos", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
    ordenes: list["OrdenTrabajo"] = Relationship(
        back_populates="vehiculo", sa_relationship_kwargs=dict(LAZY_RAISE)
    )
