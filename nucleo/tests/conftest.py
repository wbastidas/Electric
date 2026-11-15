from __future__ import annotations

from pathlib import Path

import pytest

from electric.cli import cargar_proyecto
from electric.modelo import Proyecto
from electric.perfiles import Perfil, cargar_perfil

RAIZ = Path(__file__).resolve().parents[2]
PERFILES = RAIZ / "perfiles"
EJEMPLOS = RAIZ / "ejemplos"


@pytest.fixture(scope="session")
def perfil_cnel() -> Perfil:
    return cargar_perfil(PERFILES / "cnel-ep")


@pytest.fixture(scope="session")
def perfil_control() -> Perfil:
    return cargar_perfil(PERFILES / "control-nfpa70")


@pytest.fixture(scope="session")
def vivienda() -> Proyecto:
    return cargar_proyecto(EJEMPLOS / "vivienda-120m2" / "proyecto.json")


@pytest.fixture(scope="session")
def control() -> Proyecto:
    return cargar_proyecto(EJEMPLOS / "control-ups-ct012742" / "proyecto.json")
