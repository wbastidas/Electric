"""Redes de media tensión: extensión de red, red existente del SIG y planos."""

from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from electric.mt import (
    ErrorSIG,
    ExtensionMT,
    calcular_red,
    consultar_geoportal,
    generar_kml,
    generar_planimetria,
    generar_unifilar_mt,
    leer_geojson,
)
from electric.mt.calculo import proyectar
from electric.mt.sig import leer_featureset, url_consulta
from electric.perfiles import Perfil

EJEMPLO = Path(__file__).resolve().parents[2] / "ejemplos" / "red-mt" / "extension.json"


@pytest.fixture(scope="module")
def extension() -> ExtensionMT:
    return ExtensionMT.model_validate(json.loads(EJEMPLO.read_text(encoding="utf-8")))


def test_proyeccion_local() -> None:
    x, y = proyectar(D("-2.17"), D("-79.8996"), D("-2.17"), D("-79.9"))
    assert abs(x - 44.5) < 0.5 and abs(y) < 1e-6


def test_vanos_y_estructuras(extension: ExtensionMT, perfil_cnel: Perfil) -> None:
    red = calcular_red(extension, perfil_cnel)
    assert len(red.vanos) == len(extension.postes)
    assert all(not v.excede for v in red.vanos)
    assert red.longitud_m == sum(v.longitud_m for v in red.vanos)
    tipos = [p.estructura for p in red.postes]
    assert tipos[0] == "pasante" and tipos[-1] == "terminal"
    assert tipos[2] == "retencion_angular"  # giro de unos 54°
    assert red.arranque.estructura == "arranque"


def test_caida_por_momento_electrico(perfil_cnel: Perfil) -> None:
    # 1 km recto con 500 kVA al final: 500 × 0,8 × 1 × (0,536 × 0,9 + 0,45 × 0,436) ÷ (10 × 13,8²).
    datos = {
        "nombre": "Prueba",
        "conductor": "ACSR 1/0 AWG",
        "zona": "rural",
        "arranque": {"lat": "0", "lon": "0"},
        "postes": [
            {"id": f"P{n}", "lat": "0", "lon": str(round(n * 0.0009, 6))} for n in range(1, 11)
        ],
    }
    datos["postes"][-1]["transformador_kva"] = "500"
    red = calcular_red(ExtensionMT.model_validate(datos), perfil_cnel)
    km = red.longitud_m / 1000
    esperado = (
        D(400)
        * km
        * (D("0.536") * D("0.9") + D("0.45") * (1 - D("0.81")).sqrt())
        / (10 * D("13.8") ** 2)
    )
    assert abs(red.caida_pct - esperado) < D("0.0001")
    assert red.vanos[0].carga_kva == D(400)
    assert red.postes[-1].fusible is not None
    assert red.fusible_derivacion is not None


def test_vano_largo_y_retencion_en_alineacion(perfil_cnel: Perfil) -> None:
    postes = [{"id": f"P{n}", "lat": "0", "lon": str(round(n * 0.0003, 6))} for n in range(1, 14)]
    postes.append({"id": "LEJOS", "lat": "0", "lon": "0.0060"})
    red = calcular_red(
        ExtensionMT.model_validate(
            {"nombre": "X", "arranque": {"lat": "0", "lon": "0"}, "postes": postes}
        ),
        perfil_cnel,
    )
    assert red.vanos[-1].excede
    assert any("vano" in a for a in red.avisos)
    assert "retencion" in [p.estructura for p in red.postes]


def test_cortocircuito_y_capacidad_del_seccionador(
    extension: ExtensionMT, perfil_cnel: Perfil
) -> None:
    red = calcular_red(extension, perfil_cnel)
    # 250 MVA a 13,8 kV con c = 1,1: 1,1 × 250 ÷ (√3 × 13,8) ≈ 11,5 kA.
    assert abs(red.ik_arranque_ka - D("11.505")) < D("0.01")
    assert red.ik_final_ka < red.ik_arranque_ka
    assert any("seccionador" in a for a in red.avisos)
    menor = extension.model_copy(
        update={"arranque": extension.arranque.model_copy(update={"scc_mva": D(150)})}
    )
    assert not any("seccionador" in a for a in calcular_red(menor, perfil_cnel).avisos)


def test_salidas(extension: ExtensionMT, perfil_cnel: Perfil) -> None:
    red = calcular_red(extension, perfil_cnel)
    plano = generar_planimetria(red).decode("utf-8", errors="replace")
    assert "TABLA DE ESTRUCTURAS" in plano and "PN-8" in plano
    assert "SECCIONADOR FUSIBLE" in generar_unifilar_mt(red).decode("utf-8", errors="replace")
    kml = generar_kml(red).decode("utf-8")
    assert kml.count("<Placemark>") == len(extension.postes) + 2
    assert "<LineString>" in kml


# --- SIG -------------------------------------------------------------------------------


