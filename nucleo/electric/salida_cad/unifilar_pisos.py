"""Diagrama unifilar de una vivienda de varios pisos, en DXF.

Medidor, breaker principal y tablero principal con los circuitos de su planta;
de él salen los alimentadores a los subtableros de cada piso con sus
circuitos. Cada circuito lleva su breaker, conductor y tipo.
"""

from __future__ import annotations

from decimal import Decimal

from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace

from electric.calculo import Calculado
from electric.calculo.resultado import ALIMENTADOR, PROYECTO, redondear
from electric.pisos import PRINCIPAL, Edificacion
from electric.salida_cad.dxf import _verificado

ALTO = 2.2
PASO = 16.0
TIPOS = {"iluminacion": "Iluminación", "tomacorrientes": "Tomas", "especial": "Especial"}
EQUIPOS = {
    "aire_acondicionado": "A/C",
    "refrigeradora": "Refrigeradora",
    "cargador_ev": "Cargador EV",
}


def _texto(
    msp: Modelspace,
    texto: str,
    x: float,
    y: float,
    alto: float = ALTO,
    alineacion: TextEntityAlignment = TextEntityAlignment.LEFT,
) -> None:
    msp.add_text(texto, height=alto, dxfattribs={"layer": "E-UNIF-TEXT"}).set_placement(
        (x, y), align=alineacion
    )


def _linea(msp: Modelspace, a: tuple[float, float], b: tuple[float, float]) -> None:
    msp.add_line(a, b, dxfattribs={"layer": "E-UNIF"})


def _breaker(msp: Modelspace, x: float, y: float) -> float:
    msp.add_lwpolyline(
        [(x - 2, y), (x + 2, y), (x + 2, y - 6), (x - 2, y - 6)],
        close=True,
        dxfattribs={"layer": "E-UNIF"},
    )
    _linea(msp, (x - 2, y - 6), (x + 2, y))
    return y - 6


def _num(valor: Decimal, decimales: int = 0) -> str:
    return f"{redondear(valor, decimales):f}".replace(".", ",")


def _circuitos(msp: Modelspace, calculado: Calculado, x0: float, y: float) -> float:
    """Dibuja los circuitos de un tablero bajo su barra; devuelve la y más baja."""
    fondo = y
    cargas = {c.circuito: c for c in calculado.proyecto.cargas_especiales}
    for n, circuito in enumerate(calculado.proyecto.circuitos):
        x = x0 + 6 + n * PASO
        _linea(msp, (x, y), (x, y - 5))
        yb = _breaker(msp, x, y - 5)
        _linea(msp, (x, yb), (x, yb - 6))
        breaker = calculado.res("RC-09", circuito.id).decimal
        conductor = str(calculado.res("RC-07", circuito.id).valor)
        tipo = TIPOS.get(circuito.tipo, circuito.tipo)
        carga = cargas.get(circuito.id)
        lineas = [
            circuito.id,
            EQUIPOS.get(carga.tipo, carga.tipo.replace("_", " ").capitalize())[:13]
            if carga
            else tipo,
            f"{_num(breaker)} A",
            conductor,
        ]
        for k, linea in enumerate(lineas):
            _texto(msp, linea, x, yb - 8 - k * 3, 1.7, TextEntityAlignment.TOP_CENTER)
        fondo = min(fondo, yb - 8 - len(lineas) * 3)
    return fondo


