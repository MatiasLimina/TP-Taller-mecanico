"""Servicio de autenticación: registro de clientes e inicio de sesión (C-07).

Los servicios no conocen HTTP: lanzan errores de aplicación (`app/core/errores.py`). El router
construye el Unit of Work y el servicio lo abre con `async with`.

Registro (RN01, RN02): la unicidad la decide la base, sin consulta previa; el hash de la
contraseña se calcula ANTES de abrir la transacción para no retener la conexión durante bcrypt.

Login (RN08, RN09): los tres caminos de falla (correo inexistente, contraseña incorrecta,
usuario inactivo) hacen el mismo trabajo: 2 consultas, 1 verificación bcrypt y 1 anotación de
intento. La conexión se libera antes de bcrypt. Un 429 no se anota (si se anotara, cada
reintento bloqueado renovaría la ventana y el bloqueo no terminaría nunca).
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.errores import (
    Conflicto,
    DemasiadosIntentos,
    NoAutenticado,
    restriccion_violada,
)
from app.core.security import (
    PasswordInvalidaError,
    crear_token_acceso,
    hash_password,
    verify_password,
)
from app.modules.clientes.models import Cliente
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Rol, Usuario
from app.modules.usuarios.schemas import (
    ClienteRegistradoSalida,
    LoginEntrada,
    LoginSalida,
    RegistroEntrada,
    RegistroSalida,
)
from app.modules.usuarios.unit_of_work import AnotadorIntentos, UsuariosUoW

# Valores de la consigna (RN08), no configuración de entorno.
MAX_FALLOS = 5
VENTANA = timedelta(seconds=60)

MENSAJE_CORREO_REPETIDO = "El correo ya está registrado"
MENSAJE_DOCUMENTO_REPETIDO = "El documento ya pertenece a un cliente del taller"
MENSAJE_CREDENCIALES = "Correo o contraseña incorrectos"
MENSAJE_DEMASIADOS_INTENTOS = "Demasiados intentos fallidos. Espere antes de volver a intentar"
MENSAJE_SESION_INICIADA = "Sesión iniciada"
ACCION_REGISTRO = "Auto-registro de cliente"


@dataclass(frozen=True, slots=True)
class SesionIniciada:
    """Resultado del login: el servicio no conoce `Response`; el router pone la cookie."""

    token: str
    salida: LoginSalida


async def registrar(uow: UsuariosUoW, datos: RegistroEntrada) -> RegistroSalida:
    # Antes de abrir el bloque: bcrypt no debe tener una conexión tomada (DD-06).
    password_hash = await hash_password(datos.password)
    try:
        async with uow:
            usuario = await uow.usuarios.add(
                Usuario(email=datos.email, nombre=datos.nombre, password_hash=password_hash)
            )
            assert usuario.id is not None
            await uow.asignaciones.add(AsignacionRol(usuario_id=usuario.id, rol=Rol.CLIENTE.value))
            cliente = await uow.clientes.add(
                Cliente(
                    usuario_id=usuario.id,
                    nombre=datos.nombre,
                    documento=datos.documento,
                    telefono=datos.telefono,
                )
            )
            await uow.eventos.add(EventoSeguridad(actor=datos.email, accion=ACCION_REGISTRO))
            # Se arma adentro, con valores ya cargados: afuera podría haber un rollback.
            assert cliente.id is not None
            salida = RegistroSalida(
                id=usuario.id,
                email=usuario.email,
                nombre=usuario.nombre,
                cliente=ClienteRegistradoSalida(
                    id=cliente.id,
                    nombre=cliente.nombre,
                    documento=cliente.documento,
                    telefono=cliente.telefono,
                ),
            )
    except IntegrityError as exc:
        # Fuera del bloque: el rollback del UoW ya deshizo las cuatro filas.
        restriccion = restriccion_violada(exc)
        if restriccion == "uq_usuario_email":
            raise Conflicto(MENSAJE_CORREO_REPETIDO) from None
        if restriccion == "uq_cliente_documento":
            raise Conflicto(MENSAJE_DOCUMENTO_REPETIDO) from None
        raise
    return salida


async def iniciar_sesion(
    uow: UsuariosUoW,
    anotador: AnotadorIntentos,
    datos: LoginEntrada,
    ip: str,
    hash_ficticio: str,
) -> SesionIniciada:
    ahora = datetime.now(UTC)
    # Bloque 1: dos consultas y la conexión vuelve al pool antes de bcrypt.
    async with uow:
        quinto_fallo = await uow.intentos.quinto_fallo_reciente(
            datos.email, ip, ahora - VENTANA, MAX_FALLOS
        )
        if quinto_fallo is not None:
            espera = math.ceil((quinto_fallo + VENTANA - ahora).total_seconds())
            raise DemasiadosIntentos(MENSAJE_DEMASIADOS_INTENTOS, retry_after=max(1, espera))
        usuario = await uow.usuarios.get_by_email(datos.email)
        # Valores locales: la entidad no se toca fuera del bloque.
        usuario_id = usuario.id if usuario is not None else None
        password_hash = usuario.password_hash if usuario is not None else None
        activo = usuario.activo if usuario is not None else False
        debe_cambiar_password = usuario.debe_cambiar_password if usuario is not None else False

    try:
        coincide = await verify_password(datos.password, password_hash or hash_ficticio)
    except PasswordInvalidaError:
        # Respaldo: el DTO ya responde 422 por más de 72 bytes (S-07); nunca un 500.
        coincide = False
    exito = coincide and usuario_id is not None and activo

    # Antes del 401: el fallo queda guardado aunque la petición termine en error.
    await anotador.anotar(datos.email, ip, exito)
    if not exito or usuario_id is None:
        raise NoAutenticado(MENSAJE_CREDENCIALES)

    # Bloque 2: sólo en el éxito, para que no agregue diferencia de tiempo a los fallos.
    async with uow:
        roles = await uow.asignaciones.roles_vigentes(usuario_id, datetime.now(UTC))
    token = crear_token_acceso(usuario_id, roles)
    return SesionIniciada(
        token=token,
        salida=LoginSalida(
            mensaje=MENSAJE_SESION_INICIADA,
            debe_cambiar_password=debe_cambiar_password,
            expira_en_segundos=get_settings().access_token_expire_seconds,
        ),
    )
