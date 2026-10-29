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
from app.modules.usuarios.models import (
    AsignacionRol,
    EventoSeguridad,
    IntentoAcceso,
    Rol,
    Usuario,
)


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

    async def abierta_para_actualizar(self, usuario_id: int, rol: str) -> AsignacionRol | None:
        """Fila ABIERTA (`revocada_en IS NULL`) de ese rol, bloqueada con `FOR UPDATE` (C-09).

        Abierta no es vigente: puede estar vencida. El llamador decide con su definición de
        vigencia. El bloqueo hace que dos escrituras sobre la misma fila se serialicen; al
        seguir, PostgreSQL reevalúa el `WHERE` y no devuelve una fila que la otra ya cerró.
        `populate_existing` refresca una instancia que el identity map ya tuviera cargada.
        """
        consulta = (
            self._consulta_base()
            .where(
                col(AsignacionRol.usuario_id) == usuario_id,
                col(AsignacionRol.rol) == rol,
                col(AsignacionRol.revocada_en).is_(None),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.exec(consulta)).first()

    async def admins_sin_vencimiento_para_actualizar(self) -> list[AsignacionRol]:
        """Todas las asignaciones ADMIN vigentes SIN vencimiento de usuarios activos, bloqueadas.

        Son las que sostienen la regla RN05 (S-09): `revocada_en` y `vence_en` nulos, dueño con
        `activo`. Se devuelven en orden de id y se bloquean con `FOR UPDATE OF asignacion_rol`
        (la fila de `usuario` no se bloquea). Dos revocaciones de ADMIN que compitan toman
        siempre estas filas en el mismo orden, así que una espera a la otra sin interbloqueo; al
        seguir, PostgreSQL reevalúa el `WHERE` y descarta la fila que la primera ya revocó.
        `populate_existing` evita ver una versión vieja del identity map.
        """
        consulta = (
            self._consulta_base()
            .join(Usuario, col(Usuario.id) == col(AsignacionRol.usuario_id))
            .where(
                col(AsignacionRol.rol) == Rol.ADMIN.value,
                col(AsignacionRol.revocada_en).is_(None),
                col(AsignacionRol.vence_en).is_(None),
                col(Usuario.activo).is_(True),
            )
            .order_by(col(AsignacionRol.id))
            .with_for_update(of=AsignacionRol)
            .execution_options(populate_existing=True)
        )
        return list((await self.session.exec(consulta)).all())

    async def historial(self, usuario_id: int) -> list[AsignacionRol]:
        """Todas las filas del usuario (vigentes, vencidas y revocadas), de la más antigua."""
        consulta = (
            self._consulta_base()
            .where(col(AsignacionRol.usuario_id) == usuario_id)
            .order_by(col(AsignacionRol.desde), col(AsignacionRol.id))
        )
        return list((await self.session.exec(consulta)).all())


class EventoSeguridadRepository(BaseRepository[EventoSeguridad]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EventoSeguridad)

    async def listar_recientes(self, *, offset: int, limit: int) -> list[EventoSeguridad]:
        """Página del historial, del más reciente al más antiguo (id descendente). Sin filtros."""
        consulta = (
            self._consulta_base()
            .order_by(col(EventoSeguridad.id).desc())
            .offset(offset)
            .limit(limit)
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
