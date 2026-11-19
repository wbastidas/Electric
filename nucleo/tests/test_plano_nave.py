"""Plano de la nave: tableros y máquinas, recorridos e implantación."""

from __future__ import annotations

import io
from decimal import Decimal as D
from pathlib import Path

import ezdxf
import pytest

from electric.errores import DatoInvalido
from electric.industrial import Industria, analizar, leer_cuadro
from electric.industrial.estudios import estudiar
from electric.industrial.plano import (
    CAPA_RECORRIDOS,
    generar_implantacion,
    leer_plano_nave,
    normal,
)
from electric.perfiles.carga import Perfil

EJEMPLO = Path(__file__).resolve().parents[2] / "ejemplos" / "nave-industrial"


def _plano(unidades: int = 6, factor: float = 1.0) -> bytes:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = unidades
    msp = doc.modelspace()
    for texto, (x, y) in {"TP": (0, 0), "TD 1": (10, 5), "M-1 motor": (14, 9)}.items():
        msp.add_text(texto).set_placement((x * factor, y * factor))
    salida = io.StringIO()
    doc.write(salida)
    return salida.getvalue().encode()


def test_codigos_normales() -> None:
    assert normal("td-1") == normal("TD 1") == normal("TD_1") == "TD1"


def test_recorridos_en_angulo_recto(perfil_cnel: Perfil) -> None:
    maquinas = leer_cuadro(b"Codigo,Potencia,Tablero\nM-1,10,TD-1\n", "c.csv")
    lectura = leer_plano_nave(_plano(), maquinas, perfil_cnel)
    # TP → TD-1: 10 + 5 m más 4 m de bajadas; TD-1 → M-1: 4 + 4 + 4.
    assert lectura.distancias_m == {"TD-1": D(19)}
    assert lectura.longitudes_m == {"M-1": D(12)}
    assert lectura.faltan == ()
    # El mismo plano dibujado en milímetros da lo mismo.
    en_mm = leer_plano_nave(_plano(4, 1000), maquinas, perfil_cnel)
    assert en_mm.distancias_m == lectura.distancias_m


def test_plano_sin_unidades(perfil_cnel: Perfil) -> None:
    maquinas = leer_cuadro(b"Codigo,Potencia,Tablero\nM-1,10,TD-1\n", "c.csv")
    with pytest.raises(DatoInvalido, match="unidades"):
        leer_plano_nave(_plano(0), maquinas, perfil_cnel)
    lectura = leer_plano_nave(_plano(0, 1000), maquinas, perfil_cnel, factor_a_metros=0.001)
    assert lectura.distancias_m == {"TD-1": D(19)}


def test_ejemplo_de_nave(perfil_cnel: Perfil) -> None:
    maquinas = leer_cuadro((EJEMPLO / "cuadro.csv").read_bytes(), "cuadro.csv")
    contenido = (EJEMPLO / "nave.dxf").read_bytes()
    lectura = leer_plano_nave(contenido, maquinas, perfil_cnel)
    assert not lectura.faltan and not lectura.avisos
    assert set(lectura.distancias_m) == {"TD-1", "TD-2", "TD-3"}
    industria = Industria(
        nombre="Nave",
        maquinas=tuple(maquinas),
        distancias_m=lectura.distancias_m,
        longitudes_maquina_m=lectura.longitudes_m,
    )
    estudios = estudiar(analizar(industria, perfil_cnel), perfil_cnel)
    td2 = next(a for a in estudios.alimentadores if a.tablero == "TD-2")
    assert td2.conductor is not None and td2.conductor.longitud_m == lectura.distancias_m["TD-2"]
    assert not td2.distancia_supuesta
    salida = generar_implantacion(contenido, lectura, maquinas, estudios)
    doc = ezdxf.read(io.StringIO(salida.decode()))
    rutas = [e for e in doc.modelspace() if e.dxf.layer == CAPA_RECORRIDOS]
    assert len(rutas) == 3 + len(maquinas)
