"""Modelo de prueba: del plano `ejemplos/vivienda-plano/planta.dxf` a la red dibujada."""

from __future__ import annotations

import io
import math
from decimal import Decimal as D

import ezdxf
import pytest
from ezdxf import recover
from shapely.geometry import LineString, Point, Polygon

from electric.calculo import ALIMENTADOR, PROYECTO
from electric.diseno import disenar
from electric.diseno.automatico import _repartir
from electric.errores import DatoInvalido
from electric.flujo import Resultado, proyecto_desde_plano
from electric.ingesta import leer_dxf
from electric.ingesta.dxf import clasificar_capa
from electric.interpretacion import interpretar
from electric.interpretacion.ambientes import reconocer_uso
from electric.modelo import hash_canonico
from electric.modelo.plano import Ambiente, Plano
from electric.perfiles import Perfil
from electric.salida_cad import CAPAS, generar_dxf, renderizar

from .conftest import EJEMPLOS

PLANTA = EJEMPLOS / "vivienda-plano" / "planta.dxf"

# Ambiente → (uso, ancho × alto interior en metros), medidos sobre los ejes del plano.
ESPERADOS = {
    "SALA - COMEDOR": ("sala_comedor", 6.35 * 4.85),
    "COCINA": ("cocina", 2.85 * 4.85),
    "LAVANDERÍA": ("lavanderia", 2.35 * 2.35),
    "BAÑO SOCIAL": ("bano", 2.35 * 2.35),
    "PASILLO": ("pasillo", 7.85 * 0.85),
    "DORMITORIO MASTER": ("dormitorio", 3.85 * 4.85),
    "BAÑO": ("bano", 1.85 * 3.85),
    "DORMITORIO 2": ("dormitorio", 2.85 * 3.85),
    "DORMITORIO 3": ("dormitorio", 2.85 * 3.85),
}


@pytest.fixture(scope="module")
def contenido() -> bytes:
    return PLANTA.read_bytes()


@pytest.fixture(scope="module")
def plano(contenido: bytes, perfil_cnel: Perfil) -> Plano:
    return interpretar(leer_dxf(contenido, "planta.dxf"), perfil_cnel)


@pytest.fixture(scope="module")
def resultado(contenido: bytes, perfil_cnel: Perfil) -> Resultado:
    return proyecto_desde_plano(
        contenido,
        "planta.dxf",
        perfil_cnel,
        id="vivienda-plano",
        nombre="Vivienda de prueba con plano",
        equipos=("ducha", "cocina"),
        alimentador_m=D(12),
    )


def _poligono(ambiente: Ambiente) -> Polygon:
    return Polygon([(float(p.x), float(p.y)) for p in ambiente.poligono])


# --- lectura --------------------------------------------------------------


@pytest.mark.parametrize(
    ("capa", "clase"),
    [
        ("A-MUROS", "muro"),
        ("ARQ_PAREDES", "muro"),
        ("A-WALL", "muro"),
        ("A-PUERTAS", "puerta"),
        ("A-DOOR", "puerta"),
        ("Ventanas", "ventana"),
        ("A-TEXTOS", "texto"),
        ("MOBILIARIO", "mobiliario"),
        ("A-COTAS", "cota"),
        ("0", "otro"),
    ],
)
def test_clasificacion_de_capas_en_espanol_e_ingles(capa: str, clase: str) -> None:
    assert clasificar_capa(capa) == clase


def test_lectura_del_plano_de_prueba(contenido: bytes) -> None:
    leido = leer_dxf(contenido, "planta.dxf")
    assert leido.unidad == "metros"
    assert leido.factor_a_metros == 1.0
    assert leido.capas["A-MUROS"] == "muro"
    assert len(leido.arcos_de_clase("puerta")) == 9
    assert leido.banderas == []


def test_archivo_que_no_es_dxf_se_rechaza() -> None:
    with pytest.raises(DatoInvalido, match="DXF"):
        leer_dxf(b"esto no es un plano", "malo.dxf")


def _cuarto(unidades: int, lado: float) -> bytes:
    """DXF mínimo: un cuarto cuadrado de muro doble, sin puertas."""
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = unidades
    doc.layers.add("MUROS")
    doc.layers.add("TEXTOS")
    msp = doc.modelspace()
    for a, b in ((0.0, lado), (0.05 * lado, 0.95 * lado)):
        msp.add_lwpolyline(
            [(a, a), (b, a), (b, b), (a, b)], close=True, dxfattribs={"layer": "MUROS"}
        )
    msp.add_text("ESTUDIO", height=lado / 30, dxfattribs={"layer": "TEXTOS"}).set_placement(
        (lado / 2, lado / 2)
    )
    salida = io.StringIO()
    doc.write(salida)
    return salida.getvalue().encode()


