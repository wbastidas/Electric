"""Caso de control del documento de requerimientos (CA-02).

Vivienda de 1.045 ft² de la tesis UPS CT012742, calculada con NFPA 70:
9.861 VA instalados, 5.401 VA de demanda y 22,5 A a 240 V.
"""

from __future__ import annotations

from decimal import Decimal as D

from electric.calculo import ALIMENTADOR, PROYECTO, calcular
from electric.calculo.resultado import redondear
from electric.modelo import Proyecto
from electric.perfiles import Perfil

TOLERANCIA = D("0.005")  # CA-02: diferencia ≤ 0,5 %


def _cerca(obtenido: D, esperado: D) -> bool:
    return abs(obtenido - esperado) / esperado <= TOLERANCIA


def test_reproduce_las_tres_cifras_de_la_tesis(control: Proyecto, perfil_control: Perfil) -> None:
    calculado = calcular(control, perfil_control)
    instalada = calculado.res("RC-01", PROYECTO).decimal
    demanda = calculado.res("RC-03", PROYECTO).decimal
    corriente = calculado.res("RC-06", ALIMENTADOR).decimal

    assert instalada == D(9861)
    assert redondear(demanda, 0) == D(5401)
    assert redondear(corriente, 1) == D("22.5")
    assert _cerca(demanda, D(5401))
    assert _cerca(corriente, D("22.5"))
    assert calculado.res("RC-06", ALIMENTADOR).entradas["tension_v"] == D(240)


def test_la_demanda_del_control_arrastra_el_defecto_de_la_fuente(
    control: Proyecto, perfil_control: Perfil
) -> None:
    # La tesis aplica el 35 % a todo el subtotal; el resultado debe decirlo.
    calculado = calcular(control, perfil_control)
    demanda = calculado.res("RC-03", PROYECTO)
    assert demanda.estado == "defecto_fuente"
    assert demanda.entradas["tramo_1_w"] == D(3000)
    assert demanda.entradas["tramo_2_w"] == D(6861)
    # Todo lo que depende de la demanda hereda el estado.
    assert calculado.res("RC-06", ALIMENTADOR).estado == "defecto_fuente"
    assert calculado.res("RC-05", PROYECTO).estado == "defecto_fuente"
