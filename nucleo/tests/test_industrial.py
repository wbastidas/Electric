"""Proyectos industriales: cuadro de cargas, transformador y factibilidad."""

from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from electric.cli import main
from electric.errores import DatoInvalido
from electric.industrial import (
    EXISTENTE,
    Industria,
    Maquina,
    TransformadorExistente,
    analizar,
    leer_cuadro,
    plantilla,
)
from electric.perfiles import Perfil


def _cerca(a: D, b: str, tol: str = "0.01") -> bool:
    return abs(a - D(b)) <= D(tol)


def _industria(*maquinas: Maquina, **kw: object) -> Industria:
    return Industria.model_validate({"nombre": "Prueba", "maquinas": maquinas, **kw})


def test_motor_en_hp_se_convierte_a_potencia_de_entrada(perfil_cnel: Perfil) -> None:
    motor = Maquina(
        id="M1", potencia=D(10), unidad="HP", fp=D("0.85"), eficiencia=D("0.9"),
        factor_utilizacion=D(1), factor_simultaneidad=D(1),
    )  # fmt: skip
    fila = analizar(_industria(motor), perfil_cnel).filas[0]
    # 10 HP × 0,746 ÷ 0,9 = 8,289 kW; ÷ 0,85 = 9,752 kVA; ÷ (√3 × 220 V) = 25,59 A.
    assert _cerca(fila.instalada_kw, "8.289")
    assert _cerca(fila.instalada_kva, "9.752")
    assert _cerca(fila.corriente_a, "25.59")
    assert fila.arranque == "directo"
    assert fila.corriente_arranque_a is not None
    assert _cerca(fila.corriente_arranque_a, "153.5", "0.1")
    assert fila.supuestos == ("arranque directo",)


def test_celdas_vacias_toman_los_tipicos_del_perfil_y_quedan_como_supuesto(
    perfil_cnel: Perfil,
) -> None:
    analisis = analizar(_industria(Maquina(id="B", potencia=D(5))), perfil_cnel)
    fila = analisis.filas[0]
    tipico, _ = perfil_cnel.tipo_industrial("motor")
    assert fila.fp == tipico.fp
    assert fila.factor_utilizacion == tipico.factor_utilizacion
    supuestos = analisis.resultado("instalada").supuestos
    assert any("B: factor de potencia" in s for s in supuestos)
    assert analisis.estado == "por_verificar"


def test_demanda_aplica_utilizacion_y_simultaneidad(perfil_cnel: Perfil) -> None:
    horno = Maquina(
        id="H", tipo="resistiva", potencia=D(40), cantidad=2,
        factor_utilizacion=D("0.5"), factor_simultaneidad=D("0.5"),
    )  # fmt: skip
    analisis = analizar(_industria(horno), perfil_cnel)
    assert analisis.resultado("instalada").decimal == D(80)
    assert analisis.resultado("demanda").decimal == D(20)


def test_banco_de_capacitores_lleva_el_fp_al_objetivo(perfil_cnel: Perfil) -> None:
    carga = Maquina(
        id="C", tipo="otro", potencia=D(100), fp=D("0.8"),
        factor_utilizacion=D(1), factor_simultaneidad=D(1),
    )  # fmt: skip
    fp = analizar(_industria(carga), perfil_cnel).resultado("factor_potencia")
    # Q = 75 kVAr; a 0,92 quedan 42,6 kVAr: hacen falta 32,4 kVAr → banco de 40.
    assert _cerca(fp.det("requerido_kvar"), "32.40")
    assert fp.det("banco_kvar") == D(40)
    assert fp.decimal >= D("0.92")
    assert fp.avisos


def test_sin_banco_si_el_fp_ya_cumple(perfil_cnel: Perfil) -> None:
    carga = Maquina(id="R", tipo="resistiva", potencia=D(10))
    fp = analizar(_industria(carga), perfil_cnel).resultado("factor_potencia")
    assert fp.det("banco_kvar") == 0
    assert not fp.avisos


def test_transformador_normalizado_con_reserva(perfil_cnel: Perfil) -> None:
    carga = Maquina(
        id="R", tipo="resistiva", potencia=D(70),
        factor_utilizacion=D(1), factor_simultaneidad=D(1),
    )  # fmt: skip
    analisis = analizar(_industria(carga), perfil_cnel)
    tr = analisis.resultado("transformador")
    # 70 kVA × 1,2 = 84 kVA → 100 kVA trifásico.
    assert tr.decimal == D(100)
    assert tr.detalle["montaje"] == "poste"
    assert analisis.resultado("breaker_principal").decimal == D(250)