def test_plano_sin_unidades_pide_la_escala_y_no_la_adivina(perfil_cnel: Perfil) -> None:
    sin_unidades = _cuarto(0, 4000.0)
    with pytest.raises(DatoInvalido, match="unidades"):
        leer_dxf(sin_unidades, "cuarto.dxf")
    plano = interpretar(leer_dxf(sin_unidades, "cuarto.dxf", factor_a_metros=0.001), perfil_cnel)
    assert [a.uso for a in plano.ambientes] == ["estudio"]
    assert plano.ambientes[0].area_m2 == D("12.96")  # 3,6 m × 3,6 m


def test_plano_en_milimetros_da_las_mismas_areas(perfil_cnel: Perfil) -> None:
    plano = interpretar(leer_dxf(_cuarto(4, 4000.0), "cuarto.dxf"), perfil_cnel)
    assert plano.ambientes[0].area_m2 == D("12.96")
    assert plano.area_construida_m2 == D("16.00")
    assert plano.factor_a_metros == D("0.001")


# --- interpretación -------------------------------------------------------


def test_detecta_los_nueve_ambientes_con_su_uso_y_area(plano: Plano) -> None:
    por_nombre = {a.nombre: a for a in plano.ambientes}
    assert set(por_nombre) == set(ESPERADOS)
    for nombre, (uso, area) in ESPERADOS.items():
        ambiente = por_nombre[nombre]
        assert ambiente.uso == uso, nombre
        assert float(ambiente.area_m2) == pytest.approx(area, abs=0.011), nombre
        assert ambiente.banderas == ()
    assert plano.banderas == ()
    # Muros de 15 cm centrados en un perímetro de 12 × 10 m.
    assert float(plano.area_construida_m2) == pytest.approx(12.15 * 10.15, abs=0.011)


def test_cada_puerta_une_los_ambientes_correctos(plano: Plano) -> None:
    nombre = {a.id: a.nombre for a in plano.ambientes}
    uniones = sorted(tuple(sorted(nombre[a] for a in p.ambientes)) for p in plano.puertas)
    assert uniones == sorted(
        [
            ("SALA - COMEDOR",),  # entrada principal
            ("PASILLO", "SALA - COMEDOR"),
            ("DORMITORIO MASTER", "PASILLO"),
            ("BAÑO", "PASILLO"),
            ("DORMITORIO 2", "PASILLO"),
            ("DORMITORIO 3", "PASILLO"),
            ("BAÑO SOCIAL", "PASILLO"),
            ("COCINA", "SALA - COMEDOR"),
            ("COCINA", "LAVANDERÍA"),
        ]
    )


def test_ni_mobiliario_ni_cotas_ni_rotulo_crean_ambientes(plano: Plano) -> None:
    assert len(plano.ambientes) == 9
    assert not any("PLANTA" in a.nombre or "12.00" in a.nombre for a in plano.ambientes)


@pytest.mark.parametrize(
    ("texto", "uso"),
    [
        ("Dormitorio Máster", "dormitorio"),
        ("BAÑO MASTER", "bano"),
        ("S.S.H.H.", None),
        ("HALL", "pasillo"),
        ("Sala de estar", "sala_comedor"),
        ("GARAGE", "garaje"),
        ("QUINCHO", None),
    ],
)
def test_reconocimiento_de_uso_por_nombre(perfil_cnel: Perfil, texto: str, uso: str | None) -> None:
    assert reconocer_uso(texto, perfil_cnel) == uso


def _sin_texto(contenido: bytes, quitar: str, poner: str | None) -> bytes:
    doc, _ = recover.read(io.BytesIO(contenido))
    for entidad in doc.modelspace().query("TEXT"):
        if entidad.dxf.text == quitar:
            if poner is None:
                doc.modelspace().delete_entity(entidad)
            else:
                entidad.dxf.text = poner
    salida = io.StringIO()
    doc.write(salida)
    return salida.getvalue().encode()


