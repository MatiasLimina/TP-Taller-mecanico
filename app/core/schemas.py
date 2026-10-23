"""Contratos base de la API: entradas estrictas, salidas separadas de las tablas, ids de ruta.

- Todo cuerpo de entrada (PATCH incluidos) hereda de `EntradaBase`: un campo no declarado
  da 422 y nadie puede fijar campos reservados (rol, stock, precio, estado, fechas).
- Toda respuesta se declara con un contrato `*Salida` que hereda de `SalidaBase` y enumera
  sus campos; un modelo de tabla nunca se devuelve directamente.
- Un contrato de salida que exponga `password_hash` en CUALQUIER profundidad (campo propio,
  modelo anidado, `Optional`/`list`/`dict`/`tuple`/unión/`Annotated`) o un modelo de tabla
  (`table=True`) falla al definirse, antes de atender peticiones. La misma revisión protege
  a `Pagina[X]` (`app/core/paginacion.py`). Límite: lo declarado como `Any`/`object` no se
  puede revisar.
"""

import dataclasses
from typing import (
    Annotated,
    ForwardRef,
    Literal,
    TypeAliasType,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from fastapi import Path
from pydantic import BaseModel, ConfigDict
from sqlmodel import SQLModel

INT4_MAX = 2_147_483_647  # tope de INTEGER de PostgreSQL (los `id: int` de SQLModel)

CAMPO_PROHIBIDO_EN_SALIDA = "password_hash"


class EntradaBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _tipos_de(anotacion):
    """Clases alcanzables desde una anotación, atravesando contenedores y uniones."""
    if isinstance(anotacion, (str, ForwardRef)):
        raise TypeError(
            f"No se puede resolver la referencia {anotacion!r} para revisar el contrato de "
            "salida: defina antes el modelo al que apunta"
        )
    origen = get_origin(anotacion)
    if origen is Literal:
        return
    if origen is Annotated:
        yield from _tipos_de(get_args(anotacion)[0])
        return
    if isinstance(anotacion, TypeAliasType):
        yield from _tipos_de(anotacion.__value__)
        return
    if origen is not None:
        if isinstance(origen, type):
            yield origen
        for arg in get_args(anotacion):
            for sub in arg if isinstance(arg, list | tuple) else (arg,):
                yield from _tipos_de(sub)
        return
    if isinstance(anotacion, type):
        yield anotacion


def _revisar_tipo(tipo: type, ruta: str, vistos: set[type]) -> None:
    if tipo in vistos:
        return
    vistos.add(tipo)
    campos: dict[str, list] = {}  # nombre expuesto -> [anotación, ...]
    if issubclass(tipo, BaseModel):
        if issubclass(tipo, SQLModel) and tipo.model_config.get("table"):
            raise TypeError(
                f"{ruta}: {tipo.__name__} es un modelo de tabla (table=True) y no puede "
                "formar parte de un contrato de salida"
            )
        for nombre, campo in tipo.model_fields.items():
            alias = {nombre, campo.alias, campo.serialization_alias}
            campos[nombre] = [campo.annotation, alias]
        for nombre, calculado in tipo.model_computed_fields.items():
            campos[nombre] = [calculado.return_type, {nombre, calculado.alias}]
    elif dataclasses.is_dataclass(tipo) or is_typeddict(tipo):
        for nombre, anotacion in get_type_hints(tipo).items():
            campos[nombre] = [anotacion, {nombre}]
    for nombre, (anotacion, nombres) in campos.items():
        if CAMPO_PROHIBIDO_EN_SALIDA in nombres:
            raise TypeError(
                f"{CAMPO_PROHIBIDO_EN_SALIDA} no puede estar en un contrato de salida "
                f"({ruta}.{nombre})"
            )
        for interno in _tipos_de(anotacion):
            _revisar_tipo(interno, f"{ruta}.{nombre}", vistos)


def rechazar_salida_insegura(contrato: type[BaseModel]) -> None:
    """`TypeError` si el contrato expone `password_hash` o un modelo de tabla, a cualquier profundidad."""
    _revisar_tipo(contrato, contrato.__name__, set())


class SalidaBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        rechazar_salida_insegura(cls)


IdRuta = Annotated[int, Path(ge=1, le=INT4_MAX)]
