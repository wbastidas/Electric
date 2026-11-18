from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from electric_api.app import crear_app
from electric_api.config import Config

RAIZ = Path(__file__).resolve().parents[2]
BASE = "/api/v1"
PERFIL = {"id": "cnel-ep", "version": "0.1.0"}
EJEMPLO = RAIZ / "ejemplos" / "vivienda-2-pisos"


@pytest.fixture
def cliente(tmp_path: Path) -> Iterator[TestClient]:
    config = Config(
        base_de_datos="sqlite:///:memory:", perfiles=RAIZ / "perfiles", web=tmp_path / "sin-web"
    )
    with TestClient(crear_app(config)) as cliente:
        yield cliente


def _subir(cliente: TestClient, id: str, archivo: str, nombre: str, nivel: int, equipos: str):
    return cliente.post(
        f"{BASE}/edificaciones/{id}/pisos",
        params={"nivel": nivel, "nombre": nombre, "archivo": archivo, "equipos": equipos},
        content=(EJEMPLO / archivo).read_bytes(),
        headers={"Content-Type": "application/octet-stream"},
    )


def test_vivienda_de_dos_plantas_paso_a_paso(cliente: TestClient) -> None:
    creada = cliente.post(
        f"{BASE}/edificaciones",
        json={"nombre": "Casa Pérez", "perfil": PERFIL, "altura_piso_m": 3},
    )
    assert creada.status_code == 201, creada.text
    id = creada.json()["id"]
    assert cliente.get(f"{BASE}/edificaciones/{id}/calculo").json()["estado"] == "incompleto"

    assert (
        _subir(cliente, id, "planta-baja.dxf", "Planta baja", 0, "cocina,ducha").status_code == 201
    )
    repetido = _subir(cliente, id, "planta-alta.dxf", "Otra", 0, "")
    assert repetido.status_code == 409
    detalle = _subir(cliente, id, "planta-alta.dxf", "Planta alta", 1, "ducha").json()
    assert [(p["codigo"], p["estado"]) for p in detalle["pisos"]] == [
        ("PB", "listo"),
        ("P1", "listo"),
    ]

    calculo = cliente.get(f"{BASE}/edificaciones/{id}/calculo").json()
    assert calculo["estado"] == "listo", calculo
    assert calculo["piso_principal"] == "Planta baja"
    (sub,) = calculo["subtableros"]
    assert sub["tablero"] == "TD-P1" and sub["vertical_m"] == 3
    assert calculo["principal_a"] > sub["breaker_a"]
    assert calculo["demanda_kw"] > sub["demanda_kw"]

    # Cada planta es un proyecto que se abre en el editor y sabe a qué vivienda pertenece.
    planta = cliente.get(f"{BASE}/proyectos/{sub['proyecto_id']}").json()
    assert planta["planta"] == {
        "edificacion_id": id,
        "edificacion": "Casa Pérez",
        "piso": "Planta alta",
    }

    for formato, inicio in (("dxf", b"  0"), ("png", b"\x89PNG"), ("pdf", b"%PDF")):
        respuesta = cliente.get(f"{BASE}/edificaciones/{id}/unifilar.{formato}")
        assert respuesta.status_code == 200 and respuesta.content.startswith(inicio)

    assert cliente.get(f"{BASE}/edificaciones").json()[0]["pisos"] == 2
    assert cliente.delete(f"{BASE}/edificaciones/{id}").status_code == 204
    assert cliente.get(f"{BASE}/proyectos/{sub['proyecto_id']}").status_code == 404


def test_ejemplo_de_dos_plantas(cliente: TestClient) -> None:
    ejemplo = cliente.post(f"{BASE}/ejemplos/vivienda-2-pisos")
    assert ejemplo.status_code == 201, ejemplo.text
    id = ejemplo.json()["id"]
    calculo = cliente.get(f"{BASE}/edificaciones/{id}/calculo").json()
    assert calculo["estado"] == "listo"
    assert calculo["clasificacion"] == "Tipo II"
    # Borrar una planta desde el editor la saca de la vivienda.
    planta = ejemplo.json()["pisos"][1]["proyecto_id"]
    assert cliente.delete(f"{BASE}/proyectos/{planta}").status_code == 204
    assert len(cliente.get(f"{BASE}/edificaciones/{id}").json()["pisos"]) == 1
    assert cliente.get(f"{BASE}/edificaciones/{id}/calculo").json()["estado"] == "incompleto"
