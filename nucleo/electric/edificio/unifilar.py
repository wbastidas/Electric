"""Diagrama unifilar de un edificio en DXF.

Arriba la red de CNEL y el transformador (o la acometida desde la red), el
breaker principal y la barra del centro de medición. De la barra baja una
columna por medidor: servicios generales primero y luego cada unidad, piso por
piso, con su breaker, medidor y alimentador. Si hay generador, su transferencia
automática va antes de la barra (respaldo total) o en la columna de servicios
generales.
"""

from __future__ import annotations

from decimal import Decimal

from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace

from electric.edificio.calculo import EdificioCalculado
from electric.industrial.analisis import _t
from electric.industrial.unifilar import CAPAS, _breaker, _linea, _texto
from electric.salida_cad.dxf import _verificado

PASO = 18.0
CENTRO = TextEntityAlignment.MIDDLE_CENTER


def _a(valor: Decimal | None) -> str:
    return f"{_t(valor, 0)} A" if valor is not None else "fuera de serie"


def _medidor(msp: Modelspace, x: float, y: float) -> float:
    msp.add_circle((x, y - 3), 3, dxfattribs={"layer": "E-UNIF"})
    _texto(msp, "M", x, y - 3, 2.0, alineacion=CENTRO)
    return y - 6


def _generador(msp: Modelspace, x: float, y: float, texto: list[str]) -> None:
    msp.add_circle((x, y), 5, dxfattribs={"layer": "E-UNIF"})
    _texto(msp, "G", x, y, 3.0, alineacion=CENTRO)
    for n, t in enumerate(texto):
        _texto(msp, t, x + 7, y + 2 - n * 3.2)


def _transferencia(msp: Modelspace, x: float, y: float, texto: str) -> float:
    msp.add_lwpolyline(
        [(x - 4, y), (x + 4, y), (x + 4, y - 7), (x - 4, y - 7)],
        close=True,
        dxfattribs={"layer": "E-UNIF"},
    )
    _texto(msp, "ATS", x, y - 3.5, 2.0, alineacion=CENTRO)
    _texto(msp, texto, x + 6, y - 3.5)
    return y - 7