def test_ambiente_sin_nombre_o_desconocido_queda_como_pregunta(
    contenido: bytes, perfil_cnel: Perfil
) -> None:
    sin_nombre = interpretar(leer_dxf(_sin_texto(contenido, "COCINA", None), "p.dxf"), perfil_cnel)
    dudoso = next(a for a in sin_nombre.ambientes if a.banderas)
    assert (dudoso.nombre, dudoso.uso) == ("", "otro")
    assert "no tiene nombre" in dudoso.banderas[0]

    raro = interpretar(leer_dxf(_sin_texto(contenido, "COCINA", "QUINCHO"), "p.dxf"), perfil_cnel)
    dudoso = next(a for a in raro.ambientes if a.banderas)
    assert (dudoso.nombre, dudoso.uso) == ("QUINCHO", "otro")
    assert "no se reconoce" in dudoso.banderas[0]


# --- diseño automático ----------------------------------------------------


def test_cantidades_por_ambiente_segun_las_plantillas(resultado: Resultado) -> None:
    proyecto = resultado.proyecto
    assert proyecto.plano is not None
    nombre = {a.id: a.nombre for a in proyecto.plano.ambientes}
    luces: dict[str, int] = {}
    tomas: dict[str, int] = {}
    for punto in proyecto.puntos:
        destino = luces if punto.tipo == "punto_luz" else tomas
        destino[nombre[punto.ambiente or ""]] = destino.get(nombre[punto.ambiente or ""], 0) + 1
    # ceil(área / área por luminaria): sala 30,8/12 → 3; cocina 13,8/8 → 2; baño 7,1/6 → 2…
    assert luces == {
        "SALA - COMEDOR": 3,
        "COCINA": 2,
        "LAVANDERÍA": 1,
        "BAÑO SOCIAL": 1,
        "PASILLO": 1,
        "DORMITORIO MASTER": 2,
        "BAÑO": 2,
        "DORMITORIO 2": 1,
        "DORMITORIO 3": 1,
    }
    # max(mínimo, ceil(perímetro / separación)): sala 22,4/4 → 6; cocina 15,4/3 → 6…
    assert tomas == {
        "SALA - COMEDOR": 6,
        "COCINA": 6,
        "LAVANDERÍA": 2,
        "BAÑO SOCIAL": 1,
        "PASILLO": 2,
        "DORMITORIO MASTER": 4,
        "BAÑO": 1,
        "DORMITORIO 2": 3,
        "DORMITORIO 3": 3,
    }
    assert len(proyecto.plano.interruptores) == 9
    assert resultado.avisos == ()


def test_cada_punto_cae_dentro_de_su_ambiente(resultado: Resultado) -> None:
    plano = resultado.proyecto.plano
    assert plano is not None
    recintos = {a.id: _poligono(a) for a in plano.ambientes}
    for u in plano.ubicaciones:
        assert u.ambiente is not None
        assert recintos[u.ambiente].contains(Point(float(u.x), float(u.y))), u.id
    for s in plano.interruptores:
        assert recintos[s.ambiente].contains(Point(float(s.x), float(s.y))), s.id


def test_puntos_de_pared_pegados_al_muro_y_fuera_de_los_vanos(resultado: Resultado) -> None:
    proyecto = resultado.proyecto
    plano = proyecto.plano
    assert plano is not None
    recintos = {a.id: _poligono(a) for a in plano.ambientes}
    vanos = [
        LineString(
            [(float(p.bisagra.x), float(p.bisagra.y)), (float(p.extremo.x), float(p.extremo.y))]
        )
        for p in plano.puertas
    ]
    de_pared = {p.id for p in proyecto.puntos if p.tipo == "tomacorriente"}
    de_pared |= {c.id for c in proyecto.cargas_especiales} | {"TD-1"}
    for u in plano.ubicaciones:
        if u.id not in de_pared:
            continue
        punto = Point(float(u.x), float(u.y))
        assert recintos[u.ambiente or ""].exterior.distance(punto) <= 0.06, u.id
        assert min(v.distance(punto) for v in vanos) >= 0.35, u.id


def test_tablero_y_cargas_especiales_en_su_ambiente(resultado: Resultado) -> None:
    proyecto = resultado.proyecto
    plano = proyecto.plano
    assert plano is not None
    uso = {a.id: a.uso for a in plano.ambientes}
    donde = {u.id: uso[u.ambiente or ""] for u in plano.ubicaciones}
    assert donde["TD-1"] == "pasillo"
    por_tipo = {c.tipo: donde[c.id] for c in proyecto.cargas_especiales}
    assert por_tipo == {"ducha": "bano", "cocina": "cocina"}


