"""Perfiles normativos: reglas y tablas versionadas como datos (RNF-12)."""

from electric.perfiles.carga import Perfil, cargar_perfil
from electric.perfiles.esquema import Estado, RefTabla, peor_estado

__all__ = ["Estado", "Perfil", "RefTabla", "cargar_perfil", "peor_estado"]
