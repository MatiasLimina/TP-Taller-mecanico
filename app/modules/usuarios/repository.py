"""Repositorios del módulo usuarios (C-07). Reglas generales: ver `app/core/repository.py`.

Todo con parámetros ligados; las escrituras hacen `flush()` y nunca confirman la transacción.
Las consultas devuelven valores sueltos (una columna) o entidades sin relaciones: no hay carga
perezosa posible.
"""

from datetime import datetime

from sqlalchemy import func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.repository import BaseRepository
from app.modules.usuarios.models import AsignacionRol, IntentoAcceso, Usuario


class UsuarioRepository(BaseRepository[Usuario]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Usuario)

    async def get_by_email(self, email: str) -> Usuario | None:
        """Usuario por correo exacto; el llamador ya lo normalizó a minúsculas."""
        consulta = self._consulta_base().where(col(Usuario.email) == email)
        return (await self.session.exec(consulta)).first()


class AsignacionRolRepository(BaseRepository[AsignacionRol]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AsignacionRol)

    async def roles_vigentes(self, usuario_id: int, ahora: datetime) -> list[str]:
        """Roles abiertos (sin revocar) y sin vencer a `ahora`. Sólo la columna `rol`."""
        consulta = (
            select(col(AsignacionRol.rol))
            .where(
                col(AsignacionRol.usuario_id) == usuario_id,
                col(AsignacionRol.revocada_en).is_(None),
                or_(
                    col(AsignacionRol.vence_en).is_(None),
                    col(AsignacionRol.vence_en) > ahora,
                ),
            )
            .order_by(col(AsignacionRol.rol))
        )
        return list((await self.session.exec(consulta)).all())


class IntentoAccesoRepository(BaseRepository[IntentoAcceso]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IntentoAcceso)

    async def quinto_fallo_reciente(
        self, email: str, ip: str, desde: datetime, max_fallos: int
    ) -> datetime | None:
        """Fecha del fallo número `max_fallos` más reciente que cuenta para el límite, o None (RN08).

        El límite lo define el servicio (`MAX_FALLOS`); el repositorio no conoce la regla.

        Cuentan los fallos del par correo + IP posteriores a `desde` y al último éxito de ese
        par. UNA consulta (subconsulta escalar del último éxito); ambas partes usan el índice
        `(email, ip, cuando)`. Con la fecha devuelta el servicio decide el bloqueo y calcula
        `Retry-After` sin otra consulta.
        """
        ultimo_exito = (
            select(func.max(col(IntentoAcceso.cuando)))
            .where(
                col(IntentoAcceso.email) == email,
                col(IntentoAcceso.ip) == ip,
                col(IntentoAcceso.exito).is_(True),
            )
            .scalar_subquery()
        )
        consulta = (
            select(col(IntentoAcceso.cuando))
            .where(
                col(IntentoAcceso.email) == email,
                col(IntentoAcceso.ip) == ip,
                col(IntentoAcceso.exito).is_(False),
                col(IntentoAcceso.cuando) > desde,
                or_(ultimo_exito.is_(None), col(IntentoAcceso.cuando) > ultimo_exito),
            )
            .order_by(col(IntentoAcceso.cuando).desc())
            .offset(max_fallos - 1)
            .limit(1)
        )
        return (await self.session.exec(consulta)).first()
