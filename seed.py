"""Recarga del estado inicial conocido para desarrollo y pruebas (C-06).

Este script **borra todos los datos del dominio** de la base configurada en `.env`
y carga el estado inicial reproducible que esperan los archivos `.http`.

Uso (después de aplicar `alembic upgrade head`):
    python seed.py

Notas de diseño:
- Las contraseñas definidas acá son ficticias, exclusivas de pruebas y nunca
  se leen del entorno ni se imprimen en la salida.
- El vaciado usa `TRUNCATE ... RESTART IDENTITY CASCADE` en lugar de borrar fila
  por fila, porque los disparadores de sólo agregado de C-04 son por fila y
  rechazan el borrado individual, mientras que permiten el vaciado completo.
- La carga inserta las filas directamente en una sola transacción del `UnitOfWork`:
  no escribe eventos individuales por cada usuario o rol sino un único evento
  con actor `SISTEMA`.
"""

import asyncio
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.modules.modelos  # noqa: F401 -- registra las 13 tablas en SQLModel.metadata
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.repository import BaseRepository
from app.core.security import hash_password
from app.core.unit_of_work import UnitOfWork
from app.modules.clientes.models import Cliente, Vehiculo
from app.modules.ordenes.models import (
    CodigoEstado,
    EstadoOrden,
    HistorialEstadoOrden,
    ItemOrden,
    OrdenTrabajo,
)
from app.modules.repuestos.models import (
    HistorialPrecioRepuesto,
    MovimientoStock,
    Repuesto,
)
from app.modules.usuarios.models import (
    AsignacionRol,
    EventoSeguridad,
    Rol,
    Usuario,
)
from app.modules.usuarios.schemas import CorreoNormalizado

CONTRASENA_PRUEBA = "ClaveSegura1"
CONTRASENA_PROVISORIA = "Provisoria1"
ACTOR_SISTEMA = "SISTEMA"
ACCION_CARGA = "Carga de los datos iniciales"
MOTIVO_STOCK_INICIAL = "Stock inicial"
CANTIDAD_TABLAS = 13


@dataclass(frozen=True, slots=True)
class UsuarioSeed:
    email: str
    nombre: str
    password: str
    rol: Rol
    debe_cambiar_password: bool = False


USUARIOS: tuple[UsuarioSeed, ...] = (
    UsuarioSeed("admin@example.com", "Adriana Admin", CONTRASENA_PRUEBA, Rol.ADMIN),
    UsuarioSeed("admin2@example.com", "Alberto Admin", CONTRASENA_PRUEBA, Rol.ADMIN),
    UsuarioSeed("recepcion@example.com", "Rita Recepción", CONTRASENA_PRUEBA, Rol.RECEPCION),
    UsuarioSeed("mecanico@example.com", "Mario Mecánico", CONTRASENA_PRUEBA, Rol.MECANICO),
    UsuarioSeed("mecanico2@example.com", "Marta Mecánica", CONTRASENA_PRUEBA, Rol.MECANICO),
    UsuarioSeed("cliente@example.com", "Laura Martínez", CONTRASENA_PRUEBA, Rol.CLIENTE),
    UsuarioSeed(
        "nuevo@example.com",
        "Nicolás Nuevo",
        CONTRASENA_PROVISORIA,
        Rol.MECANICO,
        debe_cambiar_password=True,
    ),
)

ESTADOS: dict[CodigoEstado, tuple[str, int, bool]] = {
    CodigoEstado.PENDIENTE: ("Orden registrada, a la espera de un mecánico", 1, False),
    CodigoEstado.EN_REPARACION: ("Un mecánico está trabajando en el vehículo", 2, False),
    CodigoEstado.TERMINADA: (
        "Reparación terminada; repuestos descontados del stock",
        3,
        True,
    ),
    CodigoEstado.CANCELADA: ("Orden cancelada sin reparación", 4, True),
}

_REPUESTOS_INICIALES: tuple[tuple[str, str, Decimal, int], ...] = (
    ("FIL-ACE-01", "Filtro de aceite", Decimal("8500.00"), 10),
    ("PAS-FRE-DEL", "Pastillas de freno delanteras", Decimal("32000.00"), 4),
    ("BUJ-01", "Bujía", Decimal("4500.00"), 2),
    ("ACE-5W30-1L", "Aceite 5W30 por litro", Decimal("12000.00"), 20),
)

_ADAPTADOR_CORREO = TypeAdapter(CorreoNormalizado)


def verificar_correos(correos: Iterable[str]) -> None:
    for correo in correos:
        try:
            normalizado = _ADAPTADOR_CORREO.validate_python(correo)
        except ValidationError:
            raise ValueError(f"Correo inválido en seed.py: {correo!r}") from None
        if normalizado != correo:
            raise ValueError(
                f"Correo no normalizado en seed.py: {correo!r} (se esperaba {normalizado!r})"
            )


