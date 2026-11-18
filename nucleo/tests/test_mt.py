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


def test_consulta_al_geoportal_sin_url_configurada(perfil_cnel: Perfil) -> None:
    capa = perfil_cnel.capas_sig()[0]
    with pytest.raises(ErrorSIG, match="URL"):
        url_consulta(capa, D("-2.17"), D("-79.9"), 300)
    with pytest.raises(ErrorSIG):
        consultar_geoportal(perfil_cnel, D("-2.17"), D("-79.9"))
    con_url = capa.model_copy(update={"url": "https://ejemplo.invalido/arcgis/rest/services/x/0"})
    url = url_consulta(con_url, D("-2.17"), D("-79.9"), 250)
    assert url.startswith("https://ejemplo.invalido/arcgis/rest/services/x/0/query?")
    assert "distance=250" in url and "outSR=4326" in url
