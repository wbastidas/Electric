"""Pruebas del esquema de perfiles y pruebas por fila de las tablas."""

from __future__ import annotations

import shutil
from decimal import Decimal as D
from pathlib import Path

import pytest
import yaml

from electric.errores import ErrorPerfil, FilaNoEncontrada
from electric.perfiles import Perfil, cargar_perfil

from .conftest import PERFILES


def test_los_perfiles_del_repositorio_validan(perfil_cnel: Perfil, perfil_control: Perfil) -> None:
    assert perfil_cnel.meta.id == "cnel-ep"
    assert perfil_control.meta.demanda_metodo == "escalonado"


def test_ninguna_tabla_inicial_figura_como_verificada(perfil_cnel: Perfil) -> None:
    # La versión inicial sale del documento de requerimientos, no del PDF oficial.
    assert {t.estado for t in perfil_cnel.tablas.values()} == {"por_verificar"}


@pytest.mark.parametrize(
    ("area", "esperado"),
    [
        ("79.99", (1, 1)),
        ("80", (2, 2)),
        ("200", (2, 2)),
        ("200.01", (3, 3)),
        ("300", (3, 3)),
        ("400", (4, 4)),
        ("400.01", (5, 5)),
        ("500", (5, 5)),
        ("501", (6, 6)),
    ],
)
def test_circuitos_minimos_por_fila(
    perfil_cnel: Perfil, area: str, esperado: tuple[int, int]
) -> None:
    assert perfil_cnel.circuitos_minimos(D(area))[0] == esperado


@pytest.mark.parametrize(
    ("area", "iluminacion", "tomacorrientes"),
    [
        ("60", "0.70", "0.50"),
        ("120", "0.70", "0.50"),
        ("250", "0.55", "0.40"),
        ("350", "0.55", "0.40"),
        ("450", "0.53", "0.30"),
    ],
)
def test_factores_demanda_por_fila(
    perfil_cnel: Perfil, area: str, iluminacion: str, tomacorrientes: str
) -> None:
    fila, ref = perfil_cnel.factores_demanda(D(area))
    assert (fila.iluminacion, fila.tomacorrientes) == (D(iluminacion), D(tomacorrientes))
    assert ref.estado == "por_verificar"


@pytest.mark.parametrize(("cantidad", "factor"), [(1, "0.80"), (2, "0.75"), (5, "0.75")])
def test_factor_de_cargas_especiales_por_fila(
    perfil_cnel: Perfil, cantidad: int, factor: str
) -> None:
    assert perfil_cnel.factor_especiales(cantidad)[0] == D(factor)


@pytest.mark.parametrize(
    ("tipo", "potencia"),
    [
        ("punto_luz", 100),
        ("tomacorriente", 200),
        ("ducha", 3500),
        ("cocina", 6000),
        ("calefon", 8000),
        ("aire_acondicionado", 2500),
        ("cargador_ev", 7500),
    ],
)
def test_cargas_por_fila(perfil_cnel: Perfil, tipo: str, potencia: int) -> None:
    assert perfil_cnel.carga(tipo)[0].potencia == D(potencia)


@pytest.mark.parametrize(
    ("calibre", "breaker"),
    [("14 AWG", 15), ("12 AWG", 20), ("10 AWG", 30), ("8 AWG", 40), ("6 AWG", 50)],
)
def test_relacion_conductor_breaker_por_fila(
    perfil_cnel: Perfil, calibre: str, breaker: int
) -> None:
    assert perfil_cnel.conductor(calibre)[0].breaker_max == D(breaker)


@pytest.mark.parametrize(
    ("breaker", "clase"),
    [
        (30, "clase 100"),
        (60, "clase 100"),
        (70, "clase 200"),
        (175, "clase 200"),
        (200, "con transformadores de corriente"),
    ],
)
def test_medidor_por_fila(perfil_cnel: Perfil, breaker: int, clase: str) -> None:
    assert perfil_cnel.medidor(D(breaker))[0].clase == clase


