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


def test_opciones(cliente: TestClient) -> None:
    o = cliente.get(f"{BASE}/edificio/opciones").json()
    assert {"A", "C", "local", "oficina"} <= {u["id"] for u in o["usuarios"]}
    assert all("trifasico" in s["id"] for s in o["sistemas"])


def test_flujo_de_un_edificio(cliente: TestClient) -> None:
    creado = cliente.post(f"{BASE}/edificios", json={"nombre": "Torre"})
    assert creado.status_code == 201, creado.text
    e = creado.json()
    id = e["id"]
    vacio = cliente.get(f"{BASE}/edificios/{id}/calculo").json()
    assert vacio["estado"] == "incompleto"
    datos = {
        **e["datos"],
        "unidades": [{"id": "A", "estrato": "C", "pisos": [1, 2, 3], "por_piso": 4}],
        "servicios": [{"descripcion": "Bomba", "kw": "3.7", "motor": True}],
        "respaldo": "servicios_generales",
    }
    guardado = cliente.put(f"{BASE}/edificios/{id}", json={"revision": 1, "datos": datos})
    assert guardado.status_code == 200, guardado.text
    viejo = cliente.put(f"{BASE}/edificios/{id}", json={"revision": 1, "datos": datos})
    assert viejo.status_code == 409
    c = cliente.get(f"{BASE}/edificios/{id}/calculo").json()
    assert c["estado"] == "listo", c
    assert len(c["unidades"]) == 12 and c["medidores"] == 13
    assert c["unidades"][0]["id"] == "101" and c["generador"]["kva"] > 0
    assert c["principal"]["breaker_a"] and c["resultados"]
    assert cliente.get(f"{BASE}/edificios").json()[0]["unidades"] == 12
    dxf = cliente.get(f"{BASE}/edificios/{id}/unifilar.dxf")
    assert dxf.status_code == 200 and b"CENTRO DE MEDICI" in dxf.content
    png = cliente.get(f"{BASE}/edificios/{id}/unifilar.png")
    assert png.content[:4] == b"\x89PNG"
    assert cliente.get(f"{BASE}/edificios/{id}/camara.dxf").status_code == 404
    assert cliente.delete(f"{BASE}/edificios/{id}").status_code == 204
    assert cliente.get(f"{BASE}/edificios/{id}").status_code == 404


def test_ejemplo_y_datos_invalidos(cliente: TestClient) -> None:
    ejemplo = cliente.post(f"{BASE}/ejemplos/edificio")
    assert ejemplo.status_code == 201
    c = cliente.get(f"{BASE}/edificios/{ejemplo.json()['id']}/calculo").json()
    assert c["estado"] == "listo" and c["transformador"]["kva"] > 0
    e = cliente.post(f"{BASE}/edificios", json={"nombre": "Sin área"}).json()
    datos = {**e["datos"], "unidades": [{"id": "L", "uso": "local", "pisos": [0]}]}
    cliente.put(f"{BASE}/edificios/{e['id']}", json={"revision": 1, "datos": datos})
    c = cliente.get(f"{BASE}/edificios/{e['id']}/calculo").json()
    assert c["estado"] == "incompleto" and "área" in c["pendientes"][0]
    assert cliente.get(f"{BASE}/edificios/{e['id']}/unifilar.dxf").status_code == 422