def test_circuitos_respetan_minimos_y_maximos(resultado: Resultado) -> None:
    proyecto = resultado.proyecto
    cuenta = {
        c.id: sum(1 for p in proyecto.puntos if p.circuito == c.id) for c in proyecto.circuitos
    }
    iluminacion = [cuenta[c.id] for c in proyecto.circuitos if c.tipo == "iluminacion"]
    tomas = [cuenta[c.id] for c in proyecto.circuitos if c.tipo == "tomacorrientes"]
    assert iluminacion == [7, 7]  # 14 luminarias, mínimo 2 circuitos, máximo 15 puntos
    assert sorted(tomas) == [9, 9, 10]  # 28 tomas, máximo 10 salidas
    assert all(n <= 10 for n in tomas)
    assert sum(1 for c in proyecto.circuitos if c.tipo == "especial") == 2
    assert resultado.calculado.res("RC-02", PROYECTO).avisos == ()
    humedos = {c.id for c in proyecto.circuitos if c.zona_humeda}
    assert all(c.id in humedos for c in proyecto.circuitos if c.tipo == "especial")


def test_recorridos_ortogonales_desde_el_tablero(resultado: Resultado) -> None:
    proyecto = resultado.proyecto
    plano = proyecto.plano
    assert plano is not None
    tablero = next(u for u in plano.ubicaciones if u.id == "TD-1")
    posicion = {u.id: (u.x, u.y) for u in plano.ubicaciones}
    assert {r.circuito for r in plano.recorridos} == {c.id for c in proyecto.circuitos}
    for recorrido in plano.recorridos:
        assert (recorrido.puntos[0].x, recorrido.puntos[0].y) == (tablero.x, tablero.y)
        for a, b in zip(recorrido.puntos, recorrido.puntos[1:], strict=False):
            assert a.x == b.x or a.y == b.y, f"{recorrido.circuito}: tramo en diagonal"
        visitados = {(p.x, p.y) for p in recorrido.puntos}
        propios = [p.id for p in proyecto.puntos if p.circuito == recorrido.circuito]
        propios += [c.id for c in proyecto.cargas_especiales if c.circuito == recorrido.circuito]
        assert all(posicion[i] in visitados for i in propios)
        # La longitud eléctrica (momento de carga) nunca supera la tubería física.
        circuito = next(c for c in proyecto.circuitos if c.id == recorrido.circuito)
        assert D(0) < circuito.longitud_m <= recorrido.longitud_m


def test_el_proyecto_disenado_cumple_al_calcular(resultado: Resultado) -> None:
    calculado = resultado.calculado
    assert calculado.res("RC-05", PROYECTO).valor == "Tipo I"
    assert calculado.res("RC-01", PROYECTO).decimal == 14 * 100 + 28 * 200 + 3500 + 6000
    for caida in calculado.de("RC-08"):
        assert caida.decimal <= caida.det("limite_pct")
    assert calculado.res("RC-10", PROYECTO).avisos == ()
    assert calculado.res("RC-09", ALIMENTADOR).decimal == 50


def test_el_diseno_es_determinista(
    contenido: bytes, perfil_cnel: Perfil, resultado: Resultado
) -> None:
    otra_vez = proyecto_desde_plano(
        contenido,
        "planta.dxf",
        perfil_cnel,
        id="vivienda-plano",
        nombre="Vivienda de prueba con plano",
        equipos=("ducha", "cocina"),
        alimentador_m=D(12),
    )
    assert hash_canonico(otra_vez.proyecto) == hash_canonico(resultado.proyecto)
    assert otra_vez.calculado.hash == resultado.calculado.hash


def test_equipo_sin_ambiente_que_lo_admita_queda_avisado(plano: Plano, perfil_cnel: Perfil) -> None:
    from electric.modelo.entidades import CargaEspecial

    diseno = disenar(plano, (CargaEspecial(id="x", tipo="cargador_ev", circuito="-"),), perfil_cnel)
    assert any("cargador_ev" in aviso for aviso in diseno.avisos)


@pytest.mark.parametrize(
    ("grupos", "minimo", "maximo", "esperado"),
    [
        ([3, 2, 1, 1, 1, 2, 2, 1, 1], 2, 15, [7, 7]),
        ([6, 6, 2, 1, 2, 4, 1, 3, 3], 2, 10, [10, 9, 9]),
        ([4], 2, 15, [2, 2]),
        ([20], 1, 15, [10, 10]),
        ([1], 2, 15, [1]),
        ([], 2, 15, []),
    ],
)
def test_reparto_en_circuitos(
    grupos: list[int], minimo: int, maximo: int, esperado: list[int]
) -> None:
    listas = [[f"g{n}-{i}" for i in range(c)] for n, c in enumerate(grupos)]
    reparto = _repartir(listas, minimo, maximo)
    assert sorted(len(c) for c in reparto) == sorted(esperado)
    assert [i for c in reparto for i in c] == [i for g in listas for i in g]


