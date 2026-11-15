"""Pruebas de propiedades (sección 9 del documento de requerimientos)."""

from __future__ import annotations

from decimal import Decimal as D

from hypothesis import given, settings
from hypothesis import strategies as st

from electric.calculo import ALIMENTADOR, PROYECTO, calcular
from electric.calculo.tramos import caida_pct, corriente
from electric.errores import SinSolucion
from electric.modelo import Proyecto
from electric.perfiles import Perfil, cargar_perfil

from .conftest import EJEMPLOS, PERFILES

PERFIL: Perfil = cargar_perfil(PERFILES / "cnel-ep")
BASE = Proyecto.model_validate_json(
    (EJEMPLOS / "vivienda-120m2" / "proyecto.json").read_text("utf-8")
)
CALIBRES = [f.calibre for f in PERFIL.conductores()[0]]

decimales = st.decimals(min_value=D("0.5"), max_value=D(200), places=2)
factores = st.decimals(min_value=D("0.70"), max_value=D(1), places=2)


@given(i=decimales, largo=decimales, extra=decimales, fp=factores)
def test_la_caida_crece_con_la_longitud_y_la_corriente(i: D, largo: D, extra: D, fp: D) -> None:
    def caida(corriente_a: D, longitud_m: D) -> D:
        return caida_pct(corriente_a, longitud_m, D(120), fp, D("6.6"), D("0.177"), D(2))

    assert caida(i, largo + extra) > caida(i, largo)
    assert caida(i + extra, largo) > caida(i, largo)


@given(p=st.decimals(min_value=D(1), max_value=D(50000), places=0), fp=factores)
def test_la_corriente_trifasica_es_menor_que_la_monofasica(p: D, fp: D) -> None:
    assert corriente(p, D(220), fp, True) < corriente(p, D(220), fp, False)


def _con_ducha(potencia: D) -> Proyecto:
    datos = BASE.model_dump()
    datos["cargas_especiales"][0]["potencia_w"] = potencia
    return Proyecto.model_validate(datos)


potencias = st.decimals(min_value=D(500), max_value=D(9000), places=0)


@settings(max_examples=60, deadline=None)
@given(menor=potencias, aumento=st.decimals(min_value=D(0), max_value=D(3000), places=0))
def test_subir_la_carga_nunca_baja_el_calibre_ni_el_breaker(menor: D, aumento: D) -> None:
    try:
        antes = calcular(_con_ducha(menor), PERFIL)
        despues = calcular(_con_ducha(menor + aumento), PERFIL)
    except SinSolucion:
        return
    for sujeto in ("C5", ALIMENTADOR):
        calibre_antes = str(antes.res("RC-07", sujeto).valor)
        calibre_despues = str(despues.res("RC-07", sujeto).valor)
        assert CALIBRES.index(calibre_despues) >= CALIBRES.index(calibre_antes)
        assert despues.res("RC-09", sujeto).decimal >= antes.res("RC-09", sujeto).decimal


@settings(max_examples=60, deadline=None)
@given(potencia=potencias)
def test_la_suma_de_fases_conserva_la_potencia(potencia: D) -> None:
    try:
        calculado = calcular(_con_ducha(potencia), PERFIL)
    except SinSolucion:
        return
    desbalance = calculado.res("RC-10", PROYECTO)
    por_fase = [v for v in desbalance.entradas.values() if isinstance(v, D)]
    assert sum(por_fase, D(0)) == calculado.res("RC-01", PROYECTO).decimal


@settings(max_examples=60, deadline=None)
@given(potencia=potencias)
def test_todo_tramo_cumple_ampacidad_proteccion_y_caida(potencia: D) -> None:
    try:
        calculado = calcular(_con_ducha(potencia), PERFIL)
    except SinSolucion:
        return
    for conductor in calculado.de("RC-07"):
        sujeto = conductor.sujeto
        breaker = calculado.res("RC-09", sujeto).decimal
        diseno = conductor.entradas["corriente_diseno_a"]
        assert isinstance(diseno, D)
        assert conductor.det("ampacidad_corregida_a") >= diseno
        assert breaker >= diseno
        caida = calculado.res("RC-08", sujeto)
        assert caida.decimal <= caida.det("limite_pct")
