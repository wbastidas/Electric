"""Edificios de departamentos, locales y oficinas con centro de medición."""

from electric.edificio.calculo import EdificioCalculado, calcular_edificio
from electric.edificio.modelo import CargaGeneral, Edificio, TipoUnidad
from electric.edificio.unifilar import generar_unifilar_edificio

__all__ = [
    "CargaGeneral",
    "Edificio",
    "EdificioCalculado",
    "TipoUnidad",
    "calcular_edificio",
    "generar_unifilar_edificio",
]