@pytest.mark.parametrize(
    ("breaker", "calibre"),
    [
        (15, "14 AWG"),
        (20, "12 AWG"),
        (40, "10 AWG"),
        (60, "10 AWG"),
        (100, "8 AWG"),
        (200, "6 AWG"),
    ],
)
def test_tierra_de_equipos_por_fila(perfil_cnel: Perfil, breaker: int, calibre: str) -> None:
    assert perfil_cnel.tierra_equipos(D(breaker))[0] == calibre


@pytest.mark.parametrize(
    ("temperatura", "factor"),
    [(20, "1.05"), (30, "1.00"), (33, "0.94"), (40, "0.88"), (45, "0.82"), (50, "0.75")],
)
def test_factor_de_temperatura_por_fila(perfil_cnel: Perfil, temperatura: int, factor: str) -> None:
    assert perfil_cnel.factor_temperatura(D(temperatura))[0] == D(factor)


@pytest.mark.parametrize(
    ("n", "factor"), [(2, "1.00"), (3, "1.00"), (4, "0.80"), (9, "0.70"), (12, "0.50")]
)
def test_factor_de_agrupamiento_por_fila(perfil_cnel: Perfil, n: int, factor: str) -> None:
    assert perfil_cnel.factor_agrupamiento(n)[0] == D(factor)


def test_normalizado_elige_el_primer_valor_que_cumple(perfil_cnel: Perfil) -> None:
    assert perfil_cnel.normalizado("breakers", D("33.97"))[0] == D(40)
    assert perfil_cnel.normalizado("breakers", D(40))[0] == D(40)
    assert perfil_cnel.normalizado_hasta("breakers", D(85)) == D(80)


def test_fuera_de_tabla_es_un_error_y_no_una_extrapolacion(perfil_cnel: Perfil) -> None:
    with pytest.raises(FilaNoEncontrada):
        perfil_cnel.factor_temperatura(D(60))
    with pytest.raises(FilaNoEncontrada):
        perfil_cnel.normalizado("breakers", D(1000))
    with pytest.raises(FilaNoEncontrada):
        perfil_cnel.carga("horno_industrial")


# --- perfiles inválidos ---------------------------------------------------


@pytest.fixture
def copia(tmp_path: Path) -> Path:
    destino = tmp_path / "cnel-ep"
    shutil.copytree(PERFILES / "cnel-ep", destino)
    return destino


def _editar(ruta: Path, **cambios: object) -> None:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    datos.update(cambios)
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")


def test_perfil_sin_una_tabla_requerida_no_carga(copia: Path) -> None:
    meta = yaml.safe_load((copia / "perfil.yaml").read_text(encoding="utf-8"))
    _editar(copia / "perfil.yaml", tablas=[t for t in meta["tablas"] if "medidores" not in t])
    with pytest.raises(ErrorPerfil, match="medidores"):
        cargar_perfil(copia)


def test_tabla_con_campo_desconocido_no_carga(copia: Path) -> None:
    _editar(copia / "tablas" / "cargas.yaml", inventado=1)
    with pytest.raises(ErrorPerfil):
        cargar_perfil(copia)


def test_verificado_exige_registro_de_quien_verifico(copia: Path) -> None:
    _editar(copia / "tablas" / "cargas.yaml", estado="verificado")
    with pytest.raises(ErrorPerfil, match="verificación"):
        cargar_perfil(copia)
    _editar(
        copia / "tablas" / "cargas.yaml",
        verificacion={"por": "Ing. de prueba", "fecha": "2026-11-15"},
    )
    assert cargar_perfil(copia).tablas["cargas"].estado == "verificado"


def test_minimo_con_calibre_inexistente_no_carga(copia: Path) -> None:
    ruta = copia / "tablas" / "minimos_calibre.yaml"
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    datos["filas"][0]["calibre"] = "16 AWG"
    _editar(ruta, filas=datos["filas"])
    with pytest.raises(ErrorPerfil, match="16 AWG"):
        cargar_perfil(copia)
