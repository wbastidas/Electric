"""Preferencias de diseño sobre el modelo de prueba: estilos, aire, refrigeradora y exteriores."""

from __future__ import annotations

import math
from decimal import Decimal as D

import pytest
from shapely.geometry import Point, Polygon

from electric.calculo import PROYECTO
from electric.diseno import Mover, disenar, editar, retrazar
from electric.diseno.automatico import EXTERIOR, huella
from electric.errores import DatoInvalido
from electric.flujo import Resultado, proyecto_desde_plano
from electric.ingesta import leer_dxf
from electric.interpretacion import interpretar
from electric.modelo import PreferenciaAmbiente, Preferencias, Proyecto, hash_canonico
from electric.modelo.plano import Plano
from electric.perfiles import Perfil

from .conftest import EJEMPLOS

PLANTA = EJEMPLOS / "vivienda-plano" / "planta.dxf"


@pytest.fixture(scope="module")
def plano(perfil_cnel: Perfil) -> Plano:
    return interpretar(leer_dxf(PLANTA.read_bytes(), "planta.dxf"), perfil_cnel)


def _disenar(perfil: Perfil, preferencias: Preferencias) -> Resultado:
    return proyecto_desde_plano(
        PLANTA.read_bytes(),
        "planta.dxf",
        perfil,
        id="escenario",
        nombre="Escenario",
        equipos=("ducha", "cocina"),
        alimentador_m=D(12),
        preferencias=preferencias,
    )


@pytest.fixture(scope="module")
def base(perfil_cnel: Perfil) -> Resultado:
    return _disenar(perfil_cnel, Preferencias())


@pytest.fixture(scope="module")
def costa(perfil_cnel: Perfil) -> Resultado:
    return _disenar(perfil_cnel, Preferencias(zona_climatica="costa"))


def _ambientes(proyecto: Proyecto) -> dict[str, str]:
    assert proyecto.plano is not None
    return {a.nombre: a.id for a in proyecto.plano.ambientes}


def _poligono(proyecto: Proyecto, aid: str) -> Polygon:
    assert proyecto.plano is not None
    ambiente = next(a for a in proyecto.plano.ambientes if a.id == aid)
    return Polygon([(float(p.x), float(p.y)) for p in ambiente.poligono])


def _luces(proyecto: Proyecto, aid: str) -> list[str]:
    return [p.id for p in proyecto.puntos if p.ambiente == aid and p.tipo == "punto_luz"]


def _lugar(proyecto: Proyecto, id: str) -> tuple[float, float]:
    assert proyecto.plano is not None
    u = next(u for u in proyecto.plano.ubicaciones if u.id == id)
    return (float(u.x), float(u.y))


# --- exteriores y refrigeradora --------------------------------------------


def test_luces_y_tomas_exteriores_en_la_fachada(base: Resultado, perfil_cnel: Perfil) -> None:
    proyecto = base.proyecto
    assert proyecto.plano is not None
    contorno = huella(proyecto.plano, float(perfil_cnel.parametro("muro_exterior_m")[0]))
    luces = [p for p in proyecto.puntos if p.ambiente == EXTERIOR and p.tipo == "punto_luz"]
    tomas = [p for p in proyecto.puntos if p.ambiente == EXTERIOR and p.tipo == "tomacorriente"]
    puertas_afuera = [d for d in proyecto.plano.puertas if len(d.ambientes) == 1]
    assert puertas_afuera, "el plano de prueba tiene puertas a la calle"
    assert len(tomas) == len(puertas_afuera)
    # Una luz por puerta exterior más las de fachada, cada 6 m como mucho.
    perimetro = contorno.exterior.length
    assert len(luces) >= max(len(puertas_afuera), math.floor(perimetro / 6))
    for punto in luces + tomas:
        lugar = Point(_lugar(proyecto, punto.id))
        assert not contorno.covers(lugar), punto.id
        assert contorno.distance(lugar) <= 0.06, punto.id

    # Van en circuitos propios: la iluminación de fachada y los tomas de intemperie (diferencial).
    circuito_luces = {p.circuito for p in luces}
    circuito_tomas = {p.circuito for p in tomas}
    assert len(circuito_luces) == 1 and len(circuito_tomas) == 1
    assert {p.ambiente for p in proyecto.puntos if p.circuito in circuito_luces} == {EXTERIOR}
    tomas_circuito = next(c for c in proyecto.circuitos if c.id in circuito_tomas)
    assert tomas_circuito.zona_humeda
    interruptor = next(s for s in proyecto.plano.interruptores if s.ambiente == EXTERIOR)
    assert interruptor.circuito in circuito_luces
    assert any(
        _poligono(proyecto, a.id).contains(Point(float(interruptor.x), float(interruptor.y)))
        for a in proyecto.plano.ambientes
    ), "el interruptor de fachada va dentro de la casa"


