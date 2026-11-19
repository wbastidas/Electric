"""Subestación 69/13,8 kV: transformador, cortocircuito, equipos y malla IEEE 80."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from electric.perfiles.carga import Perfil
from electric.subestacion import (
    Subestacion,
    calcular_subestacion,
    generar_plano_malla,
    generar_unifilar_subestacion,
)


@pytest.mark.parametrize(
    ("demanda", "onan", "onaf"),
    [("4", "5", "6.25"), ("8.5", "10", "12.5"), ("15", "16", "20"), ("22", "24", "32")],
)
def test_transformador_habitual(perfil_cnel: Perfil, demanda: str, onan: str, onaf: str) -> None:
    c = calcular_subestacion(Subestacion(nombre="SE", demanda_mva=D(demanda)), perfil_cnel)
    assert c.transformador is not None
    assert (c.transformador.mva_onan, c.transformador.mva_onaf) == (D(onan), D(onaf))
    assert c.transformador.mva_onaf >= D(demanda) * D("1.2")


def test_corrientes_y_cortocircuito(perfil_cnel: Perfil) -> None:
    c = calcular_subestacion(Subestacion(nombre="SE", demanda_mva=D("8.5")), perfil_cnel)
    # 12,5 MVA: 104,6 A en 69 kV y 523 A en 13,8 kV.
    assert round(c.corriente_at_a, 1) == D("104.6") and round(c.corriente_mt_a) == 523
    # Scc 500 MVA supuesta: 4,18 kA en 69 kV; en 13,8 kV con Z 8,5 % sobre 10 MVA.
    assert round(c.icc_at_ka, 2) == D("4.18")
    esperado = D(10) / (D(3).sqrt() * D("13.8")) / (D(10) / D(500) + D("0.085"))
    assert abs(c.icc_mt_ka - esperado) < D("0.001")
    cc = next(r for r in c.resultados if r.id == "cortocircuito")
    assert any("por verificar" in s for s in cc.supuestos)
    propia = calcular_subestacion(
        Subestacion(nombre="SE", demanda_mva=D("8.5"), scc_at_mva=D(1000)), perfil_cnel
    )
    assert propia.icc_mt_ka > c.icc_mt_ka


def test_equipos(perfil_cnel: Perfil) -> None:
    c = calcular_subestacion(Subestacion(nombre="SE", demanda_mva=D("15")), perfil_cnel)
    eq = {e.nombre: e.especificacion for e in c.equipos}
    assert "1250 A" in eq["Interruptor principal de 13,8 kV"]  # 837 A × 1,25
    assert eq["TC principal de 13,8 kV"] == "1200/5 A"
    assert "60 kV" in eq["Pararrayos de 69 kV"]


def test_alimentadores_sobrecargados(perfil_cnel: Perfil) -> None:
    c = calcular_subestacion(
        Subestacion(nombre="SE", demanda_mva=D("20"), alimentadores=2), perfil_cnel
    )
    assert any("alimentadores" in a for a in c.avisos)


def test_malla_ieee80(perfil_cnel: Perfil) -> None:
    c = calcular_subestacion(Subestacion(nombre="SE", demanda_mva=D("8.5")), perfil_cnel)
    m = c.malla
    assert m.cumple and m.tension_malla_v <= m.contacto_tolerable_v
    assert m.tension_paso_v <= m.paso_tolerable_v
    assert m.calibre_minimo_kcmil < 133.1 and m.calibre == "2/0 AWG"
    # Suelo muy resistivo: más resistencia y tensiones más altas.
    dura = calcular_subestacion(
        Subestacion(nombre="SE", demanda_mva=D("8.5"), resistividad_ohm_m=D(1000)), perfil_cnel
    )
    assert dura.malla.resistencia_ohm > m.resistencia_ohm * 9
    assert not dura.malla.resistencia_cumple and any("resistencia" in a for a in dura.avisos)


def test_planos(perfil_cnel: Perfil) -> None:
    c = calcular_subestacion(Subestacion(nombre="SE", demanda_mva=D("8.5")), perfil_cnel)
    assert b"BARRA 13" in generar_unifilar_subestacion(c)
    assert b"IEEE 80" in generar_plano_malla(c)
