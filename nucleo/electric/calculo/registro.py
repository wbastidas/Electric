"""Registro de cálculos y su orden de ejecución.

Cada cálculo declara de cuáles depende; el registro los ordena. Los cálculos
son funciones puras: sin reloj, red, archivos ni aleatoriedad.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from electric.calculo.resultado import Resultado

if TYPE_CHECKING:
    from electric.calculo.contexto import Contexto

Funcion = Callable[["Contexto"], list[Resultado]]


@dataclass(frozen=True)
class Calculo:
    id: str
    nombre: str
    depende: tuple[str, ...]
    funcion: Funcion


_REGISTRO: dict[str, Calculo] = {}


def calculo(id: str, nombre: str, depende: tuple[str, ...] = ()) -> Callable[[Funcion], Funcion]:
    def decorador(funcion: Funcion) -> Funcion:
        if id in _REGISTRO:
            raise ValueError(f"cálculo registrado dos veces: {id}")
        _REGISTRO[id] = Calculo(id=id, nombre=nombre, depende=depende, funcion=funcion)
        return funcion

    return decorador


def registrados() -> dict[str, Calculo]:
    return dict(_REGISTRO)


def orden_topologico(calculos: dict[str, Calculo]) -> list[Calculo]:
    """Orden de ejecución estable: por dependencias y, a igualdad, por identificador."""
    pendientes = dict(calculos)
    hechos: list[Calculo] = []
    listos: set[str] = set()
    while pendientes:
        disponibles = sorted(
            id for id, c in pendientes.items() if all(d in listos for d in c.depende)
        )
        if not disponibles:
            raise ValueError(f"dependencias circulares o inexistentes: {sorted(pendientes)}")
        siguiente = disponibles[0]
        hechos.append(pendientes.pop(siguiente))
        listos.add(siguiente)
    return hechos


def descendientes(calculos: dict[str, Calculo], origen: str) -> set[str]:
    """Cálculos que hay que repetir cuando cambia el resultado de `origen`."""
    afectados = {origen}
    cambio = True
    while cambio:
        cambio = False
        for id, c in calculos.items():
            if id not in afectados and any(d in afectados for d in c.depende):
                afectados.add(id)
                cambio = True
    return afectados
