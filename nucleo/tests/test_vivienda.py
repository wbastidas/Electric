"""Vivienda de ejemplo con el perfil CNEL EP, comprobada a mano.

Las cifras esperadas están escritas como aritmética explícita, sin usar el
motor, para que la prueba sea independiente del código que verifica.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal as D

import pytest

from electric.calculo import ALIMENTADOR, PROYECTO, Calculado, calcular
from electric.errores import DatoInvalido, SinSolucion
from electric.modelo import Proyecto, a_json_canonico
from electric.perfiles import Perfil

from .conftest import EJEMPLOS

FP = 0.92


@pytest.fixture(scope="module")
def calculado(vivienda: Proyecto, perfil_cnel: Perfil) -> Calculado:
    return calcular(vivienda, perfil_cnel)


def _f(calculado: Calculado, id: str, sujeto: str) -> float:
    return float(calculado.res(id, sujeto).decimal)


def test_carga_instalada(calculado: Calculado) -> None:
    assert calculado.res("RC-01", "C1").decimal == 10 * 100
    assert calculado.res("RC-01", "C2").decimal == 8 * 100
    assert calculado.res("RC-01", "C3").decimal == 8 * 200
    assert calculado.res("RC-01", "C4").decimal == 7 * 200
    assert calculado.res("RC-01", "C5").decimal == 3500
    assert calculado.res("RC-01", "C6").decimal == 6000
    assert calculado.res("RC-01", PROYECTO).decimal == 14300


def test_circuitos_minimos(calculado: Calculado) -> None:
    minimo = calculado.res("RC-02", PROYECTO)
    assert minimo.det("minimo_iluminacion") == 2
    assert minimo.det("minimo_tomacorrientes") == 2
    assert minimo.avisos == ()


def test_demanda_y_clasificacion(calculado: Calculado) -> None:
    # Mediana (120 m²): 0,70 iluminación, 0,50 tomas; dos especiales: 0,75.
    esperado = D(1800) * D("0.70") + D(3000) * D("0.50") + D(9500) * D("0.75")
    assert esperado == D(9885)
    assert calculado.res("RC-03", PROYECTO).decimal == esperado
    assert calculado.res("RC-05", PROYECTO).valor == "Tipo I"


@pytest.mark.parametrize(
    ("sujeto", "potencia", "tension"),
    [
        ("C1", 1000, 120),
        ("C3", 1600, 120),
        ("C5", 3500, 120),
        ("C6", 6000, 240),
        (ALIMENTADOR, 9885, 240),
    ],
)
def test_corriente(calculado: Calculado, sujeto: str, potencia: int, tension: int) -> None:
    assert _f(calculado, "RC-06", sujeto) == pytest.approx(potencia / (tension * FP), rel=1e-12)


@pytest.mark.parametrize(
    ("sujeto", "calibre", "breaker", "polos"),
    [
        ("C1", "14 AWG", 15, 1),
        ("C2", "14 AWG", 15, 1),
        ("C3", "12 AWG", 20, 1),
        # 12 AWG daría 3,24 % en 25 m; el motor sube a 10 AWG.
        ("C4", "10 AWG", 20, 1),
        # 31,7 A: breaker de 40 A; 10 AWG solo admite 30 A, así que sube a 8 AWG.
        ("C5", "8 AWG", 40, 1),
        # 27,2 A: breaker de 30 A; 27,2 × 1,25 = 34 A cabe en 10 AWG (35 A).
        ("C6", "10 AWG", 30, 2),
        # 44,8 A: breaker de 50 A; 44,8 × 1,25 = 56 A cabe en 6 AWG (65 A).
        (ALIMENTADOR, "6 AWG", 50, 2),
    ],
)
def test_conductor_y_proteccion(
    calculado: Calculado, sujeto: str, calibre: str, breaker: int, polos: int
) -> None:
    assert calculado.res("RC-07", sujeto).valor == calibre
    proteccion = calculado.res("RC-09", sujeto)
    assert proteccion.decimal == breaker
    assert proteccion.det("polos") == polos


def test_subida_de_calibre_por_caida_queda_avisada(calculado: Calculado) -> None:
    conductor = calculado.res("RC-07", "C4")
    assert conductor.det("pasos_por_caida") == 1
    assert "caída de tensión" in conductor.avisos[0]
    assert calculado.res("RC-07", "C1").avisos == ()


def _caida(potencia: float, tension: float, largo: float, r: float, x: float) -> float:
    i = potencia / (tension * FP)
    return 2 * i * largo * (r * FP + x * math.sqrt(1 - FP**2)) / 1000 / tension * 100


@pytest.mark.parametrize(
    ("sujeto", "esperado"),
    [
        ("C1", _caida(1000, 120, 18, 10.2, 0.190)),
        ("C4", _caida(1400, 120, 25, 3.9, 0.164)),
        ("C6", _caida(6000, 240, 10, 3.9, 0.164)),
        (ALIMENTADOR, _caida(9885, 240, 15, 1.61, 0.167)),
    ],
)
def test_caida_de_tension(calculado: Calculado, sujeto: str, esperado: float) -> None:
    assert _f(calculado, "RC-08", sujeto) == pytest.approx(esperado, rel=1e-9)


def test_caida_dentro_de_limites(calculado: Calculado) -> None:
    for resultado in calculado.de("RC-08"):
        assert resultado.decimal <= resultado.det("limite_pct")
        if resultado.sujeto != ALIMENTADOR:
            assert resultado.det("total_con_alimentador_pct") <= 5
        assert resultado.avisos == ()


def test_balanceo(calculado: Calculado) -> None:
    fases = {r.sujeto: r.valor for r in calculado.de("RC-10") if r.sujeto != PROYECTO}
    assert fases["C6"] == "AB"
    desbalance = calculado.res("RC-10", PROYECTO)
    a, b = desbalance.entradas["fase_A_w"], desbalance.entradas["fase_B_w"]
    assert isinstance(a, D) and isinstance(b, D)
    assert a + b == 14300  # la suma de fases conserva la potencia
    assert {a, b} == {D(7300), D(7000)}
    assert float(desbalance.decimal) == pytest.approx(300 / 7300 * 100)
    assert desbalance.avisos == ()


def test_tablero_medidor_y_tierra(calculado: Calculado) -> None:
    tablero = calculado.res("RC-11", "TD-1")
    assert tablero.entradas == {"polos_usados": D(7), "polos_reserva": D(2)}
    assert tablero.decimal == 12
    assert tablero.det("principal_a") == 50
    assert tablero.det("barras_a") == 100
    assert calculado.res("RC-12", PROYECTO).valor == "clase 100"
    assert calculado.res("RC-14", "C1").valor == "14 AWG"
    assert calculado.res("RC-14", ALIMENTADOR).valor == "10 AWG"
    assert calculado.res("RC-14", PROYECTO).decimal == 20


def test_ducteria(calculado: Calculado) -> None:
    # C1: dos 14 AWG y tierra 14 AWG: 3 × 6,26 = 18,78 mm²; al 40 % caben en 1/2".
    ducto = calculado.res("RC-13", "C1")
    assert ducto.valor == '1/2"'
    assert ducto.entradas["area_conductores_mm2"] == D("18.78")
    # Alimentador: tres 6 AWG y tierra 10 AWG: 111,74 mm²; exige 279,4 mm²: 3/4".
    assert calculado.res("RC-13", ALIMENTADOR).valor == '3/4"'
    for resultado in calculado.de("RC-13"):
        assert resultado.det("relleno_pct") <= 40


def test_diferencial_solo_en_zonas_humedas(calculado: Calculado) -> None:
    assert calculado.res("RC-09", "C4").detalle["diferencial"] == "sí"
    assert calculado.res("RC-09", "C5").detalle["diferencial"] == "sí"
    assert calculado.res("RC-09", "C1").detalle["diferencial"] == "no"


def test_todo_resultado_declara_tablas_y_estado(calculado: Calculado) -> None:
    for resultado in calculado.resultados:
        assert resultado.formula
        assert resultado.tablas, f"{resultado.id} {resultado.sujeto} no cita tablas"
        assert resultado.estado == "por_verificar"


def test_determinismo(vivienda: Proyecto, perfil_cnel: Perfil, calculado: Calculado) -> None:
    otra_vez = calcular(vivienda, perfil_cnel)
    assert otra_vez.hash == calculado.hash
    assert a_json_canonico(list(otra_vez.resultados)) == a_json_canonico(list(calculado.resultados))


def test_regresion_contra_la_salida_guardada(calculado: Calculado) -> None:
    """Cualquier cambio en un número rompe esta prueba.

    Para regenerar tras un cambio intencional:
        electric calcular ejemplos/vivienda-120m2/proyecto.json --json \
            > ejemplos/vivienda-120m2/resultados.json
    """
    guardado = json.loads((EJEMPLOS / "vivienda-120m2" / "resultados.json").read_text("utf-8"))
    assert guardado["huella"] == calculado.hash
    assert guardado["resultados"] == json.loads(a_json_canonico(list(calculado.resultados)))


# --- supuestos y errores --------------------------------------------------


def _con(vivienda: Proyecto, **cambios: object) -> Proyecto:
    return Proyecto.model_validate({**vivienda.model_dump(), **cambios})


def test_supuesto_sobrescribe_y_queda_registrado(vivienda: Proyecto, perfil_cnel: Perfil) -> None:
    supuesto = {
        "parametro": "factor_potencia",
        "valor": D("1"),
        "justificacion": "cargas resistivas",
        "autor": "Ing. de prueba",
        "fecha": "2026-11-15",
    }
    calculado = calcular(_con(vivienda, supuestos=[supuesto]), perfil_cnel)
    corriente = calculado.res("RC-06", "C1")
    assert float(corriente.decimal) == pytest.approx(1000 / 120)
    assert "cargas resistivas" in corriente.supuestos[0]
    # La demanda no usa el factor de potencia: no debe citar el supuesto.
    assert calculado.res("RC-03", PROYECTO).supuestos == ()


def test_potencia_de_placa_reemplaza_el_valor_por_defecto(
    vivienda: Proyecto, perfil_cnel: Perfil
) -> None:
    cargas = [c.model_dump() for c in vivienda.cargas_especiales]
    cargas[0]["potencia_w"] = D(4500)
    calculado = calcular(_con(vivienda, cargas_especiales=cargas), perfil_cnel)
    circuito = calculado.res("RC-01", "C5")
    assert circuito.decimal == 4500
    assert "placa" in circuito.supuestos[0]


def test_faltan_circuitos_minimos_da_aviso(vivienda: Proyecto, perfil_cnel: Perfil) -> None:
    calculado = calcular(_con(vivienda, area_construida_m2=D(250)), perfil_cnel)
    avisos = calculado.res("RC-02", PROYECTO).avisos
    assert len(avisos) == 2
    assert "el mínimo es 3" in avisos[0]


def test_demanda_sobre_12_kw_es_tipo_ii(vivienda: Proyecto, perfil_cnel: Perfil) -> None:
    cargas = [c.model_dump() for c in vivienda.cargas_especiales]
    cargas[1]["potencia_w"] = D(12000)
    calculado = calcular(_con(vivienda, cargas_especiales=cargas), perfil_cnel)
    assert calculado.res("RC-03", PROYECTO).decimal > 12000
    assert calculado.res("RC-05", PROYECTO).valor == "Tipo II"


def test_carga_entre_lineas_en_sistema_bifilar_es_error(
    vivienda: Proyecto, perfil_cnel: Perfil
) -> None:
    with pytest.raises(DatoInvalido, match="entre líneas"):
        calcular(_con(vivienda, sistema="monofasico_bifilar_120"), perfil_cnel)


def test_recorrido_imposible_es_error_y_no_un_valor_inventado(
    vivienda: Proyecto, perfil_cnel: Perfil
) -> None:
    circuitos = [c.model_dump() for c in vivienda.circuitos]
    circuitos[2]["longitud_m"] = D(900)
    with pytest.raises(SinSolucion) as error:
        calcular(_con(vivienda, circuitos=circuitos), perfil_cnel)
    assert error.value.sujeto == "C3"


def test_perfil_distinto_al_del_proyecto_es_error(
    vivienda: Proyecto, perfil_control: Perfil
) -> None:
    with pytest.raises(DatoInvalido, match="perfil"):
        calcular(vivienda, perfil_control)


def test_fase_fijada_por_el_usuario_se_respeta(vivienda: Proyecto, perfil_cnel: Perfil) -> None:
    circuitos = [c.model_dump() for c in vivienda.circuitos]
    circuitos[0]["fase"] = "A"
    calculado = calcular(_con(vivienda, circuitos=circuitos), perfil_cnel)
    fase = calculado.res("RC-10", "C1")
    assert fase.valor == "A"
    assert fase.detalle["origen"] == "fijada"

    circuitos[0]["fase"] = "C"
    with pytest.raises(DatoInvalido, match="fase"):
        calcular(_con(vivienda, circuitos=circuitos), perfil_cnel)
