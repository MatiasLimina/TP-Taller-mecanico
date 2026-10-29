"""Servicio de autenticación: registro, login (C-07), sesión, roles y cambio de contraseña (C-08).

Los servicios no conocen HTTP: lanzan errores de aplicación (`app/core/errores.py`). El router
construye el Unit of Work y el servicio lo abre con `async with`.

Registro (RN01, RN02): la unicidad la decide la base, sin consulta previa; el hash de la
contraseña se calcula ANTES de abrir la transacción para no retener la conexión durante bcrypt.

Login (RN08, RN09): los tres caminos de falla (correo inexistente, contraseña incorrecta,
usuario inactivo) hacen el mismo trabajo: 2 consultas, 1 verificación bcrypt y 1 anotación de
intento. La conexión se libera antes de bcrypt. Un 429 no se anota (si se anotara, cada
reintento bloqueado renovaría la ventana y el bloqueo no terminaría nunca).

Sesión (C-08): `autenticar` valida el token de la cookie y lo contrasta con la base en cada
petición (usuario existente y activo, token no anterior al último cambio de contraseña, RN07);
`exigir_roles` consulta los roles vigentes en la base y nunca mira los del token (RN04). Los dos
lanzan 401/403 como errores de aplicación; no conocen `Request` ni `Response`.

Cambio de contraseña (RN07): las dos operaciones bcrypt van FUERA de toda transacción; el
`password_cambiada_en` guardado y el `iat` del token nuevo salen del MISMO instante, y la
comparación del RN07 es entre dos `datetime` con zona, sin truncar al segundo.
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
    SinPermiso,
    restriccion_violada,
)
from app.core.security import (
    PasswordInvalidaError,
    TokenInvalidoError,
    crear_token_acceso,
    decodificar_token_acceso,
    hash_password,
    verify_password,
)
from app.modules.clientes.models import Cliente
from app.modules.usuarios.models import AsignacionRol, EventoSeguridad, Rol, Usuario
from app.modules.usuarios.schemas import (
    CambioPasswordEntrada,
    ClienteRegistradoSalida,
    LoginEntrada,
    LoginSalida,
    PerfilSalida,
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

MENSAJE_SIN_SESION = "Se requiere iniciar sesión"
MENSAJE_SESION_INVALIDA = "La sesión no es válida o venció"
MENSAJE_CAMBIO_PENDIENTE = "Debe cambiar la contraseña antes de continuar"
MENSAJE_SIN_PERMISO = "No tiene permiso para realizar esta operación"
MENSAJE_PASSWORD_ACTUAL_INCORRECTA = "La contraseña actual es incorrecta"
MENSAJE_PASSWORD_ACTUALIZADA = "Contraseña actualizada"
ACCION_CAMBIO_PASSWORD = "Cambio de contraseña"


@dataclass(frozen=True, slots=True)
class SesionIniciada:
    """Resultado del login: el servicio no conoce `Response`; el router pone la cookie."""

    token: str
    salida: LoginSalida


@dataclass(frozen=True, slots=True)
class UsuarioActual:
    """Quién hace la petición: valores, nunca la entidad (sin `password_hash`, sin relaciones)."""

    id: int
    email: str
    nombre: str
    debe_cambiar_password: bool
    roles_token: tuple[str, ...]  # informativos: los permisos se deciden con la base (RN04)


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


async def autenticar(uow: UsuariosUoW, token: str | None) -> UsuarioActual:
    """Resuelve el token de la cookie en el usuario de la petición, o lanza 401 (RN07).

    Falta o cookie vacía -> `MENSAJE_SIN_SESION`. Todo lo demás (token roto, vencido, de otra
    clave; cuenta inexistente o inactiva; sesión anterior al último cambio de contraseña) ->
    el mismo `MENSAJE_SESION_INVALIDA`, para no revelar el estado de la cuenta.
    """
    if not token:
        raise NoAutenticado(MENSAJE_SIN_SESION)
    try:
        datos = decodificar_token_acceso(token)
    except TokenInvalidoError:
        raise NoAutenticado(MENSAJE_SESION_INVALIDA) from None
    async with uow:
        usuario = await uow.usuarios.get_by_id(datos.usuario_id)
        if usuario is None or not usuario.activo:
            raise NoAutenticado(MENSAJE_SESION_INVALIDA)
        # RN07: un token emitido antes del último cambio de contraseña ya no vale. Las dos
        # fechas se comparan tal cual (microsegundos, con zona): truncar dejaría vivas las
        # sesiones anteriores emitidas dentro del mismo segundo del cambio.
        if usuario.password_cambiada_en is not None and datos.iat < usuario.password_cambiada_en:
            raise NoAutenticado(MENSAJE_SESION_INVALIDA)
        # Se arma adentro, con valores ya cargados.
        assert usuario.id is not None
        actual = UsuarioActual(
            id=usuario.id,
            email=usuario.email,
            nombre=usuario.nombre,
            debe_cambiar_password=usuario.debe_cambiar_password,
            roles_token=datos.roles,
        )
    return actual


async def perfil(uow: UsuariosUoW, actual: UsuarioActual) -> PerfilSalida:
    async with uow:
        vigentes = await uow.asignaciones.roles_vigentes(actual.id, datetime.now(UTC))
    return PerfilSalida(
        id=actual.id,
        email=actual.email,
        nombre=actual.nombre,
        debe_cambiar_password=actual.debe_cambiar_password,
        roles_vigentes=vigentes,
        roles_token=list(actual.roles_token),
    )


async def exigir_roles(uow: UsuariosUoW, usuario_id: int, permitidos: frozenset[str]) -> None:
    """403 si el usuario no tiene ninguno de los roles `permitidos` vigentes en la base (RN04).

    Consulta en cada petición; los roles del token nunca participan. Sin comodín de ADMIN.
    """
    async with uow:
        vigentes = await uow.asignaciones.roles_vigentes(usuario_id, datetime.now(UTC))
    if permitidos.isdisjoint(vigentes):
        raise SinPermiso(MENSAJE_SIN_PERMISO)


async def cambiar_password(
    uow: UsuariosUoW, actual: UsuarioActual, datos: CambioPasswordEntrada
) -> SesionIniciada:
    """Cambia la contraseña y devuelve una sesión nueva; invalida toda sesión anterior (RN07).

    bcrypt (verificar la actual, hashear la nueva) corre FUERA de las dos transacciones cortas:
    ninguna conexión queda tomada durante ~300 ms de bcrypt (DD-06).
    """
    # Bloque 1: sólo leer el hash guardado.
    async with uow:
        usuario = await uow.usuarios.get_by_id(actual.id)
        hash_guardado = usuario.password_hash if usuario is not None else None
    if hash_guardado is None:
        raise NoAutenticado(MENSAJE_SESION_INVALIDA)
    try:
        coincide = await verify_password(datos.password_actual, hash_guardado)
    except PasswordInvalidaError:
        # Respaldo: el DTO ya responde 422 por más de 72 bytes; nunca un 500.
        coincide = False
    if not coincide:
        raise NoAutenticado(MENSAJE_PASSWORD_ACTUAL_INCORRECTA)
    nuevo_hash = await hash_password(datos.password_nueva)

    # Bloque 2: todo o nada (hash, marca de cambio, bandera, evento de seguridad).
    async with uow:
        usuario = await uow.usuarios.get_by_id(actual.id)
        if usuario is None:
            raise NoAutenticado(MENSAJE_SESION_INVALIDA)
        # Un solo instante: es el `password_cambiada_en` guardado y el `iat` del token nuevo,
        # así el token nuevo vale y toda sesión emitida antes (aunque sea del mismo segundo) no.
        ahora = datetime.now(UTC)
        await uow.usuarios.update(
            usuario,
            {
                "password_hash": nuevo_hash,
                "password_cambiada_en": ahora,
                "debe_cambiar_password": False,
            },
        )
        await uow.eventos.add(EventoSeguridad(actor=usuario.email, accion=ACCION_CAMBIO_PASSWORD))
        roles = await uow.asignaciones.roles_vigentes(actual.id, ahora)
    token = crear_token_acceso(actual.id, roles, ahora=ahora)
    return SesionIniciada(
        token=token,
        salida=LoginSalida(
            mensaje=MENSAJE_PASSWORD_ACTUALIZADA,
            debe_cambiar_password=False,
            expira_en_segundos=get_settings().access_token_expire_seconds,
        ),
    )
