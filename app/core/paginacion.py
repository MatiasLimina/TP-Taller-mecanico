"""Paginación común de los listados: parámetros, envoltorio y regla de página inexistente.

Flujo en el servicio (contar primero evita traer filas de una página que da 422)::

    total = await repo.contar_x(filtros)          # mismos filtros que la página
    verificar_pagina(pag, total)                  # EntradaInvalida si la página no existe
    items = await repo.listar_x(filtros, offset=pag.offset, limit=pag.size)
    return armar_pagina([XSalida.model_validate(i) for i in items], total, pag)

En el router: `pag: PaginacionDep`.
"""

from dataclasses import dataclass
from math import ceil
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict

from app.core.errores import EntradaInvalida
from app.core.schemas import rechazar_salida_insegura

SIZE_POR_DEFECTO = 20
SIZE_MAXIMO = 100


@dataclass(frozen=True)
class Paginacion:
    page: int
    size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def parametros_paginacion(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=SIZE_MAXIMO)] = SIZE_POR_DEFECTO,
) -> Paginacion:
    return Paginacion(page=page, size=size)


PaginacionDep = Annotated[Paginacion, Depends(parametros_paginacion)]


class Pagina[T](BaseModel):
    """Envoltorio de listados. `Pagina[X]` aplica la misma revisión que `SalidaBase`: se
    rechaza al parametrizarla si `X` es un modelo de tabla o expone `password_hash`."""

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        rechazar_salida_insegura(cls)

    items: list[T]
    total: int
    page: int
    size: int
    pages: int


def calcular_paginas(total: int, size: int) -> int:
    """Cero resultados es una página vacía: al menos 1."""
    return max(1, ceil(total / size))


def verificar_pagina(pag: Paginacion, total: int) -> None:
    pages = calcular_paginas(total, pag.size)
    if pag.page > pages:
        raise EntradaInvalida(f"La página {pag.page} no existe: hay {pages}")


def armar_pagina[T](items: list[T], total: int, pag: Paginacion) -> Pagina[T]:
    return Pagina[T](
        items=items,
        total=total,
        page=pag.page,
        size=pag.size,
        pages=calcular_paginas(total, pag.size),
    )
