from __future__ import annotations

from decimal import Decimal as D
from typing import Any

import pytest
from pydantic import ValidationError

from electric.modelo import Proyecto, a_json_canonico, hash_canonico


def _datos(vivienda: Proyecto) -> dict[str, Any]:
    return vivienda.model_dump()


def test_el_ejemplo_es_valido_e_inmutable(vivienda: Proyecto) -> None:
    assert len(vivienda.puntos) == 33
    with pytest.raises(ValidationError):
        vivienda.nombre = "otro"  # type: ignore[misc]


def test_hash_estable_e_independiente_del_orden_de_claves(vivienda: Proyecto) -> None:
    datos = _datos(vivienda)
    invertido = dict(reversed(list(datos.items())))
    assert hash_canonico(vivienda) == hash_canonico(Proyecto.model_validate(invertido))
    assert hash_canonico(vivienda) == hash_canonico(Proyecto.model_validate(datos))


def test_decimales_equivalentes_dan_el_mismo_json() -> None:
    assert a_json_canonico({"a": D("1.50")}) == a_json_canonico({"a": D("1.5")}) == '{"a":"1.5"}'
    assert a_json_canonico({"a": D("0.000")}) == '{"a":"0"}'


def test_la_serializacion_rechaza_coma_flotante() -> None:
    with pytest.raises(TypeError):
        a_json_canonico({"a": 1.5})


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        (lambda d: d["puntos"][0].update(circuito="C99"), "inexistente"),
        (lambda d: d["puntos"][0].update(circuito="C5"), "especial"),
        (lambda d: d["cargas_especiales"][0].update(circuito="C1"), "especial"),
        (lambda d: d["cargas_especiales"][0].update(circuito="C6"), "más de una carga"),
        (lambda d: d["puntos"][1].update(id=d["puntos"][0]["id"]), "repetidos"),
        (lambda d: d.update(cargas_especiales=d["cargas_especiales"][:1]), "sin puntos"),
        (lambda d: d["circuitos"][0].update(longitud_m=D(0)), "greater than 0"),
        (lambda d: d.update(inventado=1), "Extra inputs"),
    ],
)
def test_proyectos_incoherentes_se_rechazan(vivienda: Proyecto, cambio: Any, mensaje: str) -> None:
    datos = _datos(vivienda)
    cambio(datos)
    with pytest.raises(ValidationError, match=mensaje):
        Proyecto.model_validate(datos)


def test_supuesto_exige_justificacion_y_parametro_conocido(vivienda: Proyecto) -> None:
    datos = _datos(vivienda)
    base = {"valor": D("0.95"), "autor": "Ing. de prueba", "fecha": "2026-11-15"}
    datos["supuestos"] = [{**base, "parametro": "factor_potencia", "justificacion": ""}]
    with pytest.raises(ValidationError):
        Proyecto.model_validate(datos)
    datos["supuestos"] = [{**base, "parametro": "umbral_tipo_i_kw", "justificacion": "prueba"}]
    with pytest.raises(ValidationError, match="no se puede sobrescribir"):
        Proyecto.model_validate(datos)