async def calcular_hashes(usuarios: Sequence[UsuarioSeed]) -> list[str]:
    return list(await asyncio.gather(*(hash_password(u.password) for u in usuarios)))


async def vaciar_tablas(session: AsyncSession) -> None:
    tablas = [t.name for t in SQLModel.metadata.sorted_tables]
    assert len(tablas) == CANTIDAD_TABLAS
    # Nombres de la metadata del código (constantes), nunca datos externos.
    await session.exec(text(f"TRUNCATE TABLE {', '.join(tablas)} RESTART IDENTITY CASCADE"))  # type: ignore[call-overload]


async def _agregar[T: SQLModel](session: AsyncSession, entidad: T) -> T:
    return await BaseRepository(session, type(entidad)).add(entidad)


async def cargar_catalogo(session: AsyncSession) -> None:
    assert set(ESTADOS) == set(CodigoEstado)
    for codigo in sorted(CodigoEstado, key=lambda c: ESTADOS[c][1]):
        descripcion, posicion, es_final = ESTADOS[codigo]
        await _agregar(
            session,
            EstadoOrden(
                codigo=codigo.value,
                descripcion=descripcion,
                posicion=posicion,
                es_final=es_final,
            ),
        )


async def cargar_usuarios(session: AsyncSession, hashes: Sequence[str]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for u, h in zip(USUARIOS, hashes, strict=True):
        usuario = await _agregar(
            session,
            Usuario(
                email=u.email,
                nombre=u.nombre,
                password_hash=h,
                debe_cambiar_password=u.debe_cambiar_password,
            ),
        )
        assert usuario.id is not None
        await _agregar(session, AsignacionRol(usuario_id=usuario.id, rol=u.rol.value))
        ids[u.email] = usuario.id
    return ids


async def cargar_clientes(session: AsyncSession, ids: Mapping[str, int]) -> list[int]:
    laura = await _agregar(
        session,
        Cliente(
            usuario_id=ids["cliente@example.com"],
            nombre="Laura Martínez",
            documento="28111222",
            telefono="1144440001",
        ),
    )
    assert laura.id is not None
    v1 = await _agregar(
        session,
        Vehiculo(
            cliente_id=laura.id,
            patente="AB123CD",
            marca="Toyota",
            modelo="Corolla",
            anio=2019,
        ),
    )
    v2 = await _agregar(
        session,
        Vehiculo(
            cliente_id=laura.id,
            patente="AC456EF",
            marca="Volkswagen",
            modelo="Gol",
            anio=2015,
        ),
    )

    jorge = await _agregar(
        session,
        Cliente(
            usuario_id=None,
            nombre="Jorge Pérez",
            documento="25111333",
            telefono="1144440002",
        ),
    )
    assert jorge.id is not None
    v3 = await _agregar(
        session,
        Vehiculo(
            cliente_id=jorge.id,
            patente="AD789GH",
            marca="Ford",
            modelo="Fiesta",
            anio=2012,
        ),
    )
    assert v1.id is not None and v2.id is not None and v3.id is not None
    return [v1.id, v2.id, v3.id]


async def cargar_repuestos(
    session: AsyncSession, ids: Mapping[str, int]
) -> dict[str, Repuesto]:
    admin_id = ids["admin@example.com"]
    repuestos: dict[str, Repuesto] = {}
    for codigo, descripcion, precio, stock_inicial in _REPUESTOS_INICIALES:
        repuesto = await _agregar(
            session,
            Repuesto(
                codigo=codigo,
                descripcion=descripcion,
                precio=precio,
                stock=stock_inicial,
            ),
        )
        assert repuesto.id is not None
        await _agregar(
            session,
            MovimientoStock(
                repuesto_id=repuesto.id,
                usuario_id=admin_id,
                cantidad=stock_inicial,
                motivo=MOTIVO_STOCK_INICIAL,
            ),
        )
        repuestos[codigo] = repuesto

    filtro = repuestos["FIL-ACE-01"]
    assert filtro.id is not None
    await _agregar(
        session,
        HistorialPrecioRepuesto(
            repuesto_id=filtro.id,
            usuario_id=admin_id,
            precio_anterior=Decimal("8000.00"),
            precio_nuevo=filtro.precio,
        ),
    )
    return repuestos


async def cargar_ordenes(
    session: AsyncSession,
    ids: Mapping[str, int],
    vehiculos: Sequence[int],
    repuestos: Mapping[str, Repuesto],
) -> None:
    recepcion_id = ids["recepcion@example.com"]
    mecanico_id = ids["mecanico@example.com"]

    items_orden_1 = (
        (repuestos["FIL-ACE-01"], 1),
        (repuestos["ACE-5W30-1L"], 4),
    )
    total_orden_1 = sum(
        (cantidad * repuesto.precio for repuesto, cantidad in items_orden_1),
        Decimal("0.00"),
    )
    orden_1 = await _agregar(
        session,
        OrdenTrabajo(
            vehiculo_id=vehiculos[0],
            mecanico_id=None,
            estado=CodigoEstado.PENDIENTE.value,
            falla="Service de los 30.000 km: cambio de aceite y filtro",
            total=total_orden_1,
        ),
    )
    assert orden_1.id is not None
    for repuesto, cantidad in items_orden_1:
        assert repuesto.id is not None
        await _agregar(
            session,
            ItemOrden(
                orden_id=orden_1.id,
                repuesto_id=repuesto.id,
                cantidad=cantidad,
                precio_unitario=repuesto.precio,
            ),
        )

    items_orden_2 = ((repuestos["BUJ-01"], 4),)
    total_orden_2 = sum(
        (cantidad * repuesto.precio for repuesto, cantidad in items_orden_2),
        Decimal("0.00"),
    )
    orden_2 = await _agregar(
        session,
        OrdenTrabajo(
            vehiculo_id=vehiculos[2],
            mecanico_id=mecanico_id,
            estado=CodigoEstado.EN_REPARACION.value,
            falla="El motor falla en frío y tironea al acelerar",
            total=total_orden_2,
        ),
    )
    assert orden_2.id is not None
    for repuesto, cantidad in items_orden_2:
        assert repuesto.id is not None
        await _agregar(
            session,
            ItemOrden(
                orden_id=orden_2.id,
                repuesto_id=repuesto.id,
                cantidad=cantidad,
                precio_unitario=repuesto.precio,
            ),
        )

    await _agregar(
        session,
        HistorialEstadoOrden(
            orden_id=orden_1.id,
            desde_estado=None,
            hasta_estado=CodigoEstado.PENDIENTE.value,
            usuario_id=recepcion_id,
        ),
    )
    await _agregar(
        session,
        HistorialEstadoOrden(
            orden_id=orden_2.id,
            desde_estado=None,
            hasta_estado=CodigoEstado.PENDIENTE.value,
            usuario_id=recepcion_id,
        ),
    )
    await _agregar(
        session,
        HistorialEstadoOrden(
            orden_id=orden_2.id,
            desde_estado=CodigoEstado.PENDIENTE.value,
            hasta_estado=CodigoEstado.EN_REPARACION.value,
            usuario_id=mecanico_id,
        ),
    )


async def cargar_evento_sistema(session: AsyncSession) -> None:
    await _agregar(
        session,
        EventoSeguridad(actor=ACTOR_SISTEMA, accion=ACCION_CARGA),
    )


async def contar_filas(session: AsyncSession) -> dict[str, int]:
    conteo: dict[str, int] = {}
    for tabla in SQLModel.metadata.sorted_tables:
        consulta = select(func.count()).select_from(tabla)
        conteo[tabla.name] = (await session.exec(consulta)).one()
    return conteo


async def sembrar(
    session_factory: async_sessionmaker[AsyncSession],
    hashes: Sequence[str],
) -> dict[str, int]:
    async with session_factory() as session, UnitOfWork(session):
        await vaciar_tablas(session)
        await cargar_catalogo(session)
        ids = await cargar_usuarios(session, hashes)
        vehiculos = await cargar_clientes(session, ids)
        repuestos = await cargar_repuestos(session, ids)
        await cargar_ordenes(session, ids, vehiculos, repuestos)
        await cargar_evento_sistema(session)
        conteo = await contar_filas(session)
    return conteo


async def main() -> int:
    try:
        verificar_correos(u.email for u in USUARIOS)
        settings = get_settings()
    except (ValueError, ValidationError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    hashes = await calcular_hashes(USUARIOS)
    # `sql_echo=False` evita que SQLAlchemy imprima `password_hash` en stdout
    # cuando `.env` tiene `SQL_ECHO=true` (regla dura: la salida nunca expone hashes).
    engine = create_engine(settings.model_copy(update={"sql_echo": False}))
    try:
        session_factory = create_session_factory(engine)
        conteo = await sembrar(session_factory, hashes)
    finally:
        await engine.dispose()

    resumen = " ".join(f"{tabla}={cantidad}" for tabla, cantidad in conteo.items())
    print("Se reemplazaron todos los datos del dominio de la base configurada.")
    print(f"Seed cargado: {resumen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