def test_refrigeradora_con_circuito_propio_en_la_cocina(base: Resultado) -> None:
    proyecto = base.proyecto
    cocina = _ambientes(proyecto)["COCINA"]
    refri = next(c for c in proyecto.cargas_especiales if c.tipo == "refrigeradora")
    assert refri.id == f"E-{cocina}-REF" and refri.origen == "auto"
    assert _poligono(proyecto, cocina).contains(Point(_lugar(proyecto, refri.id)))
    circuito = next(c for c in proyecto.circuitos if c.id == refri.circuito)
    assert circuito.tipo == "especial"
    assert base.calculado.res("RC-01", refri.circuito).decimal == 400


def test_sin_exteriores_ni_refrigeradora(perfil_cnel: Perfil, base: Resultado) -> None:
    sin = _disenar(perfil_cnel, Preferencias(exteriores=False, refrigeradora=False)).proyecto
    assert not any(p.ambiente == EXTERIOR for p in sin.puntos)
    assert not any(c.tipo == "refrigeradora" for c in sin.cargas_especiales)
    assert len(sin.circuitos) == len(base.proyecto.circuitos) - 3


# --- aire acondicionado por zona climática -----------------------------------


def test_costa_pone_aire_en_dormitorios_y_sala(costa: Resultado, base: Resultado) -> None:
    proyecto = costa.proyecto
    ids = _ambientes(proyecto)
    aires = {c.id: c for c in proyecto.cargas_especiales if c.tipo == "aire_acondicionado"}
    esperados = {
        f"E-{ids[n]}-AA"
        for n in ("SALA - COMEDOR", "DORMITORIO MASTER", "DORMITORIO 2", "DORMITORIO 3")
    }
    assert set(aires) == esperados
    assert not any(c.tipo == "aire_acondicionado" for c in base.proyecto.cargas_especiales)

    # Sala de 30,8 m² × 600 BTU/m² = 18 480 BTU → equipo de 24 000 BTU, 2 400 W, entre líneas.
    sala = aires[f"E-{ids['SALA - COMEDOR']}-AA"]
    assert sala.potencia_w == 2500  # nunca menos que el aire de la tabla de cargas
    assert sala.conexion == "linea"
    assert sala.nota is not None and sala.nota.startswith("24000 BTU")
    dormitorio = aires[f"E-{ids['DORMITORIO 2']}-AA"]
    assert dormitorio.nota is not None and dormitorio.nota.startswith("9000 BTU")
    assert _poligono(proyecto, ids["DORMITORIO 2"]).contains(Point(_lugar(proyecto, dormitorio.id)))

    # Cuatro aires más llevan la vivienda a Tipo II.
    assert (
        costa.calculado.res("RC-01", PROYECTO).decimal
        > base.calculado.res("RC-01", PROYECTO).decimal + 4 * 2400
    )
    assert costa.calculado.res("RC-05", PROYECTO).valor == "Tipo II"


def test_sierra_no_pone_aire_salvo_que_se_pida(perfil_cnel: Perfil, plano: Plano) -> None:
    ids = {a.nombre: a.id for a in plano.ambientes}
    sierra = _disenar(perfil_cnel, Preferencias(zona_climatica="sierra")).proyecto
    assert not any(c.tipo == "aire_acondicionado" for c in sierra.cargas_especiales)

    pedido = Preferencias(
        zona_climatica="sierra",
        ambientes={ids["DORMITORIO MASTER"]: PreferenciaAmbiente(aire=True)},
    )
    con_uno = _disenar(perfil_cnel, pedido).proyecto
    assert [c.id for c in con_uno.cargas_especiales if c.tipo == "aire_acondicionado"] == [
        f"E-{ids['DORMITORIO MASTER']}-AA"
    ]

    quitado = Preferencias(
        zona_climatica="costa", ambientes={ids["SALA - COMEDOR"]: PreferenciaAmbiente(aire=False)}
    )
    sin_sala = _disenar(perfil_cnel, quitado).proyecto
    aires = [c.id for c in sin_sala.cargas_especiales if c.tipo == "aire_acondicionado"]
    assert len(aires) == 3 and f"E-{ids['SALA - COMEDOR']}-AA" not in aires


# --- estilos de iluminación y tomas ----------------------------------------


