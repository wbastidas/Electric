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
    assert cuadro["alimentador"]["breaker"] == "2P 50 A"
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


def test_el_contrato_openapi_guardado_esta_al_dia(cliente: TestClient) -> None:
    """La interfaz genera sus tipos de api/openapi.json.

    Si falla, regenere: `python exportar_openapi.py` en api/ y `pnpm gen` en web/.
    """
    guardado = json.loads((RAIZ / "api" / "openapi.json").read_text("utf-8"))
    assert guardado == cliente.app.openapi()  # type: ignore[attr-defined]


# --- plano, diseño y salida ------------------------------------------------

PLANTA = RAIZ / "ejemplos" / "vivienda-plano" / "planta.dxf"
BINARIO = {"Content-Type": "application/octet-stream"}


def test_modelo_de_prueba_con_plano_de_punta_a_punta(cliente: TestClient) -> None:
    creado = cliente.post("/api/v1/ejemplos/vivienda-plano")
    assert creado.status_code == 201, creado.text
    proyecto = creado.json()
    ruta = f"/api/v1/proyectos/{proyecto['id']}"
    plano = proyecto["datos"]["plano"]
    assert len(plano["ambientes"]) == 9
    assert len(plano["recorridos"]) == 7
    assert len(plano["interruptores"]) == 9

    calculos = cliente.get(f"{ruta}/calculos").json()
    assert calculos["estado"] == "listo"
    assert {d["etiqueta"]: d["texto"] for d in calculos["resumen"]}[
        "Clasificación CNEL"
    ] == "Tipo I"

    fondo = cliente.get(f"{ruta}/plano/fondo").json()
    assert fondo["unidad"] == "metros"
    assert {linea["clase"] for linea in fondo["lineas"]} >= {"muro", "puerta", "ventana"}
    assert "cota" not in {linea["clase"] for linea in fondo["lineas"]}
    assert any(t["texto"] == "COCINA" for t in fondo["textos"])

    dxf = cliente.get(f"{ruta}/salida.dxf")
    assert dxf.status_code == 200 and b"E-CIRC" in dxf.content
    assert cliente.get(f"{ruta}/salida.png").content.startswith(b"\x89PNG")
    assert cliente.get(f"{ruta}/salida.pdf").content.startswith(b"%PDF")
    assert cliente.get(f"{ruta}/salida.svg").status_code == 404


def test_subir_plano_corregir_un_uso_y_disenar(cliente: TestClient) -> None:
    proyecto = _crear(cliente, {"nombre": "Casa con plano", "perfil": PERFIL})
    ruta = f"/api/v1/proyectos/{proyecto['id']}"

    subido = cliente.post(
        f"{ruta}/plano",
        params={"revision": 1, "nombre": "planta.dxf"},
        content=PLANTA.read_bytes(),
        headers=BINARIO,
    )
    assert subido.status_code == 200, subido.text
    datos = subido.json()["datos"]
    assert subido.json()["revision"] == 2
    assert datos["area_construida_m2"] == "123.32"
    assert len(datos["plano"]["ambientes"]) == 9
    assert datos["plano"]["ubicaciones"] == []

    # El usuario declara una ducha, cambia el uso de un dormitorio y fija el alimentador.
    datos["cargas_especiales"] = [{"id": "d1", "tipo": "ducha", "circuito": "-"}]
    datos["tablero"] = {"id": "TD-1", "alimentador_longitud_m": "10"}
    dormitorio = next(a for a in datos["plano"]["ambientes"] if a["nombre"] == "DORMITORIO 3")
    dormitorio["uso"] = "estudio"
    guardado = cliente.put(ruta, json={"revision": 2, "datos": datos})
    assert guardado.status_code == 200, guardado.text

    desactualizado = cliente.post(f"{ruta}/diseno", json={"revision": 2})
    assert desactualizado.status_code == 409

    diseno = cliente.post(f"{ruta}/diseno", json={"revision": 3})
    assert diseno.status_code == 200, diseno.text
    final = diseno.json()["proyecto"]
    assert final["revision"] == 4
    nuevos = final["datos"]
    assert [c["tipo"] for c in nuevos["cargas_especiales"]] == ["ducha"]
    assert nuevos["cargas_especiales"][0]["circuito"].startswith("C")
    estudio = next(a for a in nuevos["plano"]["ambientes"] if a["nombre"] == "DORMITORIO 3")
    luces = [
        p for p in nuevos["puntos"] if p["ambiente"] == estudio["id"] and p["tipo"] == "punto_luz"
    ]
    assert len(luces) == 2  # estudio: 10,97 m² / 10 m² por luminaria → 2; como dormitorio era 1

    assert cliente.get(f"{ruta}/calculos").json()["estado"] == "listo"
    acciones = [e["accion"] for e in cliente.get(f"{ruta}/bitacora").json()]
    assert acciones == ["diseñar", "guardar", "cargar plano", "crear"]


def test_plano_ilegible_o_sin_plano_se_explica(cliente: TestClient) -> None:
    proyecto = _crear(cliente, {"nombre": "Casa", "perfil": PERFIL})
    ruta = f"/api/v1/proyectos/{proyecto['id']}"
    malo = cliente.post(
        f"{ruta}/plano", params={"revision": 1}, content=b"no es un plano", headers=BINARIO
    )
    assert malo.status_code == 422
    assert malo.json()["codigo"] == "dato_invalido"
    assert cliente.post(f"{ruta}/diseno", json={"revision": 1}).json()["codigo"] == "sin_plano"
    assert cliente.get(f"{ruta}/salida.dxf").json()["codigo"] == "sin_plano"
    assert cliente.get(f"{ruta}/plano/fondo").status_code == 404


def test_borrar_un_proyecto_con_plano(cliente: TestClient) -> None:
    proyecto = cliente.post("/api/v1/ejemplos/vivienda-plano").json()
    assert cliente.delete(f"/api/v1/proyectos/{proyecto['id']}").status_code == 204
