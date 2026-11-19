from __future__ import annotations

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


def test_flujo_de_una_urbanizacion(cliente: TestClient) -> None:
    u = cliente.post(f"{BASE}/urbanizaciones", json={"nombre": "Lotes"}).json()
    id = u["id"]
    assert cliente.get(f"{BASE}/urbanizaciones/{id}/calculo").json()["estado"] == "incompleto"
    datos = {**u["datos"], "manzanas": [{"id": "A", "lotes": 20}, {"id": "B", "lotes": 20}]}
    assert (
        cliente.put(f"{BASE}/urbanizaciones/{id}", json={"revision": 1, "datos": datos}).status_code
        == 200
    )
    assert (
        cliente.put(f"{BASE}/urbanizaciones/{id}", json={"revision": 1, "datos": datos}).status_code
        == 409
    )
    c = cliente.get(f"{BASE}/urbanizaciones/{id}/calculo").json()
    assert c["estado"] == "listo" and c["lotes"] == 40 and c["sectores"]
    assert sum(s["lotes"] for s in c["sectores"]) == 40
    assert cliente.get(f"{BASE}/urbanizaciones").json()[0]["lotes"] == 40
    png = cliente.get(f"{BASE}/urbanizaciones/{id}/plano.png")
    assert png.content[:4] == b"\x89PNG"
    assert cliente.delete(f"{BASE}/urbanizaciones/{id}").status_code == 204


def test_ejemplo(cliente: TestClient) -> None:
    r = cliente.post(f"{BASE}/ejemplos/urbanizacion")
    assert r.status_code == 201
    c = cliente.get(f"{BASE}/urbanizaciones/{r.json()['id']}/calculo").json()
    assert c["lotes"] == 64 and c["luminarias"] > 0
    dxf = cliente.get(f"{BASE}/urbanizaciones/{r.json()['id']}/plano.dxf")
    assert b"CUADRO DE TRANSFORMADORES" in dxf.content
