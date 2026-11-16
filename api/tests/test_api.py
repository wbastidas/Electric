from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from electric_api.app import crear_app
from electric_api.config import Config

RAIZ = Path(__file__).resolve().parents[2]
PERFIL = {"id": "cnel-ep", "version": "0.1.0"}


@pytest.fixture
def cliente(tmp_path: Path) -> Iterator[TestClient]:
    config = Config(
        base_de_datos="sqlite:///:memory:",
        perfiles=RAIZ / "perfiles",
        web=tmp_path / "sin-web",
    )
    with TestClient(crear_app(config)) as cliente:
        yield cliente


def _vivienda() -> dict[str, Any]:
    datos = json.loads((RAIZ / "ejemplos" / "vivienda-120m2" / "proyecto.json").read_text("utf-8"))
    del datos["id"]
    return datos


def _crear(cliente: TestClient, datos: dict[str, Any]) -> dict[str, Any]:
    respuesta = cliente.post("/api/v1/proyectos", json=datos)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_perfiles_muestran_el_estado_de_cada_tabla(cliente: TestClient) -> None:
    perfiles = {p["id"]: p for p in cliente.get("/api/v1/perfiles").json()}
    cnel = perfiles["cnel-ep"]
    assert cnel["sistema_defecto"] == "monofasico_trifilar_120_240"
    assert {t["estado"] for t in cnel["tablas"]} == {"por_verificar"}
    assert {c["tipo"] for c in cnel["cargas"] if c["especial"]} >= {"ducha", "cocina"}


def test_crear_un_proyecto_vacio_y_ver_que_falta(cliente: TestClient) -> None:
    proyecto = _crear(cliente, {"nombre": "Casa nueva", "perfil": PERFIL})
    assert proyecto["revision"] == 1
    calculos = cliente.get(f"/api/v1/proyectos/{proyecto['id']}/calculos").json()
    assert calculos["estado"] == "incompleto"
    assert {p["codigo"] for p in calculos["pendientes"]} == {
        "falta_area",
        "falta_tablero",
        "sin_circuitos",
    }
    assert calculos["resultados"] == []


def test_vivienda_completa_da_el_cuadro_de_cargas(cliente: TestClient) -> None:
    proyecto = _crear(cliente, _vivienda())
    calculos = cliente.get(f"/api/v1/proyectos/{proyecto['id']}/calculos").json()
    assert calculos["estado"] == "listo"
    assert calculos["aviso"].startswith("BORRADOR")
    resumen = {d["etiqueta"]: d for d in calculos["resumen"]}
    assert resumen["Carga instalada"]["texto"] == "14300 W"
    assert resumen["Demanda máxima"]["texto"] == "9885 W"
    assert resumen["Clasificación CNEL"]["texto"] == "Tipo I"
    assert resumen["Demanda máxima"]["estado"] == "por_verificar"
    cuadro = {f["circuito"]: f for f in calculos["cuadro"]}
    assert cuadro["C4"]["conductor"] == "10 AWG"
    assert cuadro["alimentador"]["breaker"] == "2P 60 A"
    assert len(calculos["tablas_sin_verificar"]) == 16
    assert any("C4" in aviso for aviso in calculos["avisos"])
    caida = next(r for r in calculos["resultados"] if (r["id"], r["sujeto"]) == ("RC-08", "C1"))
    assert caida["texto"] == "2,57 %"
    assert caida["formula"].startswith("ΔV %")
    assert caida["tablas"]


def test_la_huella_no_depende_del_identificador_ni_del_orden(cliente: TestClient) -> None:
    uno = _crear(cliente, _vivienda())
    datos = _vivienda()
    otro = _crear(cliente, dict(reversed(list(datos.items()))))
    h1 = cliente.get(f"/api/v1/proyectos/{uno['id']}/calculos").json()["resultados"]
    h2 = cliente.get(f"/api/v1/proyectos/{otro['id']}/calculos").json()["resultados"]
    assert h1 == h2