@pytest.mark.parametrize(
    ("kw", "nivel"),
    [(8, "red_existente"), (100, "transformador_propio"), (900, "cuarto_mt"),
     (6000, "subestacion")],
)  # fmt: skip
def test_nivel_de_servicio_por_norma(perfil_cnel: Perfil, kw: int, nivel: str) -> None:
    carga = Maquina(
        id="R", tipo="resistiva", potencia=D(kw),
        factor_utilizacion=D(1), factor_simultaneidad=D(1),
    )  # fmt: skip
    decision = analizar(_industria(carga), perfil_cnel).decision
    assert decision.nivel.id == nivel
    if nivel != "red_existente":
        assert decision.opcion == "particular"
    if nivel == "transformador_propio":
        assert "factibilidad" in decision.motivos[0]


def test_demanda_mayor_al_mayor_transformador_avisa(perfil_cnel: Perfil) -> None:
    carga = Maquina(
        id="R", tipo="resistiva", potencia=D(6000),
        factor_utilizacion=D(1), factor_simultaneidad=D(1),
    )  # fmt: skip
    analisis = analizar(_industria(carga), perfil_cnel)
    assert analisis.decision.transformador is None
    assert any("varios transformadores" in a for a in analisis.avisos)


def _taller(existente: TransformadorExistente | None) -> Industria:
    return _industria(
        Maquina(id="M1", potencia=D(5), unidad="HP"),
        Maquina(id="L", tipo="iluminacion", potencia=D(2), fases=1),
        existente=existente,
    )


def test_sin_transformador_existente_queda_pendiente(perfil_cnel: Perfil) -> None:
    decision = analizar(_taller(None), perfil_cnel).decision
    assert decision.nivel.id == "red_existente"
    assert decision.opcion == "pendiente"


def test_usa_el_existente_si_cumple_todo(perfil_cnel: Perfil) -> None:
    existente = TransformadorExistente(
        codigo="T-123", kva=D(75), clientes={"C": 20}, distancia_m=D(60)
    )
    analisis = analizar(_taller(existente), perfil_cnel)
    decision = analisis.decision
    assert decision.opcion == "existente"
    assert "T-123" in decision.titulo
    assert all(c.cumple for c in decision.comprobaciones)
    # 75 × 0,8 − 20 × 1,6 = 28 kVA libres.
    assert analisis.resultado("capacidad_libre", EXISTENTE).decimal == D(28)
    acometida = analisis.resultado("acometida", EXISTENTE)
    assert acometida.det("caida_pct") <= D(5)


@pytest.mark.parametrize(
    ("existente", "falla"),
    [
        (TransformadorExistente(kva=D(25), clientes={"C": 20}, distancia_m=D(60)), "Capacidad"),
        (TransformadorExistente(kva=D(75), demanda_kva=D(10), distancia_m=D(400)), "Distancia"),
        (TransformadorExistente(kva=D(50), fases=1, demanda_kva=D(5), distancia_m=D(30)),
         "Fases"),
    ],
)  # fmt: skip
def test_transformador_particular_si_el_existente_no_cumple(
    perfil_cnel: Perfil, existente: TransformadorExistente, falla: str
) -> None:
    decision = analizar(_taller(existente), perfil_cnel).decision
    assert decision.opcion == "particular"
    assert any(m.startswith(falla) for m in decision.motivos)
    assert decision.transformador is not None


def test_demanda_medida_reemplaza_la_estimada(perfil_cnel: Perfil) -> None:
    existente = TransformadorExistente(
        kva=D(75), demanda_kva=D(50), clientes={"C": 1}, distancia_m=D(20)
    )
    analisis = analizar(_taller(existente), perfil_cnel)
    libre = analisis.resultado("capacidad_libre", EXISTENTE)
    assert libre.decimal == D(10)
    assert libre.entradas["origen_demanda"] == "medida"


def test_existente_sin_demanda_ni_clientes_es_un_error(perfil_cnel: Perfil) -> None:
    existente = TransformadorExistente(kva=D(75), distancia_m=D(20))
    with pytest.raises(DatoInvalido, match="demanda actual"):
        analizar(_taller(existente), perfil_cnel)


def test_arranque_directo_de_un_motor_grande_en_un_transformador_pequeno(
    perfil_cnel: Perfil,
) -> None:
    existente = TransformadorExistente(kva=D(30), demanda_kva=D(0), distancia_m=D(10))
    industria = _industria(
        Maquina(id="M", potencia=D(40), unidad="HP", factor_utilizacion=D("0.3")),
        existente=existente,
    )
    analisis = analizar(industria, perfil_cnel)
    arranque = next(c for c in analisis.decision.comprobaciones if c.nombre.startswith("Arranque"))
    assert not arranque.cumple
    assert analisis.decision.opcion == "particular"


def test_maquina_trifasica_en_sistema_monofasico(perfil_cnel: Perfil) -> None:
    industria = _industria(Maquina(id="M", potencia=D(5)), sistema="monofasico_trifilar_120_240")
    with pytest.raises(DatoInvalido, match="trifásica"):
        analizar(industria, perfil_cnel)


