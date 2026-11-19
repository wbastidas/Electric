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


def test_flujo_de_una_subestacion(cliente: TestClient) -> None:
    s = cliente.post(f"{BASE}/subestaciones", json={"nombre": "SE"}).json()
    id = s["id"]
    assert cliente.get(f"{BASE}/subestaciones/{id}/calculo").json()["estado"] == "incompleto"
    datos = {**s["datos"], "demanda_mva": "15", "alimentadores": 6}
    r = cliente.put(f"{BASE}/subestaciones/{id}", json={"revision": 1, "datos": datos})
    assert r.status_code == 200
    viejo = cliente.put(f"{BASE}/subestaciones/{id}", json={"revision": 1, "datos": datos})
    assert viejo.status_code == 409
    c = cliente.get(f"{BASE}/subestaciones/{id}/calculo").json()
    assert c["estado"] == "listo" and c["transformador"].startswith("16/20")
    assert c["scc_supuesta"] and c["malla"]["cumple"] and len(c["equipos"]) >= 10
    for plano in ("unifilar", "malla"):
        png = cliente.get(f"{BASE}/subestaciones/{id}/{plano}.png")
        assert png.content[:4] == b"\x89PNG"
    assert cliente.get(f"{BASE}/subestaciones").json()[0]["demanda_mva"] == 15
    assert cliente.delete(f"{BASE}/subestaciones/{id}").status_code == 204


def test_ejemplo(cliente: TestClient) -> None:
    r = cliente.post(f"{BASE}/ejemplos/subestacion")
    assert r.status_code == 201
    c = cliente.get(f"{BASE}/subestaciones/{r.json()['id']}/calculo").json()
    assert c["estado"] == "listo" and c["icc_mt_ka"] > 0
