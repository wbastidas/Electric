"""Planos de la subestación en DXF: unifilar y malla de puesta a tierra."""

from __future__ import annotations

from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace

from electric.industrial.analisis import _t
from electric.industrial.unifilar import CAPAS, _linea, _texto
from electric.salida_cad.dxf import _verificado
from electric.subestacion.calculo import SubestacionCalculada

CENTRO = TextEntityAlignment.MIDDLE_CENTER


def _interruptor(msp: Modelspace, x: float, y: float) -> float:
    """Interruptor de potencia como cuadrado; devuelve la y inferior."""
    msp.add_lwpolyline([(x - 3, y), (x + 3, y), (x + 3, y - 6), (x - 3, y - 6)], close=True,
                       dxfattribs={"layer": "E-UNIF"})  # fmt: skip
    return y - 6


def _seccionador(msp: Modelspace, x: float, y: float) -> float:
    """Cuchilla abierta entre dos contactos."""
    _linea(msp, (x, y), (x, y - 1))
    _linea(msp, (x, y - 1), (x + 3, y - 5))
    _linea(msp, (x - 1.2, y - 6), (x + 1.2, y - 6))
    _linea(msp, (x, y - 6), (x, y - 7))
    return y - 7


def _tc(msp: Modelspace, x: float, y: float) -> None:
    msp.add_circle((x, y), 1.6, dxfattribs={"layer": "E-UNIF"})


def _pararrayos(msp: Modelspace, x: float, y: float) -> None:
    _linea(msp, (x, y), (x + 8, y))
    msp.add_lwpolyline([(x + 6.5, y), (x + 9.5, y), (x + 9.5, y - 5), (x + 6.5, y - 5)], close=True,
                       dxfattribs={"layer": "E-UNIF"})  # fmt: skip
    _linea(msp, (x + 8, y - 5), (x + 8, y - 7))
    _linea(msp, (x + 6.5, y - 7), (x + 9.5, y - 7))


def generar_unifilar_subestacion(c: SubestacionCalculada) -> bytes:
    doc = Drawing.new("R2010")
    doc.units = 4
    for capa, color in CAPAS.items():
        doc.layers.add(capa, color=color)
    msp = doc.modelspace()
    se = c.subestacion
    eq = {e.nombre.split(" (")[0]: e.especificacion for e in c.equipos}
    x, y = 60.0, 0.0
    linea = f"LÍNEA DE {_t(c.tension_at_kv, 0)} kV DE CNEL · Scc {_t(c.scc_at_mva, 0)} MVA"
    _texto(msp, f"{linea} (por verificar)", x - 20, y + 4)
    _linea(msp, (x, y), (x, y - 8))
    _pararrayos(msp, x, y - 2)
    _texto(msp, f"Pararrayos {eq['Pararrayos de 69 kV']}", x + 12, y - 3)
    y -= 8
    y = _seccionador(msp, x, y)
    _texto(msp, f"89-AT · seccionador {eq['Seccionador de 69 kV']}", x + 6, y + 1)
    _linea(msp, (x, y), (x, y - 4))
    y = _interruptor(msp, x, y - 4)
    _texto(msp, f"52-AT · {eq['Interruptor de 69 kV']}", x + 6, y + 3)
    _tc(msp, x, y - 3)
    _texto(
        msp,
        f"TC {eq['TC de 69 kV']} · Icc {_t(c.icc_at_ka, 2)} kA",
        x + 6,
        y - 3.5,
        capa="E-UNIF-CC",
    )
    _linea(msp, (x, y), (x, y - 8))
    y -= 8
    msp.add_circle((x, y - 6), 6, dxfattribs={"layer": "E-UNIF"})
    msp.add_circle((x, y - 15), 6, dxfattribs={"layer": "E-UNIF"})
    _texto(msp, eq["Transformador de potencia"], x + 9, y - 9)
    y -= 21
    _pararrayos(msp, x, y - 2)
    _texto(msp, f"Pararrayos {eq['Pararrayos de 13,8 kV']}", x + 12, y - 4)
    _linea(msp, (x, y), (x, y - 8))
    y -= 8
    _tc(msp, x, y - 1)
    y = _interruptor(msp, x, y - 3)
    principal = eq["Interruptor principal de 13,8 kV"]
    _texto(msp, f"52-MT · {principal} · TC {eq['TC principal de 13,8 kV']}", x + 6, y + 3)
    _linea(msp, (x, y), (x, y - 6))
    y -= 6
    n = se.alimentadores
    paso = 26.0
    ancho = (n + 1) * paso
    x0 = x - ancho / 2
    msp.add_lwpolyline(
        [(x0, y), (x0 + ancho, y)], dxfattribs={"layer": "E-UNIF", "const_width": 1.2}
    )
    _texto(msp, f"BARRA {_t(c.tension_mt_kv, 1)} kV · Icc {_t(c.icc_mt_ka, 2)} kA", x0, y + 2.5,
           capa="E-UNIF-CC")  # fmt: skip
    for i in range(n + 1):
        xi = x0 + paso / 2 + i * paso
        yy = y
        _linea(msp, (xi, yy), (xi, yy - 4))
        yy = _interruptor(msp, xi, yy - 4)
        _tc(msp, xi, yy - 3)
        _linea(msp, (xi, yy), (xi, yy - 14))
        if i < n:
            especificacion = eq["Interruptores de alimentador"].split(", TC")[0]
            nominal, _, icc = especificacion.rpartition(", ")
            textos = [f"ALIMENTADOR {i + 1}", f"{_t(c.corriente_alimentador_a, 0)} A", nominal, icc]
        else:
            textos = [
                "SERVICIOS",
                "AUXILIARES",
                eq["Transformador de servicios auxiliares"].split(",")[0],
            ]
        for k, t in enumerate(textos):
            _texto(msp, t, xi, yy - 17 - k * 3, 1.8, alineacion=TextEntityAlignment.TOP_CENTER)
    yy = y - 46
    _texto(msp, se.nombre.upper(), x0, yy, 3.5)
    _texto(msp, f"Demanda {_t(se.demanda_mva, 2)} MVA · In AT {_t(c.corriente_at_a, 1)} A · "
           f"In MT {_t(c.corriente_mt_a, 1)} A", x0, yy - 5)  # fmt: skip
    _texto(msp, f"Protecciones: {eq['Relés de protección']}", x0, yy - 9)
    _texto(msp, "DIAGRAMA UNIFILAR — BORRADOR, REQUIERE REVISIÓN Y FIRMA", x0, yy - 13)
    return _verificado(doc)