def test_guardar_sube_la_revision_y_queda_en_bitacora(cliente: TestClient) -> None:
    proyecto = _crear(cliente, _vivienda())
    ruta = f"/api/v1/proyectos/{proyecto['id']}"
    datos = proyecto["datos"]
    datos["predio"]["propietario"] = "María Pérez"
    datos["cargas_especiales"][0]["potencia_w"] = "4500"
    guardado = cliente.put(ruta, json={"revision": 1, "datos": datos})
    assert guardado.status_code == 200, guardado.text
    assert guardado.json()["revision"] == 2

    calculos = cliente.get(f"{ruta}/calculos").json()
    assert {f["circuito"]: f for f in calculos["cuadro"]}["C5"]["carga"] == "4500 W"
    assert any("placa" in s for s in calculos["supuestos"])

    bitacora = cliente.get(f"{ruta}/bitacora").json()
    assert [(e["accion"], e["revision"]) for e in bitacora] == [("guardar", 2), ("crear", 1)]
    assert bitacora[0]["huella"] != bitacora[1]["huella"]
    assert cliente.get("/api/v1/proyectos").json()[0]["propietario"] == "María Pérez"


def test_edicion_simultanea_se_rechaza_con_409(cliente: TestClient) -> None:
    proyecto = _crear(cliente, _vivienda())
    ruta = f"/api/v1/proyectos/{proyecto['id']}"
    assert cliente.put(ruta, json={"revision": 1, "datos": proyecto["datos"]}).status_code == 200
    tardio = cliente.put(ruta, json={"revision": 1, "datos": proyecto["datos"]})
    assert tardio.status_code == 409
    assert tardio.headers["content-type"].startswith("application/problem+json")
    assert tardio.json()["codigo"] == "revision_desactualizada"


def test_proyecto_incoherente_se_guarda_y_se_explica(cliente: TestClient) -> None:
    datos = _vivienda()
    datos["puntos"][0]["circuito"] = "C99"
    proyecto = _crear(cliente, datos)
    calculos = cliente.get(f"/api/v1/proyectos/{proyecto['id']}/calculos").json()
    assert calculos["estado"] == "incompleto"
    assert "circuito inexistente" in calculos["pendientes"][0]["mensaje"]


def test_un_calculo_sin_solucion_es_una_pregunta_y_no_un_error_500(cliente: TestClient) -> None:
    datos = _vivienda()
    datos["circuitos"][2]["longitud_m"] = "900"
    proyecto = _crear(cliente, datos)
    respuesta = cliente.get(f"/api/v1/proyectos/{proyecto['id']}/calculos")
    assert respuesta.status_code == 200
    assert respuesta.json()["pendientes"][0]["codigo"] == "sin_solucion"


def test_errores_en_formato_problem_json(cliente: TestClient) -> None:
    falta = cliente.get("/api/v1/proyectos/no-existe")
    assert falta.status_code == 404
    assert falta.json()["codigo"] == "proyecto_no_encontrado"

    invalido = cliente.post("/api/v1/proyectos", json={"nombre": "", "perfil": PERFIL})
    assert invalido.status_code == 422
    assert invalido.json()["errores"][0]["campo"] == "nombre"

    sin_perfil = cliente.post(
        "/api/v1/proyectos", json={"nombre": "x", "perfil": {"id": "otra", "version": "1"}}
    )
    assert sin_perfil.status_code == 422
    assert sin_perfil.json()["codigo"] == "perfil_no_disponible"


def test_borrar(cliente: TestClient) -> None:
    proyecto = _crear(cliente, _vivienda())
    ruta = f"/api/v1/proyectos/{proyecto['id']}"
    assert cliente.delete(ruta).status_code == 204
    assert cliente.get(ruta).status_code == 404
    assert cliente.get("/api/v1/proyectos").json() == []