def test_geojson_de_red_existente(perfil_cnel: Perfil, extension: ExtensionMT) -> None:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"capa": "postes", "CODIGO": "P-EX-12", "ESTRUCTURA": "X1"},
                "geometry": {"type": "Point", "coordinates": [-79.9, -2.17]},
            },
            {
                "type": "Feature",
                "properties": {"CODIGO": "T1", "CONDUCTOR": "ACSR 2/0", "FASES": "ABC"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-79.901, -2.17], [-79.9, -2.17]],
                },
            },
            {
                "type": "Feature",
                "properties": {"capa": "transformadores", "CODIGO": "TR-9", "POTENCIA": 50},
                "geometry": {"type": "Point", "coordinates": [-79.9005, -2.1702]},
            },
            {"type": "Feature", "properties": {"capa": "postes"}, "geometry": None},
        ],
    }
    red, avisos = leer_geojson(json.dumps(geojson).encode(), perfil_cnel)
    assert [p.id for p in red.postes] == ["P-EX-12"]
    assert red.postes[0].estructura == "X1"
    assert red.tramos[0].conductor == "ACSR 2/0" and len(red.tramos[0].puntos) == 2
    assert red.transformadores[0].kva == D(50)
    assert avisos and "omitieron" in avisos[0]
    plano = generar_planimetria(calcular_red(extension, perfil_cnel), red)
    assert b"P-EX-12" in plano


def test_featureset_de_arcgis() -> None:
    texto = json.dumps(
        {"features": [{"attributes": {"codigo": "A"}, "geometry": {"x": -79.9, "y": -2.17}}]}
    )
    assert leer_featureset(texto) == [({"codigo": "A"}, {"x": -79.9, "y": -2.17})]
    with pytest.raises(ErrorSIG, match="error"):
        leer_featureset(json.dumps({"error": {"code": 400}}))


def _servicio_simulado(llamadas: list[str]):  # type: ignore[no-untyped-def]
    """Respuestas con la forma de ArcGIS REST para probar la lógica (no son datos de CNEL)."""
    base = "https://geoportal.cnelep.gob.ec/arcgis/rest/services/REP/CNELEPN/MapServer"
    capas = {
        "layers": [
            {"id": 3, "name": "Postes"},
            {"id": 5, "name": "Red Baja Tensión"},
            {"id": 6, "name": "Red Media Tensión"},
            {"id": 9, "name": "Transformadores"},
            {"id": 11, "name": "Seccionadores"},
        ]
    }
    campos = {
        3: [{"name": "COD_POSTE"}, {"name": "ARMADO", "alias": "Estructura"}, {"name": "ALIM"}],
        6: [{"name": "OBJECTID"}, {"name": "CALIBRE"}, {"name": "FASE"}],
        9: [{"name": "CODIGO"}, {"name": "KVA"}, {"name": "NUM_CLIENTES"}],
        11: [{"name": "CODIGO"}, {"name": "TIPO"}],
    }
    rasgos = {
        3: [
            {
                "attributes": {"COD_POSTE": "P-1", "ARMADO": "UP-1"},
                "geometry": {"x": -79.9, "y": -2.17},
            }
        ],
        6: [
            {
                "attributes": {"OBJECTID": 7, "CALIBRE": "2/0"},
                "geometry": {"paths": [[[-79.9, -2.17], [-79.899, -2.17]]]},
            }
        ],
        9: [
            {"attributes": {"CODIGO": "TR-1", "KVA": 50}, "geometry": {"x": -79.8995, "y": -2.1701}}
        ],
        11: [],
    }

    def leer(url: str) -> str:
        llamadas.append(url)
        if url == f"{base}?f=json":
            return json.dumps(capas)
        numero = int(url.split("MapServer/")[1].split("/")[0].split("?")[0])
        if "/query?" in url:
            return json.dumps({"features": rasgos[numero]})
        return json.dumps({"name": next(c["name"] for c in capas["layers"] if c["id"] == numero),
                           "fields": campos[numero]})  # fmt: skip

    return leer


def test_reconoce_capas_y_campos_del_servicio(perfil_cnel: Perfil) -> None:
    from electric.mt.sig import descubrir

    llamadas: list[str] = []
    hallazgo = descubrir(perfil_cnel, _servicio_simulado(llamadas))
    capas = {c.capa: c for c in hallazgo.capas}
    assert capas["transformadores"].url and capas["transformadores"].url.endswith("/9")
    assert capas["postes"].url and capas["postes"].url.endswith("/3")
    # La de baja tensión no se toma como red de media tensión.
    assert capas["tramos_mt"].nombre == "Red Media Tensión"
    assert capas["protecciones"].nombre == "Seccionadores"
    assert capas["postes"].campos["id"] == "COD_POSTE"
    assert capas["postes"].campos["estructura"] == "ARMADO"
    assert capas["transformadores"].campos["kva"] == "KVA"
    assert capas["transformadores"].campos["clientes"] == "NUM_CLIENTES"
    assert any("no se encontraron los campos" in a for a in hallazgo.avisos)


def test_consulta_con_el_servicio_simulado(perfil_cnel: Perfil) -> None:
    llamadas: list[str] = []
    red, _ = consultar_geoportal(
        perfil_cnel, D("-2.17"), D("-79.9"), 250, leer=_servicio_simulado(llamadas)
    )
    assert [p.id for p in red.postes] == ["P-1"] and red.postes[0].estructura == "UP-1"
    assert red.tramos[0].conductor == "2/0"
    assert red.transformadores[0].kva == D(50)
    assert any("/9/query?" in u and "distance=250" in u for u in llamadas)


def test_geoportal_que_no_responde(perfil_cnel: Perfil) -> None:
    def caido(url: str) -> str:
        raise ErrorSIG("no se pudo conectar con el geoportal: rechazado")

    with pytest.raises(ErrorSIG, match="conectar"):
        consultar_geoportal(perfil_cnel, D("-2.17"), D("-79.9"), leer=caido)
    capa = perfil_cnel.capas_sig()[0]
    with pytest.raises(ErrorSIG, match="URL"):
        url_consulta(capa, D("-2.17"), D("-79.9"), 300)
