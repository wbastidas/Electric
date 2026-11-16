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


def test_opciones_y_plantilla(cliente: TestClient) -> None:
    opciones = cliente.get(f"{BASE}/industrial/opciones").json()
    assert "motor" in {t["id"] for t in opciones["tipos"]}
    assert "estrella_triangulo" in {a["id"] for a in opciones["arranques"]}
    assert "trifasico_277_480" in {s["id"] for s in opciones["sistemas"]}
    plantilla = cliente.get(f"{BASE}/industrial/plantilla")
    assert plantilla.status_code == 200
    assert plantilla.content[:2] == b"PK"
    assert cliente.get(f"{BASE}/industrial/opciones?perfil=control-nfpa70").status_code == 422


def test_flujo_completo_de_una_industria(cliente: TestClient) -> None:
    creada = cliente.post(f"{BASE}/industrias", json={"nombre": "Metalmecánica"})
    assert creada.status_code == 201, creada.text
    industria = creada.json()
    id = industria["id"]

    vacio = cliente.get(f"{BASE}/industrias/{id}/analisis").json()
    assert vacio["estado"] == "incompleto"

    plantilla = cliente.get(f"{BASE}/industrial/plantilla").content
    cargada = cliente.post(
        f"{BASE}/industrias/{id}/cuadro?revision=1&nombre=cuadro.xlsx",
        content=plantilla,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert cargada.status_code == 200, cargada.text
    assert len(cargada.json()["datos"]["maquinas"]) == 6
    assert cargada.json()["revision"] == 2

    analisis = cliente.get(f"{BASE}/industrias/{id}/analisis").json()
    assert analisis["estado"] == "listo"
    assert len(analisis["filas"]) == 6
    assert {t["tablero"] for t in analisis["tableros"]} == {"TD-1", "TD-2", "TD-3"}
    assert analisis["decision"]["opcion"] == "particular"
    assert analisis["decision"]["transformador"]["kva"] == 100

    datos = cargada.json()["datos"]
    datos["existente"] = {"codigo": "T-1", "kva": 300, "demanda_kva": 60, "distancia_m": 50}
    guardada = cliente.put(f"{BASE}/industrias/{id}", json={"revision": 2, "datos": datos})
    assert guardada.status_code == 200, guardada.text
    analisis = cliente.get(f"{BASE}/industrias/{id}/analisis").json()
    assert analisis["decision"]["opcion"] == "existente"
    assert "factibilidad" in " ".join(analisis["decision"]["motivos"])

    lista = cliente.get(f"{BASE}/industrias").json()
    assert lista[0]["maquinas"] == 6

    conflicto = cliente.put(f"{BASE}/industrias/{id}", json={"revision": 1, "datos": datos})
    assert conflicto.status_code == 409

    assert cliente.delete(f"{BASE}/industrias/{id}").status_code == 204
    assert cliente.get(f"{BASE}/industrias/{id}").status_code == 404


def test_cuadro_con_errores(cliente: TestClient) -> None:
    id = cliente.post(f"{BASE}/industrias", json={"nombre": "X"}).json()["id"]
    respuesta = cliente.post(
        f"{BASE}/industrias/{id}/cuadro?revision=1&nombre=c.csv",
        content=b"Codigo,Potencia,FP\nA,10,2\n",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert respuesta.status_code == 422
    assert "fila 2" in respuesta.json()["detail"]
