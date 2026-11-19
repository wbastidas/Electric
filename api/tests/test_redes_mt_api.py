from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from electric_api.app import crear_app
from electric_api.config import Config

RAIZ = Path(__file__).resolve().parents[2]
BASE = "/api/v1"


@pytest.fixture
def cliente(tmp_path: Path) -> Iterator[TestClient]:
    config = Config(
        base_de_datos="sqlite:///:memory:", perfiles=RAIZ / "perfiles", web=tmp_path / "sin-web"
    )
    with TestClient(crear_app(config)) as cliente:
        yield cliente


def test_red_mt_paso_a_paso(cliente: TestClient) -> None:
    opciones = cliente.get(f"{BASE}/red-mt/opciones").json()
    assert "ACSR 1/0 AWG" in {c["id"] for c in opciones["conductores"]}
    assert opciones["geoportal_configurado"] is True

    red = cliente.post(f"{BASE}/redes-mt", json={"nombre": "Extensión barrio norte"}).json()
    id = red["id"]
    calculo = cliente.get(f"{BASE}/redes-mt/{id}/calculo").json()
    assert calculo["estado"] == "incompleto" and len(calculo["pendientes"]) == 2
    assert cliente.get(f"{BASE}/redes-mt/{id}/planimetria.png").status_code == 422

    datos = red["datos"]
    datos["arranque"] = {"lat": -2.17, "lon": -79.9, "alimentador": "A1"}
    datos["postes"] = [
        {"id": "P1", "lat": -2.17, "lon": -79.89966},
        {"id": "P2", "lat": -2.17, "lon": -79.89932, "transformador_kva": 50},
    ]
    guardada = cliente.put(f"{BASE}/redes-mt/{id}", json={"revision": 1, "datos": datos})
    assert guardada.status_code == 200, guardada.text
    calculo = cliente.get(f"{BASE}/redes-mt/{id}/calculo").json()
    assert calculo["estado"] == "listo", calculo
    assert [p["estructura"] for p in calculo["postes"]] == ["pasante", "terminal"]
    assert calculo["fusible_derivacion"] and 70 < calculo["longitud_m"] < 80
    for plano in ("planimetria", "unifilar"):
        for formato, inicio in (("dxf", b"  0"), ("png", b"\x89PNG"), ("pdf", b"%PDF")):
            respuesta = cliente.get(f"{BASE}/redes-mt/{id}/{plano}.{formato}")
            assert respuesta.status_code == 200, respuesta.text
            assert respuesta.content.startswith(inicio)
    kml = cliente.get(f"{BASE}/redes-mt/{id}/red.kml")
    assert kml.status_code == 200 and b"<kml" in kml.content

    conflicto = cliente.put(f"{BASE}/redes-mt/{id}", json={"revision": 1, "datos": datos})
    assert conflicto.status_code == 409


def test_red_existente(cliente: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    id = cliente.post(f"{BASE}/ejemplos/red-mt").json()["id"]
    # Sin acceso al geoportal, la consulta responde con un problema claro.
    import electric.mt.sig as sig

    def sin_red(url: str, tiempo_s: float = 20) -> str:
        raise sig.ErrorSIG("no se pudo conectar con el geoportal: rechazado")

    monkeypatch.setattr(sig, "leer_url", sin_red)
    respuesta = cliente.post(f"{BASE}/redes-mt/{id}/existente/geoportal?lat=-2.17&lon=-79.9")
    assert respuesta.status_code == 502
    assert "GeoJSON" in respuesta.json()["detail"]
    diagnostico = cliente.get(f"{BASE}/red-mt/geoportal").json()
    assert diagnostico["conectado"] is False and "conectar" in diagnostico["error"]
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"CODIGO": "P-EX-12"},
                "geometry": {"type": "Point", "coordinates": [-79.9, -2.17]},
            }
        ],
    }
    cargada = cliente.post(
        f"{BASE}/redes-mt/{id}/existente/archivo",
        content=json.dumps(geojson).encode(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert cargada.status_code == 200, cargada.text
    assert cliente.get(f"{BASE}/redes-mt/{id}").json()["existente"]["postes"][0]["id"] == "P-EX-12"
    assert cliente.get(f"{BASE}/redes-mt").json()[0]["postes"] == 8
    assert cliente.delete(f"{BASE}/redes-mt/{id}").status_code == 204
