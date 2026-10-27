"""Modelos del dominio usuarios: usuario, asignación de rol, intentos de acceso y eventos de seguridad.

Reglas que valen para todos los `models.py` de `app/modules/*`:

- Se importa `app.core.modelo_base` ANTES de declarar tablas: fija la convención de nombres de
  restricciones e índices (`uq_usuario_email`, `fk_…`, `ix_…`) que el servicio usa para traducir
  violaciones a mensajes propios.
- Ninguna relación se carga sola (`lazy="raise"`): leer una relación no precargada lanza
  `InvalidRequestError` sin emitir SQL. El método del repositorio que devuelve la entidad declara
  la precarga (`selectinload`/`joinedload`) de lo que el servicio va a tocar.
- Las relaciones entre módulos se nombran como texto (`"Cliente"`) con el import bajo
  `TYPE_CHECKING`, para evitar imports circulares; se resuelven al configurar los mappers, por eso
  la aplicación y Alembic importan el registro único `app/modules/modelos.py`.
- No hay `onupdate`/`server_onupdate`: un atributo expirado dispararía una carga perezosa.
- Este archivo NO usa `from __future__ import annotations`: SQLModel necesita las anotaciones
  evaluadas para construir columnas y relaciones.

Roles: la columna `asignacion_rol.rol` guarda el texto del enum `Rol`, sin tipo ENUM nativo de
PostgreSQL. Los valores admitidos los impone un CHECK generado desde `Rol`; Alembic NO detecta
cambios en CHECKs, así que tocar `Rol` exige escribir a mano una migración que reemplace
`ck_asignacion_rol_rol_valido`.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Index, func, text
from sqlmodel import Field, Relationship, SQLModel

from app.core.modelo_base import LAZY_RAISE, ahora_utc

if TYPE_CHECKING:
    from app.modules.clientes.models import Cliente
    from app.modules.ordenes.models import OrdenTrabajo


class Rol(StrEnum):
    ADMIN = "ADMIN"
    RECEPCION = "RECEPCION"
    MECANICO = "MECANICO"
    CLIENTE = "CLIENTE"


# Constantes del código (no datos del usuario): el CHECK se arma desde el enum.
_ROLES_SQL = ", ".join(f"'{rol.value}'" for rol in Rol)


class Usuario(SQLModel, table=True):
    __tablename__ = "usuario"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True)
    nombre: str
    password_hash: str
    activo: bool = Field(default=True, sa_column_kwargs={"server_default": text("true")})
    debe_cambiar_password: bool = Field(
        default=False, sa_column_kwargs={"server_default": text("false")}
    )
    password_cambiada_en: datetime | None = None

    asignaciones: list["AsignacionRol"] = Relationship(
        back_populates="usuario",
        sa_relationship_kwargs={**LAZY_RAISE, "foreign_keys": "[AsignacionRol.usuario_id]"},
    )
    cliente: Optional["Cliente"] = Relationship(
        back_populates="usuario",
        sa_relationship_kwargs={**LAZY_RAISE, "uselist": False},
    )
    ordenes_asignadas: list["OrdenTrabajo"] = Relationship(
        back_populates="mecanico", sa_relationship_kwargs=dict(LAZY_RAISE)
    )


class AsignacionRol(SQLModel, table=True):
    __tablename__ = "asignacion_rol"
    __table_args__ = (
        CheckConstraint(f"rol IN ({_ROLES_SQL})", name="rol_valido"),
        # Unicidad sólo entre asignaciones abiertas (RN03): una revocada no impide reasignar.
        Index(
            "uq_asignacion_rol_usuario_id_rol",
            "usuario_id",
            "rol",
            unique=True,
            postgresql_where=text("revocada_en IS NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuario.id", index=True)
    rol: str
    desde: datetime = Field(
        default_factory=ahora_utc, sa_column_kwargs={"server_default": func.now()}
    )
    vence_en: datetime | None = None
    revocada_en: datetime | None = None
    # FK de auditoría: se lee como id, sin relación ORM (hay dos FK a `usuario` en esta tabla).
    otorgada_por: int | None = Field(default=None, foreign_key="usuario.id", index=True)

    usuario: "Usuario" = Relationship(
        back_populates="asignaciones",
        sa_relationship_kwargs={**LAZY_RAISE, "foreign_keys": "[AsignacionRol.usuario_id]"},
    )


class IntentoAcceso(SQLModel, table=True):
    __tablename__ = "intento_acceso"
    # Conteo de intentos recientes por correo e IP (RN08).
    __table_args__ = (Index("ix_intento_acceso_email_ip_cuando", "email", "ip", "cuando"),)

    id: int | None = Field(default=None, primary_key=True)
    cuando: datetime = Field(
        default_factory=ahora_utc, sa_column_kwargs={"server_default": func.now()}
    )
    email: str
    ip: str
    exito: bool


class EventoSeguridad(SQLModel, table=True):
    __tablename__ = "evento_seguridad"

    id: int | None = Field(default=None, primary_key=True)
    cuando: datetime = Field(
        default_factory=ahora_utc, sa_column_kwargs={"server_default": func.now()}
    )
    actor: str
    accion: str