def test_solo_motores_llevan_arranque(perfil_cnel: Perfil) -> None:
    industria = _industria(Maquina(id="R", tipo="resistiva", potencia=D(5), arranque="directo"))
    with pytest.raises(DatoInvalido, match="arranque"):
        analizar(industria, perfil_cnel)


def test_maquinas_repetidas() -> None:
    with pytest.raises(ValueError, match="repetida"):
        _industria(Maquina(id="A", potencia=D(1)), Maquina(id="A", potencia=D(2)))


# --- Excel y CSV --------------------------------------------------------------


def _plantilla(perfil: Perfil) -> bytes:
    return plantilla(
        [(t.tipo, t.nombre) for t in perfil.tipos_industriales()],
        [(a.id, a.nombre) for a in perfil.arranques()],
    )


def test_la_plantilla_se_lee_y_se_analiza(perfil_cnel: Perfil) -> None:
    maquinas = leer_cuadro(_plantilla(perfil_cnel), "cuadro.xlsx")
    assert [m.id for m in maquinas] == ["M-01", "M-02", "R-01", "S-01", "L-01", "T-01"]
    assert maquinas[0].unidad == "HP"
    assert maquinas[0].arranque == "estrella_triangulo"
    assert maquinas[1].cantidad == 2
    analisis = analizar(Industria(nombre="Plantilla", maquinas=maquinas), perfil_cnel)
    assert {t.tablero for t in analisis.tableros} == {"TD-1", "TD-2", "TD-3"}
    assert analisis.decision.nivel.id == "transformador_propio"


def test_csv_con_punto_y_coma_coma_decimal_y_unidad_en_el_encabezado() -> None:
    texto = (
        "Código;Descripción;Tipo;Potencia (HP);Fases;Factor de potencia;Arranque\n"
        "1;Molino;Motor;7,5;3;0,82;Estrella-triángulo\n"
        ";;;;;;\n"
        "2;Banda;motor;2;3;;\n"
    )
    maquinas = leer_cuadro(texto.encode("utf-8"), "cuadro.csv")
    assert [m.id for m in maquinas] == ["1", "2"]
    assert maquinas[0].potencia == D("7.5")
    assert maquinas[0].unidad == "HP"
    assert maquinas[0].fp == D("0.82")
    assert maquinas[0].arranque == "estrella_triangulo"
    assert maquinas[1].fp is None


def test_errores_del_cuadro_indican_la_fila() -> None:
    texto = "Código,Potencia,FP\nA,10,1.5\nB,,0.9\n"
    with pytest.raises(DatoInvalido) as error:
        leer_cuadro(texto.encode(), "cuadro.csv")
    assert "fila 2" in str(error.value)
    assert "fila 3: falta la potencia" in str(error.value)


def test_cuadro_sin_columna_de_potencia() -> None:
    with pytest.raises(DatoInvalido, match="Potencia"):
        leer_cuadro(b"Codigo,Descripcion\nA,Motor\n", "cuadro.csv")


def test_formato_no_admitido() -> None:
    with pytest.raises(DatoInvalido, match="xlsx"):
        leer_cuadro(b"", "cuadro.ods")


# --- Línea de comandos --------------------------------------------------------


def test_cli_industrial(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cuadro = tmp_path / "cuadro.xlsx"
    assert main(["plantilla-industrial", str(cuadro)]) == 0
    assert cuadro.exists()
    assert main(["industrial", str(cuadro), "--nombre", "Taller"]) == 0
    salida = capsys.readouterr().out
    assert "Decisión: Transformador particular" in salida
    assert "Transformador propuesto: 100 kVA" in salida

    csv = tmp_path / "taller.csv"
    csv.write_text("Código,Potencia (HP),Tipo\nM1,5,motor\n", encoding="utf-8")
    argumentos = ["industrial", str(csv), "--existente-kva", "75", "--clientes", "C=20"]
    assert main([*argumentos, "--distancia", "60", "--codigo", "T-9"]) == 0
    assert "Usar el transformador existente T-9" in capsys.readouterr().out


def test_sobre_12_kw_puede_usar_el_existente_sujeto_a_factibilidad(perfil_cnel: Perfil) -> None:
    carga = Maquina(
        id="R", tipo="resistiva", potencia=D(20),
        factor_utilizacion=D(1), factor_simultaneidad=D(1),
    )  # fmt: skip
    existente = TransformadorExistente(kva=D(100), demanda_kva=D(30), distancia_m=D(40))
    decision = analizar(_industria(carga, existente=existente), perfil_cnel).decision
    assert decision.nivel.id == "transformador_propio"
    assert decision.opcion == "existente"
    assert "factibilidad" in decision.motivos[1]
