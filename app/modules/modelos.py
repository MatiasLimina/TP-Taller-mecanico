"""Registro único de modelos de tabla.

Importar este módulo carga los `models.py` de todos los módulos, de modo que `SQLModel.metadata`
tiene las 13 tablas y SQLAlchemy resuelve las relaciones declaradas por nombre de clase entre
módulos (`"Cliente"`, `"OrdenTrabajo"`). Lo importan `main.py`, `migrations/env.py` y cualquier
script que use los modelos (p. ej. el seed): una lista única que no se desincroniza al agregar un
módulo. Un módulo nuevo con tablas se agrega acá.
"""

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
    IntentoAcceso,
    Rol,
    Usuario,
)

__all__ = [
    "AsignacionRol",
    "Cliente",
    "CodigoEstado",
    "EstadoOrden",
    "EventoSeguridad",
    "HistorialEstadoOrden",
    "HistorialPrecioRepuesto",
    "IntentoAcceso",
    "ItemOrden",
    "MovimientoStock",
    "OrdenTrabajo",
    "Repuesto",
    "Rol",
    "Usuario",
    "Vehiculo",
]
