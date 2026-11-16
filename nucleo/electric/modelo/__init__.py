"""Modelo del proyecto: la única fuente de verdad de la que sale todo entregable."""

from electric.modelo.entidades import (
    CargaEspecial,
    Circuito,
    Predio,
    PreferenciaAmbiente,
    Preferencias,
    Proyectista,
    Proyecto,
    Punto,
    RefPerfil,
    Supuesto,
    Tablero,
)
from electric.modelo.serializacion import a_json_canonico, hash_canonico

__all__ = [
    "CargaEspecial",
    "Circuito",
    "Predio",
    "Proyectista",
    "PreferenciaAmbiente",
    "Preferencias",
    "Proyecto",
    "Punto",
    "RefPerfil",
    "Supuesto",
    "Tablero",
    "a_json_canonico",
    "hash_canonico",
]
