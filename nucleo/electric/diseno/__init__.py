"""Diseño automático de la instalación sobre los ambientes del plano, y su edición."""

from electric.diseno.automatico import Diseno, disenar
from electric.diseno.edicion import (
    Agregar,
    CambiarCircuito,
    Edicion,
    Editado,
    Liberar,
    Mover,
    Quitar,
    editar,
    retrazar,
)

__all__ = [
    "Agregar",
    "CambiarCircuito",
    "Diseno",
    "Edicion",
    "Editado",
    "Liberar",
    "Mover",
    "Quitar",
    "disenar",
    "editar",
    "retrazar",
]