def generar_plano_malla(c: SubestacionCalculada) -> bytes:
    doc = Drawing.new("R2010")
    doc.units = 6
    doc.header["$INSUNITS"] = 6
    for capa, color in (("E-MALLA", 3), ("E-VARILLA", 1), ("E-TEXTO", 7), ("A-CERCO", 8)):
        doc.layers.add(capa, color=color)
    msp = doc.modelspace()
    m = c.malla
    lx, ly = m.largo_m, m.ancho_m
    msp.add_lwpolyline([(-1, -1), (lx + 1, -1), (lx + 1, ly + 1), (-1, ly + 1)], close=True,
                       dxfattribs={"layer": "A-CERCO"})  # fmt: skip
    for i in range(m.conductores_x):
        yy = ly * i / (m.conductores_x - 1)
        msp.add_line((0, yy), (lx, yy), dxfattribs={"layer": "E-MALLA"})
    for j in range(m.conductores_y):
        xx = lx * j / (m.conductores_y - 1)
        msp.add_line((xx, 0), (xx, ly), dxfattribs={"layer": "E-MALLA"})
    # Varillas en los cruces del perímetro.
    puntos = {
        (lx * j / (m.conductores_y - 1), y0) for j in range(m.conductores_y) for y0 in (0, ly)
    }
    puntos |= {
        (x0, ly * i / (m.conductores_x - 1)) for i in range(m.conductores_x) for x0 in (0, lx)
    }
    for px, py in sorted(puntos):
        msp.add_circle((px, py), 0.35, dxfattribs={"layer": "E-VARILLA"})
    alto = max(lx, ly) / 50
    lineas = [
        "MALLA DE PUESTA A TIERRA (IEEE 80)",
        f"{lx:.0f} × {ly:.0f} m, cuadrícula de {m.separacion_m:.0f} m, "
        f"conductor de cobre {m.calibre} a 0,5 m",
        f"{len(puntos)} varillas de cobre en el perímetro",
        f"Rg = {m.resistencia_ohm:.2f} Ω {'≤' if m.resistencia_cumple else '>'} "
        f"{m.limite_resistencia_ohm:.0f} Ω{'' if m.resistencia_cumple else ' (NO CUMPLE)'}"
        f" · GPR = {m.gpr_v:.0f} V",
        f"Tensión de malla {m.tension_malla_v:.0f} V ≤ {m.contacto_tolerable_v:.0f} V tolerable"
        if m.cumple
        else f"Tensión de malla {m.tension_malla_v:.0f} V frente a "
        f"{m.contacto_tolerable_v:.0f} V: NO CUMPLE",
        f"Tensión de paso {m.tension_paso_v:.0f} V frente a {m.paso_tolerable_v:.0f} V tolerable",
        "Capa de grava de 10 cm sobre todo el patio",
        "BORRADOR — REQUIERE REVISIÓN Y FIRMA",
    ]
    for k, t in enumerate(lineas):
        msp.add_text(
            t.replace(".", ","), height=alto, dxfattribs={"layer": "E-TEXTO"}
        ).set_placement((lx + 4, ly - k * alto * 1.8))
    return _verificado(doc)