def generar_unifilar_edificio(calculo: EdificioCalculado) -> bytes:
    doc = Drawing.new("R2010")
    doc.units = 4
    for capa, color in CAPAS.items():
        doc.layers.add(capa, color=color)
    msp = doc.modelspace()
    e = calculo.edificio
    s = calculo.sistema
    columnas = (1 if calculo.servicios else 0) + len(calculo.unidades)
    ancho = max(columnas * PASO + 40, 200)
    x0 = 20.0

    # Red, transformador y principal.
    y = 0.0
    _texto(msp, "RED DE MEDIA TENSIÓN DE CNEL" if calculo.transformador else "RED DE CNEL (BT)",
           x0, y + 4)  # fmt: skip
    _linea(msp, (x0, y), (x0, y - 8))
    y -= 8
    if calculo.transformador:
        t = calculo.transformador
        msp.add_circle((x0, y - 5), 5, dxfattribs={"layer": "E-UNIF"})
        msp.add_circle((x0, y - 12), 5, dxfattribs={"layer": "E-UNIF"})
        lineas = [
            f"Transformador {_t(t.kva, 1)} kVA trifásico ({t.montaje})",
            f"BT {_t(s.v_linea, 0)}/{_t(s.v_fase_neutro, 0)} V · Z = {_t(t.z_pct, 2)} %",
        ]
        if calculo.camara:
            lineas.append(f"Cámara de transformación · fusibles {calculo.camara.fusible or '—'}")
        for n, texto in enumerate(lineas):
            _texto(msp, texto, x0 + 9, y - 5 - n * 3.2)
        y -= 17
    p = calculo.principal
    _linea(msp, (x0, y), (x0, y - 6))
    y -= 6
    texto_acometida = (
        f"Acometida {p.conductor.texto} · {_t(p.conductor.longitud_m, 0)} m · "
        f"ΔV {_t(p.conductor.caida_pct, 2)} %"
        if p.conductor
        else "Acometida sin solución"
    )
    _texto(msp, texto_acometida, x0 + 4, y + 2)
    if calculo.generador and e.respaldo == "total":
        g = calculo.generador
        _generador(msp, x0 + 60, y - 4, [f"Generador {_t(g.kva, 0) if g.kva else '—'} kVA",
                                         "respaldo total"])  # fmt: skip
        y = _transferencia(msp, x0, y - 1, f"Transferencia automática {_a(g.transferencia_a)}")
        _linea(msp, (x0 + 4, y + 3.5), (x0 + 55, y + 3.5))
        _linea(msp, (x0, y), (x0, y - 4))
        y -= 4
    y = _breaker(msp, x0, y)
    _texto(msp, f"Principal 3P {_a(p.breaker_a)}", x0 + 4, y + 3)
    if p.icc_ka is not None:
        _texto(msp, f"Icc {_t(p.icc_ka, 1)} kA", x0 + 4, y - 0.5, capa="E-UNIF-CC")
    _linea(msp, (x0, y), (x0, y - 6))
    y -= 6

    # Barra del centro de medición.
    msp.add_lwpolyline(
        [(x0 - 5, y), (x0 + ancho - 25, y)], dxfattribs={"layer": "E-UNIF", "const_width": 1.0}
    )
    _texto(
        msp,
        f"CENTRO DE MEDICIÓN · barra {_a(p.barra_a)} · {calculo.medidores} medidores en "
        f"{calculo.modulos} módulo{'s' if calculo.modulos > 1 else ''}",
        x0 - 5,
        y + 2,
    )
    barra = y

    x = x0 + 4
    if calculo.servicios:
        sg = calculo.servicios
        yy = barra
        _linea(msp, (x, yy), (x, yy - 4))
        yy = _breaker(msp, x, yy - 4)
        yy = _medidor(msp, x, yy - 1)
        _linea(msp, (x, yy), (x, yy - 4))
        yy -= 4
        if calculo.generador and e.respaldo == "servicios_generales":
            g = calculo.generador
            yy = _transferencia(msp, x, yy, "")
            _linea(msp, (x + 4, yy + 3.5), (x + 9, yy + 3.5))
            _generador(msp, x + 14, yy + 3.5, [])
            _texto(msp, f"G {_t(g.kva, 0) if g.kva else '—'} kVA · ATS {_a(g.transferencia_a)}",
                   x + 8, yy - 4.5, 1.8)  # fmt: skip
            _linea(msp, (x, yy), (x, yy - 8))
            yy -= 8
        _rotulos(msp, x, yy, ["SERVICIOS", "GENERALES", f"{_t(sg.demanda_kva, 1)} kVA",
                              f"3P {_a(sg.breaker_a)}", sg.medidor,
                              sg.conductor.texto if sg.conductor else "sin solución"])  # fmt: skip
        x += PASO * (2.2 if calculo.generador and e.respaldo == "servicios_generales" else 1)
    for u in calculo.unidades:
        yy = barra
        _linea(msp, (x, yy), (x, yy - 4))
        yy = _breaker(msp, x, yy - 4)
        yy = _medidor(msp, x, yy - 1)
        _linea(msp, (x, yy), (x, yy - 18))
        polos = {1: "1P", 2: "2P", 3: "3P"}[u.fases]
        _rotulos(msp, x, yy - 18, [u.id, _corto(u.tipo), f"{_t(u.demanda_kva, 1)} kVA",
                                   f"{polos} {_a(u.breaker_a)}",
                                   u.conductor.texto if u.conductor else "sin solución",
                                   f"{_t(u.longitud_m, 0)} m"])  # fmt: skip
        x += PASO

    # Cuadro de demanda.
    yy = barra - 70
    _texto(msp, "DEMANDA DEL EDIFICIO", x0 - 5, yy, 3.0)
    yy -= 5
    for grupo in calculo.grupos:
        texto = (
            f"{grupo.nombre}: {grupo.usuarios} usuarios, Σ {_t(grupo.suma_kva, 1)} kVA × FC "
            f"{_t(grupo.factor, 2)} = {_t(grupo.demanda_kva, 1)} kVA"
        )
        _texto(msp, texto, x0 - 5, yy)
        yy -= 3.6
    if calculo.servicios:
        _texto(msp, f"Servicios generales: {_t(calculo.servicios.demanda_kva, 1)} kVA", x0 - 5, yy)
        yy -= 3.6
    _texto(msp, f"Total: {_t(calculo.demanda_kva, 1)} kVA · {_t(calculo.demanda_kw, 1)} kW · "
           f"{calculo.nivel.nombre}", x0 - 5, yy)  # fmt: skip
    yy -= 7
    _texto(msp, e.nombre.upper(), x0 - 5, yy, 3.5)
    _texto(msp, "DIAGRAMA UNIFILAR — BORRADOR, REQUIERE REVISIÓN Y FIRMA", x0 - 5, yy - 5)
    msp.add_lwpolyline(
        [(x0 - 12, 12), (x0 + ancho - 15, 12), (x0 + ancho - 15, yy - 10), (x0 - 12, yy - 10)],
        close=True,
        dxfattribs={"layer": "E-UNIF-MARCO"},
    )
    return _verificado(doc)


def _corto(texto: str, n: int = 10) -> str:
    """Rótulo que cabe en una columna del unifilar."""
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def _rotulos(msp: Modelspace, x: float, y: float, textos: list[str]) -> None:
    for n, texto in enumerate(textos):
        _texto(msp, texto, x, y - 3 - n * 3.0, 1.8, alineacion=TextEntityAlignment.TOP_CENTER)
