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
    NoEncontrado,
    SinPermiso,
    restriccion_violada,
)
from app.core.paginacion import Pagina, Paginacion, armar_pagina, verificar_pagina
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
    AsignacionRolEntrada,
    AsignacionSalida,
    CambioPasswordEntrada,
    ClienteRegistradoSalida,
    EventoSalida,
    LoginEntrada,
    LoginSalida,
    PerfilSalida,
    PersonalAltaEntrada,
    PersonalSalida,
    RegistroEntrada,
    RegistroSalida,
    RolesUsuarioSalida,
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

ACCION_ALTA_PERSONAL = "Alta de personal: {email}"

MENSAJE_USUARIO_INEXISTENTE = "El usuario no existe"
MENSAJE_ROL_YA_VIGENTE = "El usuario ya tiene el rol {rol} vigente"
MENSAJE_ROL_NO_VIGENTE = "El usuario no tiene el rol {rol} vigente"
MENSAJE_AUTOREVOCACION = "Un administrador no puede revocarse su propio rol ADMIN"
MENSAJE_SIN_ADMINISTRADORES = (
    "No se puede revocar: el sistema quedaría sin administradores vigentes sin vencimiento"
)
ACCION_ASIGNACION = "Asignación del rol {rol} a {email}"
ACCION_REVOCACION = "Revocación del rol {rol} a {email}"
SUFIJO_VENCE = " hasta {vence}"
SUFIJO_REEMPLAZA = " (reemplaza una asignación vencida)"


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


async def listar_eventos(uow: UsuariosUoW, pag: Paginacion) -> Pagina[EventoSalida]:
    """Historial de seguridad paginado, del más reciente al más antiguo (C-09)."""
    async with uow:
        total = await uow.eventos.count()
        verificar_pagina(pag, total)
        eventos = await uow.eventos.listar_recientes(offset=pag.offset, limit=pag.size)
        items = [EventoSalida.model_validate(evento) for evento in eventos]
    return armar_pagina(items, total, pag)


async def alta_personal(
    uow: UsuariosUoW, actual: UsuarioActual, datos: PersonalAltaEntrada
) -> PersonalSalida:
    """Alta de una cuenta de personal por un ADMIN: usuario + evento, todo o nada (C-09, D3).

    La cuenta nace activa, con la contraseña provisoria y `debe_cambiar_password` verdadero, sin
    roles ni ficha de cliente (se asignan con `POST /usuarios/{id}/roles`). La unicidad del
    correo la decide `uq_usuario_email` (sin consulta previa; también con altas simultáneas) y
    se traduce fuera del bloque. bcrypt corre ANTES de abrir la transacción (DD-06).
    """
    password_hash = await hash_password(datos.password_provisoria)
    try:
        async with uow:
            usuario = await uow.usuarios.add(
                Usuario(
                    email=datos.email,
                    nombre=datos.nombre,
                    password_hash=password_hash,
                    debe_cambiar_password=True,
                )
            )
            await uow.eventos.add(
                EventoSeguridad(
                    actor=actual.email, accion=ACCION_ALTA_PERSONAL.format(email=usuario.email)
                )
            )
            # Se arma adentro, con valores ya cargados: afuera podría haber un rollback.
            salida = PersonalSalida.model_validate(usuario)
    except IntegrityError as exc:
        if restriccion_violada(exc) == "uq_usuario_email":
            raise Conflicto(MENSAJE_CORREO_REPETIDO) from None
        raise
    return salida


def _vigente(asignacion: AsignacionRol, ahora: datetime) -> bool:
    """Única definición de "vigente" para las salidas: no revocada y sin vencer a `ahora`.

    Es la misma regla que `AsignacionRolRepository.roles_vigentes` (que la aplica en SQL).
    """
    return asignacion.revocada_en is None and (
        asignacion.vence_en is None or asignacion.vence_en > ahora
    )


def _salida_asignacion(asignacion: AsignacionRol, ahora: datetime) -> AsignacionSalida:
    # Valores ya cargados (se llama dentro del bloque); `id` nunca es None tras el flush.
    assert asignacion.id is not None
    return AsignacionSalida(
        id=asignacion.id,
        usuario_id=asignacion.usuario_id,
        rol=asignacion.rol,
        desde=asignacion.desde,
        vence_en=asignacion.vence_en,
        revocada_en=asignacion.revocada_en,
        otorgada_por=asignacion.otorgada_por,
        vigente=_vigente(asignacion, ahora),
    )