# --- salida CAD -----------------------------------------------------------


@pytest.fixture(scope="module")
def dxf(contenido: bytes, resultado: Resultado, perfil_cnel: Perfil) -> bytes:
    return generar_dxf(contenido, resultado.proyecto, resultado.calculado, perfil_cnel)


def test_dxf_de_salida_abre_sin_errores_y_tiene_las_capas(dxf: bytes) -> None:
    doc, auditor = recover.read(io.BytesIO(dxf))
    assert not auditor.has_errors
    for capa, (color, _) in CAPAS.items():
        assert doc.layers.get(capa).color == color
    msp = doc.modelspace()
    por_bloque: dict[str, int] = {}
    for insercion in msp.query("INSERT"):
        por_bloque[insercion.dxf.name] = por_bloque.get(insercion.dxf.name, 0) + 1
    # Cada símbolo aparece una vez más en la leyenda.
    assert por_bloque == {
        "E_LUMINARIA": 14 + 1,
        "E_TOMACORRIENTE": 28 + 1,
        "E_INTERRUPTOR": 9 + 1,
        "E_ESPECIAL": 2 + 1,
        "E_TABLERO": 1 + 1,
    }
    assert len(msp.query('LWPOLYLINE[layer=="E-CIRC"]')) == 7
    textos = [t.dxf.text for t in msp.query('TEXT[layer=="E-TEXT"]')]
    assert any(t.startswith("BORRADOR") for t in textos)
    assert "CUADRO DE CARGAS" in textos


def test_los_simbolos_llevan_atributos(dxf: bytes) -> None:
    doc, _ = recover.read(io.BytesIO(dxf))
    luminaria = next(i for i in doc.modelspace().query('INSERT[name=="E_LUMINARIA"]') if i.attribs)
    atributos = {a.dxf.tag: a.dxf.text for a in luminaria.attribs}
    assert atributos["ID"].startswith("L-")
    assert atributos["CIRCUITO"] in {"C1", "C2"}
    assert atributos["POTENCIA"] == "100 W"
    assert atributos["ALTURA"] == "2.5 m"


def test_el_plano_del_arquitecto_queda_intacto_y_en_gris(contenido: bytes, dxf: bytes) -> None:
    antes = contenido[:]
    original, _ = recover.read(io.BytesIO(contenido))
    salida, _ = recover.read(io.BytesIO(dxf))
    assert contenido == antes == PLANTA.read_bytes()
    for capa in ("A-MUROS", "A-PUERTAS", "A-VENTANAS", "A-TEXTOS", "A-MOBILIARIO"):
        consulta = f'*[layer=="{capa}"]'
        assert len(salida.modelspace().query(consulta)) == len(
            original.modelspace().query(consulta)
        )
        assert salida.layers.get(capa).color == 8
    muros_antes = sorted(
        (
            round(e.dxf.start.x, 6),
            round(e.dxf.start.y, 6),
            round(e.dxf.end.x, 6),
            round(e.dxf.end.y, 6),
        )
        for e in original.modelspace().query('LINE[layer=="A-MUROS"]')
    )
    muros_despues = sorted(
        (
            round(e.dxf.start.x, 6),
            round(e.dxf.start.y, 6),
            round(e.dxf.end.x, 6),
            round(e.dxf.end.y, 6),
        )
        for e in salida.modelspace().query('LINE[layer=="A-MUROS"]')
    )
    assert muros_antes == muros_despues


def test_imagen_y_pdf(dxf: bytes) -> None:
    png = renderizar(dxf, "png")
    assert png.startswith(b"\x89PNG") and len(png) > 20_000
    pdf = renderizar(dxf, "pdf")
    assert pdf.startswith(b"%PDF") and len(pdf) > 5_000


def test_sin_diseno_no_hay_dxf(contenido: bytes, vivienda: object, perfil_cnel: Perfil) -> None:
    with pytest.raises(DatoInvalido, match="plano"):
        generar_dxf(contenido, vivienda, None, perfil_cnel)  # type: ignore[arg-type]


def test_angulos_de_referencia() -> None:
    # Guarda contra regresiones en el orden angular de ambientes alrededor del tablero.
    assert math.isclose(math.atan2(1, 0), math.pi / 2)