def generar_unifilar_pisos(edificacion: Edificacion) -> bytes:
    doc = Drawing.new("R2010")
    doc.units = 4  # milímetros
    for capa, color in {"E-UNIF": 7, "E-UNIF-TEXT": 7, "E-UNIF-MARCO": 8}.items():
        doc.layers.add(capa, color=color)
    msp = doc.modelspace()
    calc = edificacion.calculado
    tp = edificacion.calculado_principal

    columnas = [(PRINCIPAL, edificacion.principal.nombre, tp)] + [
        (s.tablero, s.piso.nombre, s.calculado) for s in edificacion.subtableros
    ]
    anchos = [max(len(c.proyecto.circuitos), 1) * PASO + 14 for _, _, c in columnas]
    total = sum(anchos)
    x0 = -total / 2

    # Medidor, acometida y breaker principal.
    y = 0.0
    msp.add_lwpolyline(
        [(-4, y), (4, y), (4, y - 7), (-4, y - 7)], close=True, dxfattribs={"layer": "E-UNIF"}
    )
    _texto(msp, "kWh", 0, y - 3.5, 2, TextEntityAlignment.MIDDLE_CENTER)
    medidor = calc.res("RC-12", PROYECTO)
    _texto(msp, f"MEDIDOR CNEL EP · {medidor.valor}", 7, y - 2)
    _texto(msp, f"Demanda {_num(calc.res('RC-03', PROYECTO).decimal / 1000, 2)} kW · "
           f"{calc.res('RC-05', PROYECTO).valor}", 7, y - 5.5)  # fmt: skip
    y -= 7
    _linea(msp, (0, y), (0, y - 14))
    alimentador = calc.proyecto.tablero.alimentador_longitud_m
    _texto(msp, f"{calc.res('RC-07', ALIMENTADOR).valor} · {_num(alimentador, 1)} m · "
           f"ΔV {_num(calc.res('RC-08', ALIMENTADOR).decimal, 2)} %", 3, y - 7)  # fmt: skip
    y -= 14
    yb = _breaker(msp, 0, y)
    _texto(msp, f"PRINCIPAL {_num(calc.res('RC-09', ALIMENTADOR).decimal)} A", 4, y - 3)
    _linea(msp, (0, yb), (0, yb - 6))
    y = yb - 6

    # Barra general: alimenta la columna del TP y los subtableros.
    msp.add_lwpolyline(
        [(x0, y), (x0 + total, y)], dxfattribs={"layer": "E-UNIF", "const_width": 1.0}
    )
    _texto(msp, f"TABLERO PRINCIPAL {PRINCIPAL} · {edificacion.principal.nombre}", x0, y + 2.5)
    barra = y
    fondo = barra
    x = x0
    subtableros = {s.tablero: s for s in edificacion.subtableros}
    for (tablero, nombre, calculado), ancho in zip(columnas, anchos, strict=True):
        if tablero == PRINCIPAL:
            fondo = min(fondo, _circuitos(msp, calculado, x, barra))
            x += ancho
            continue
        sub = subtableros[tablero]
        cx = x + 6
        _linea(msp, (cx, barra), (cx, barra - 6))
        yb = _breaker(msp, cx, barra - 6)
        _texto(msp, f"{_num(sub.breaker_a)} A", cx + 3.5, barra - 9)
        _texto(msp, f"{sub.conductor} · {_num(sub.longitud_m, 1)} m", cx + 3.5, yb - 6)
        _texto(msp, f"ΔV {_num(sub.caida_pct, 2)} %", cx + 3.5, yb - 9.5)
        _linea(msp, (cx, yb), (cx, yb - 16))
        ytd = yb - 16
        msp.add_lwpolyline(
            [(cx, ytd), (x + ancho - 6, ytd)], dxfattribs={"layer": "E-UNIF", "const_width": 0.7}
        )
        _texto(msp, f"SUBTABLERO {tablero} · {nombre}", cx, ytd + 2)
        fondo = min(fondo, _circuitos(msp, calculado, cx - 6, ytd))
        x += ancho

    y = fondo - 10
    _texto(msp, f"DIAGRAMA UNIFILAR · {edificacion.nombre}", x0, y, 3.5)
    resumen = f"{len(edificacion.pisos)} plantas · {_num(edificacion.area_m2, 1)} m²"
    _texto(msp, f"{resumen} · BORRADOR sujeto a revisión y firma de un profesional", x0, y - 5.5)
    msp.add_lwpolyline(
        [(x0 - 10, 10), (x0 + total + 10, 10), (x0 + total + 10, y - 10), (x0 - 10, y - 10)],
        close=True,
        dxfattribs={"layer": "E-UNIF-MARCO"},
    )
    return _verificado(doc)