def test_ojos_de_buey_en_cuadricula(perfil_cnel: Perfil, base: Resultado) -> None:
    resultado = _disenar(perfil_cnel, Preferencias(iluminacion="ojos_de_buey"))
    proyecto = resultado.proyecto
    ids = _ambientes(proyecto)
    sala = _luces(proyecto, ids["SALA - COMEDOR"])
    assert len(sala) >= math.ceil(30.8 / 2.5)
    poligono = _poligono(proyecto, ids["SALA - COMEDOR"])
    lugares = [_lugar(proyecto, i) for i in sala]
    assert all(poligono.contains(Point(p)) for p in lugares)
    assert (
        len({round(x, 2) for x, _ in lugares}) >= 3 and len({round(y, 2) for _, y in lugares}) >= 2
    )
    # Cada empotrado cuenta con la potencia por punto de CNEL: más puntos, más carga y circuitos.
    maximo = int(perfil_cnel.parametro("puntos_max_iluminacion")[0])
    for c in proyecto.circuitos:
        if c.tipo == "iluminacion":
            assert sum(1 for p in proyecto.puntos if p.circuito == c.id) <= maximo
    assert len(proyecto.puntos) > len(base.proyecto.puntos)
    assert (
        resultado.calculado.res("RC-01", PROYECTO).decimal
        > base.calculado.res("RC-01", PROYECTO).decimal
    )


def test_foco_central_y_cambio_por_ambiente(perfil_cnel: Perfil, plano: Plano) -> None:
    ids = {a.nombre: a.id for a in plano.ambientes}
    preferencias = Preferencias(
        iluminacion="foco_central",
        exteriores=False,
        ambientes={ids["SALA - COMEDOR"]: PreferenciaAmbiente(iluminacion="ojos_de_buey")},
    )
    proyecto = _disenar(perfil_cnel, preferencias).proyecto
    for nombre, aid in ids.items():
        luces = _luces(proyecto, aid)
        if nombre == "SALA - COMEDOR":
            assert len(luces) >= 13
        else:
            assert len(luces) == 1, nombre


def test_tomas_en_los_extremos_de_las_paredes(perfil_cnel: Perfil, base: Resultado) -> None:
    proyecto = base.proyecto
    aid = _ambientes(proyecto)["DORMITORIO MASTER"]
    poligono = _poligono(proyecto, aid)
    esquinas = list(poligono.exterior.coords)
    tomas = [p.id for p in proyecto.puntos if p.ambiente == aid and p.tipo == "tomacorriente"]
    assert len(tomas) >= 2
    for t in tomas:
        lugar = _lugar(proyecto, t)
        assert min(math.dist(lugar, e) for e in esquinas) <= 0.8, t

    repartidos = Preferencias(ambientes={aid: PreferenciaAmbiente(tomas="perimetro")})
    otro = _disenar(perfil_cnel, repartidos).proyecto
    assert {_lugar(otro, t) for t in tomas} != {_lugar(proyecto, t) for t in tomas}


def test_estilo_desconocido_se_rechaza(perfil_cnel: Perfil, plano: Plano) -> None:
    with pytest.raises(DatoInvalido, match="estilo"):
        disenar(plano, (), perfil_cnel, Preferencias(iluminacion="neon"))


# --- coherencia con la edición y el rediseño --------------------------------


def test_redisenar_regenera_las_cargas_propuestas_sin_duplicarlas(
    costa: Resultado, perfil_cnel: Perfil
) -> None:
    proyecto = costa.proyecto
    assert proyecto.plano is not None
    otra_vez = disenar(
        proyecto.plano, proyecto.cargas_especiales, perfil_cnel, proyecto.preferencias
    )
    assert [c.id for c in otra_vez.cargas_especiales] == [c.id for c in proyecto.cargas_especiales]
    assert hash_canonico(retrazar(proyecto, perfil_cnel)) == hash_canonico(proyecto)


def test_mover_un_punto_afuera_lo_vuelve_exterior(base: Resultado, perfil_cnel: Perfil) -> None:
    proyecto = base.proyecto
    assert proyecto.plano is not None
    toma = next(p for p in proyecto.puntos if p.ambiente != EXTERIOR and p.tipo == "tomacorriente")
    contorno = huella(proyecto.plano, 0.2)
    xmin, ymin, _, _ = contorno.bounds
    editado = editar(
        proyecto,
        [Mover(id=toma.id, x=D(str(round(xmin - 1, 2))), y=D(str(round(ymin + 2, 2))))],
        perfil_cnel,
    ).proyecto
    assert next(p for p in editado.puntos if p.id == toma.id).ambiente == EXTERIOR

    # Entre dos ambientes (sobre el muro) no se puede.
    ids = _ambientes(proyecto)
    a, b = _poligono(proyecto, ids["COCINA"]), _poligono(proyecto, ids["SALA - COMEDOR"])
    muro = a.buffer(0.1).intersection(b.buffer(0.1)).representative_point()
    with pytest.raises(DatoInvalido, match="muro"):
        editar(
            proyecto,
            [Mover(id=toma.id, x=D(str(round(muro.x, 3))), y=D(str(round(muro.y, 3))))],
            perfil_cnel,
        )