def _fecha_evento(instante: datetime) -> str:
    return instante.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def asignar_rol(
    uow: UsuariosUoW, actual: UsuarioActual, usuario_id: int, datos: AsignacionRolEntrada
) -> AsignacionSalida:
    """Abre una asignación de rol vigente: una sola abierta por rol y usuario (RN03, C-09 D4).

    La fila abierta del rol se lee con `FOR UPDATE`. Si está vigente -> 409. Si está abierta
    pero vencida, se cierra (`revocada_en = ahora`) y se abre otra en la MISMA transacción: el
    índice parcial `uq_asignacion_rol_usuario_id_rol` trata como abierta a una fila vencida, así
    que el cierre va antes del INSERT (el repositorio hace `flush` en cada escritura). Ninguna
    fila se borra. Con asignaciones simultáneas decide el índice: la perdedora recibe el mismo
    409, traducido fuera del bloque.
    """
    rol = datos.rol.value
    ahora = datetime.now(UTC)
    try:
        async with uow:
            usuario = await uow.usuarios.get_by_id(usuario_id)
            if usuario is None:
                raise NoEncontrado(MENSAJE_USUARIO_INEXISTENTE)
            abierta = await uow.asignaciones.abierta_para_actualizar(usuario_id, rol)
            if abierta is not None and _vigente(abierta, ahora):
                raise Conflicto(MENSAJE_ROL_YA_VIGENTE.format(rol=rol))
            if abierta is not None:  # abierta pero vencida: se cierra antes de abrir la nueva
                await uow.asignaciones.update(abierta, {"revocada_en": ahora})
            nueva = await uow.asignaciones.add(
                AsignacionRol(
                    usuario_id=usuario_id,
                    rol=rol,
                    desde=ahora,
                    vence_en=datos.vence_en,
                    otorgada_por=actual.id,
                )
            )
            accion = ACCION_ASIGNACION.format(rol=rol, email=usuario.email)
            if nueva.vence_en is not None:
                accion += SUFIJO_VENCE.format(vence=_fecha_evento(nueva.vence_en))
            if abierta is not None:
                accion += SUFIJO_REEMPLAZA
            await uow.eventos.add(EventoSeguridad(actor=actual.email, accion=accion))
            salida = _salida_asignacion(nueva, ahora)
    except IntegrityError as exc:
        # Fuera del bloque: el rollback ya ocurrió. El mensaje usa `rol` del contrato.
        if restriccion_violada(exc) == "uq_asignacion_rol_usuario_id_rol":
            raise Conflicto(MENSAJE_ROL_YA_VIGENTE.format(rol=rol)) from None
        raise
    return salida


async def roles_de_usuario(uow: UsuariosUoW, usuario_id: int) -> RolesUsuarioSalida:
    """Historial completo de asignaciones del usuario y sus roles vigentes a este instante."""
    ahora = datetime.now(UTC)
    async with uow:
        usuario = await uow.usuarios.get_by_id(usuario_id)
        if usuario is None:
            raise NoEncontrado(MENSAJE_USUARIO_INEXISTENTE)
        filas = await uow.asignaciones.historial(usuario_id)
        asignaciones = [_salida_asignacion(fila, ahora) for fila in filas]
        salida = RolesUsuarioSalida(
            usuario_id=usuario_id,
            email=usuario.email,
            nombre=usuario.nombre,
            roles_vigentes=sorted({a.rol for a in asignaciones if a.vigente}),
            asignaciones=asignaciones,
        )
    return salida


async def revocar_rol(
    uow: UsuariosUoW, actual: UsuarioActual, usuario_id: int, rol: Rol
) -> AsignacionSalida:
    """Revoca (escribe `revocada_en`, no borra) el rol vigente de un usuario (RN03/RN05, C-09 D5).

    Orden de los rechazos: 404 usuario -> 409 autoprotección -> 404 rol no vigente -> 409 sin
    administradores. Revocar un rol no vigente (nunca lo tuvo, ya revocado o vencido) es 404.

    RN05 (S-09): siempre debe quedar al menos una asignación ADMIN VIGENTE SIN VENCIMIENTO de un
    usuario activo. Las ADMIN con `vence_en` no cuentan: el paso del tiempo las apagaría sin
    pasar por acá. Un ADMIN nunca se revoca su propio ADMIN.

    Por qué se bloquea: dos ADMIN sin vencimiento que se revocan entre sí a la vez verían cada
    uno al otro en el conjunto y confirmarían los dos, dejando cero. Con `FOR UPDATE` sobre
    TODO el conjunto, la segunda transacción espera; al seguir, PostgreSQL reevalúa el filtro y
    descarta la fila que la primera revocó, así que el conjunto queda en su propia fila (que es
    el objetivo) y responde 409.

    Por qué el conjunto se bloquea ANTES que el objetivo, y en orden de id: si cada transacción
    tomara primero su objetivo, dos revocaciones cruzadas se esperarían mutuamente (`40P01`,
    un 500). Así todas toman las mismas filas en el mismo orden y sólo se hace cola.
    """
    ahora = datetime.now(UTC)
    async with uow:
        usuario = await uow.usuarios.get_by_id(usuario_id)
        if usuario is None:
            raise NoEncontrado(MENSAJE_USUARIO_INEXISTENTE)
        if rol is Rol.ADMIN and usuario_id == actual.id:
            raise Conflicto(MENSAJE_AUTOREVOCACION)
        permanentes: list[AsignacionRol] = []
        if rol is Rol.ADMIN:
            permanentes = await uow.asignaciones.admins_sin_vencimiento_para_actualizar()
        objetivo = await uow.asignaciones.abierta_para_actualizar(usuario_id, rol.value)
        if objetivo is None or not _vigente(objetivo, ahora):
            raise NoEncontrado(MENSAJE_ROL_NO_VIGENTE.format(rol=rol.value))
        if rol is Rol.ADMIN and not any(fila.id != objetivo.id for fila in permanentes):
            raise Conflicto(MENSAJE_SIN_ADMINISTRADORES)
        await uow.asignaciones.update(objetivo, {"revocada_en": ahora})
        await uow.eventos.add(
            EventoSeguridad(
                actor=actual.email,
                accion=ACCION_REVOCACION.format(rol=rol.value, email=usuario.email),
            )
        )
        salida = _salida_asignacion(objetivo, ahora)
    return salida
