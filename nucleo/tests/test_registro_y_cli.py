from __future__ import annotations

import json

import pytest

from electric.calculo.registro import descendientes, orden_topologico, registrados
from electric.cli import main

from .conftest import EJEMPLOS, PERFILES

VIVIENDA = str(EJEMPLOS / "vivienda-120m2" / "proyecto.json")


def test_orden_respeta_las_dependencias() -> None:
    orden = [c.id for c in orden_topologico(registrados())]
    assert len(orden) == 13
    for calculo in registrados().values():
        for dependencia in calculo.depende:
            assert orden.index(dependencia) < orden.index(calculo.id)


def test_descendientes_para_recalculo_parcial() -> None:
    calculos = registrados()
    assert descendientes(calculos, "RC-02") == {"RC-02"}
    assert "RC-01" not in descendientes(calculos, "RC-06")
    assert {"RC-07", "RC-08", "RC-09", "RC-11", "RC-12", "RC-13", "RC-14"} <= descendientes(
        calculos, "RC-06"
    )
    assert descendientes(calculos, "RC-01") == set(calculos) - {"RC-02"}


def test_cli_informe(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["calcular", VIVIENDA, "--perfiles", str(PERFILES)]) == 0
    salida = capsys.readouterr().out
    assert salida.startswith("BORRADOR")
    assert "9885 W" in salida
    assert "Tipo I" in salida
    assert "2P 50 A" in salida
    assert "Tablas sin verificar usadas en este cálculo: 16" in salida


def test_cli_json_y_explicar(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["calcular", VIVIENDA, "--perfiles", str(PERFILES), "--json"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert len(datos["huella"]) == 64
    assert main(["calcular", VIVIENDA, "--perfiles", str(PERFILES), "--explicar", "RC-08:C1"]) == 0
    salida = capsys.readouterr().out
    assert "fórmula: ΔV %" in salida
    assert "general/conductores-cobre" in salida


def test_cli_validar_perfil(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validar-perfil", str(PERFILES / "cnel-ep")]) == 0
    assert "válido, 42 tablas" in capsys.readouterr().out


def test_cli_error_legible(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["calcular", "no-existe.json", "--perfiles", str(PERFILES)]) == 1
    assert "Error (error)" in capsys.readouterr().err
