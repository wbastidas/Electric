"""Asistente: de las respuestas del usuario a las opciones Básica, Recomendada y Confort."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from electric.calculo import PROYECTO
from electric.diseno.opciones import Respuestas, preferencias_para
from electric.errores import DatoInvalido
from electric.flujo import Resultado, proyecto_desde_plano
from electric.ingesta import leer_dxf
from electric.interpretacion import interpretar
from electric.modelo import Preferencias
from electric.modelo.plano import Plano
from electric.perfiles import Perfil

from .conftest import EJEMPLOS

PLANTA = EJEMPLOS / "vivienda-plano" / "planta.dxf"
RESPUESTAS = Respuestas(
    zona_climatica="sierra",
    aire="dormitorios",
    iluminacion="plafon",
    iluminacion_social="ojos_de_buey",
    iluminacion_dormitorios="foco_central",
    refrigeradora=False,
    exteriores=False,
    equipos=("ducha", "cocina"),
)


@pytest.fixture(scope="module")
def plano(perfil_cnel: Perfil) -> Plano:
    return interpretar(leer_dxf(PLANTA.read_bytes(), "planta.dxf"), perfil_cnel)


def _disenar(perfil: Perfil, preferencias: Preferencias) -> Resultado:
    return proyecto_desde_plano(
        PLANTA.read_bytes(),
        "planta.dxf",
        perfil,
        id="opcion",
        nombre="Opción",
        equipos=RESPUESTAS.equipos,
        alimentador_m=D(12),
        preferencias=preferencias,
    )


@pytest.fixture(scope="module")
def opciones(plano: Plano, perfil_cnel: Perfil) -> dict[str, Resultado]:
    return {
        o: _disenar(perfil_cnel, preferencias_para(o, RESPUESTAS, plano, perfil_cnel))
        for o in ("basica", "recomendada", "confort")
    }


def _ids(plano: Plano) -> dict[str, str]:
    return {a.nombre: a.id for a in plano.ambientes}


def _luces(r: Resultado, aid: str) -> int:
    return sum(1 for p in r.proyecto.puntos if p.ambiente == aid and p.tipo == "punto_luz")


def _aires(r: Resultado) -> set[str]:
    return {c.id for c in r.proyecto.cargas_especiales if c.tipo == "aire_acondicionado"}


def test_recomendada_es_lo_que_respondio(opciones: dict[str, Resultado], plano: Plano) -> None:
    r = opciones["recomendada"]
    ids = _ids(plano)
    # Aire solo en dormitorios, aunque la Sierra no lo pide.
    dormitorios = {ids[n] for n in ("DORMITORIO MASTER", "DORMITORIO 2", "DORMITORIO 3")}
    assert _aires(r) == {f"E-{a}-AA" for a in dormitorios}
    # Ojos de buey en las zonas sociales, un foco en cada dormitorio, plafón en el resto.
    assert _luces(r, ids["SALA - COMEDOR"]) >= 13 and _luces(r, ids["COCINA"]) >= 6
    assert all(_luces(r, a) == 1 for a in dormitorios)
    assert _luces(r, ids["PASILLO"]) == 1
    assert not any(c.tipo == "refrigeradora" for c in r.proyecto.cargas_especiales)
    assert not any(p.ambiente == "EXT" for p in r.proyecto.puntos)


def test_basica_es_lo_minimo(opciones: dict[str, Resultado], plano: Plano) -> None:
    r = opciones["basica"]
    assert _aires(r) == set()
    assert r.proyecto.preferencias.iluminacion == "plafon"
    assert _luces(r, _ids(plano)["SALA - COMEDOR"]) == 3
    assert {c.tipo for c in r.proyecto.cargas_especiales} == {"ducha", "cocina"}


def test_confort_lo_completa(opciones: dict[str, Resultado], plano: Plano) -> None:
    r = opciones["confort"]
    ids = _ids(plano)
    assert len(_aires(r)) == 4  # sala y tres dormitorios admiten aire
    assert f"E-{ids['SALA - COMEDOR']}-AA" in _aires(r)
    assert any(c.tipo == "refrigeradora" for c in r.proyecto.cargas_especiales)
    assert any(p.ambiente == "EXT" for p in r.proyecto.puntos)
    # Los dormitorios conservan el gusto del usuario.
    assert _luces(r, ids["DORMITORIO 2"]) == 1


def test_la_carga_crece_de_basica_a_confort(opciones: dict[str, Resultado]) -> None:
    carga = {o: r.calculado.res("RC-01", PROYECTO).decimal for o, r in opciones.items()}
    assert carga["basica"] < carga["recomendada"] < carga["confort"]
    assert opciones["basica"].calculado.res("RC-05", PROYECTO).valor == "Tipo I"
    assert opciones["confort"].calculado.res("RC-05", PROYECTO).valor == "Tipo II"


def test_respuestas_invalidas(plano: Plano, perfil_cnel: Perfil) -> None:
    with pytest.raises(DatoInvalido, match="estilo"):
        preferencias_para("recomendada", Respuestas(iluminacion="neon"), plano, perfil_cnel)
    with pytest.raises(DatoInvalido, match="equipo especial"):
        preferencias_para("basica", Respuestas(equipos=("punto_luz",)), plano, perfil_cnel)
