"""Configuración por variables de entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    #: URL de SQLAlchemy. SQLite sirve para desarrollo; producción usa PostgreSQL.
    base_de_datos: str
    perfiles: Path
    #: Carpeta con la interfaz web compilada; si existe, la API la sirve.
    web: Path


def leer_config() -> Config:
    return Config(
        base_de_datos=os.environ.get("ELECTRIC_BD", "sqlite:///./electric.db"),
        perfiles=Path(os.environ.get("ELECTRIC_PERFILES", _RAIZ / "perfiles")),
        web=Path(os.environ.get("ELECTRIC_WEB", _RAIZ / "web" / "dist")),
    )
