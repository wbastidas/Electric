"""Salidas de una extensión de red de MT: planimetría DXF, unifilar y KML."""

from __future__ import annotations

import math
from decimal import Decimal
from xml.sax.saxutils import escape

from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace

from electric.calculo.resultado import redondear
from electric.mt.calculo import RedCalculada, proyectar
from electric.mt.modelo import RedExistente
from electric.salida_cad.dxf import _verificado

CAPAS = {
    "MT-EXISTENTE": 8,
    "MT-NUEVA": 1,
    "MT-POSTES": 5,
    "MT-TRAFOS": 6,
    "MT-TEXTO": 7,
    "MT-COTAS": 3,
    "MT-MARCO": 8,
}


def _n(valor: Decimal | float, decimales: int = 0) -> str:
    return f"{redondear(Decimal(str(valor)), decimales):f}".replace(".", ",")


def _texto(
    msp: Modelspace,
    texto: str,
    x: float,
    y: float,
    alto: float,
    capa: str = "MT-TEXTO",
    alineacion: TextEntityAlignment = TextEntityAlignment.LEFT,
    rotacion: float = 0.0,
) -> None:
    msp.add_text(texto, height=alto, rotation=rotacion, dxfattribs={"layer": capa}).set_placement(
        (x, y), align=alineacion
    )


def _documento() -> tuple[Drawing, Modelspace]:
    doc = Drawing.new("R2010")
    doc.units = 6  # metros
    for capa, color in CAPAS.items():
        doc.layers.add(capa, color=color)
    return doc, doc.modelspace()


def generar_planimetria(red: RedCalculada, existente: RedExistente | None = None) -> bytes:
    """Planta de la red en metros alrededor del arranque, con la red existente en gris."""
    doc, msp = _documento()
    ext = red.extension
    a = ext.arranque
    puntos = [(red.arranque.x, red.arranque.y)] + [(p.x, p.y) for p in red.postes]
    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    alcance = max(max(xs) - min(xs), max(ys) - min(ys), 50.0)
    alto = max(alcance / 120, 1.2)
    radio = alto * 0.6

    def local(lat: Decimal, lon: Decimal) -> tuple[float, float]:
        return proyectar(lat, lon, a.lat, a.lon)

    if existente is not None:
        for tramo in existente.tramos:
            msp.add_lwpolyline(
                [local(c.lat, c.lon) for c in tramo.puntos], dxfattribs={"layer": "MT-EXISTENTE"}
            )
        for sig in existente.postes:
            ex, ey = local(sig.lat, sig.lon)
            msp.add_circle((ex, ey), radio * 0.7, dxfattribs={"layer": "MT-EXISTENTE"})
            _texto(msp, sig.id, ex + radio, ey - radio, alto * 0.6, "MT-EXISTENTE")
        for trafo in existente.transformadores:
            x, y = local(trafo.lat, trafo.lon)
            _texto(
                msp, f"T {trafo.kva or ''} kVA", x + radio, y + radio, alto * 0.6, "MT-EXISTENTE"
            )

    # Línea nueva y vanos.
    msp.add_lwpolyline(puntos, dxfattribs={"layer": "MT-NUEVA", "const_width": alto * 0.15})
    for vano, (p, q) in zip(red.vanos, zip(puntos, puntos[1:], strict=False), strict=True):
        mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
        angulo = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
        if angulo > 90 or angulo < -90:
            angulo += 180
        _texto(
            msp,
            f"{_n(vano.longitud_m, 1)} m",
            mx,
            my + alto * 0.4,
            alto * 0.75,
            "MT-COTAS",
            TextEntityAlignment.BOTTOM_CENTER,
            angulo,
        )

    # Arranque.
    msp.add_circle(puntos[0], radio * 1.6, dxfattribs={"layer": "MT-NUEVA"})
    _texto(msp, f"ARRANQUE {red.arranque.id}", radio * 2, radio * 2, alto)
    if a.alimentador:
        _texto(msp, f"Alimentador {a.alimentador}", radio * 2, radio * 2 - alto * 1.4, alto * 0.8)

    # Postes nuevos.
    for n, poste in enumerate(red.postes, start=1):
        msp.add_circle((poste.x, poste.y), radio, dxfattribs={"layer": "MT-POSTES"})
        _texto(
            msp,
            str(n),
            poste.x,
            poste.y,
            alto * 0.7,
            "MT-POSTES",
            TextEntityAlignment.MIDDLE_CENTER,
        )
        etiqueta = poste.codigo or poste.estructura_nombre
        _texto(
            msp, f"{poste.id} · {etiqueta}", poste.x + radio * 1.5, poste.y - alto * 1.6, alto * 0.7
        )
        if poste.transformador_kva:
            lado = radio * 2
            tx, ty = poste.x + radio * 1.5, poste.y + radio * 1.5
            msp.add_lwpolyline(
                [(tx, ty), (tx + lado, ty), (tx + lado / 2, ty + lado * 0.87)],
                close=True,
                dxfattribs={"layer": "MT-TRAFOS"},
            )
            _texto(
                msp,
                f"{_n(poste.transformador_kva, 1)} kVA · {poste.fusible or ''}",
                tx + lado * 1.3,
                ty,
                alto * 0.75,
                "MT-TRAFOS",
            )

    # Norte.
    nx, ny = max(xs) + alcance * 0.1, max(ys) + alcance * 0.05
    msp.add_lwpolyline(
        [(nx, ny), (nx - alto, ny - alto * 3), (nx, ny - alto * 2.2), (nx + alto, ny - alto * 3)],
        close=True,
        dxfattribs={"layer": "MT-TEXTO"},
    )
    _texto(msp, "N", nx, ny + alto * 0.5, alto * 1.2, alineacion=TextEntityAlignment.BOTTOM_CENTER)

    # Tabla de estructuras y rótulo.
    x0 = min(xs) - alcance * 0.05
    y = min(ys) - alcance * 0.12
    _texto(msp, f"PLANIMETRÍA · {ext.nombre}", x0, y, alto * 1.5)
    y -= alto * 2.2
    _texto(
        msp,
        f"{_n(ext.tension_kv, 1)} kV · {ext.fases}F · {ext.conductor} · "
        f"{_n(red.longitud_m, 1)} m · caída {_n(red.caida_pct, 2)} % · zona {ext.zona}",
        x0,
        y,
        alto * 0.9,
    )
    y -= alto * 2.4
    _texto(msp, "TABLA DE ESTRUCTURAS", x0, y, alto)
    y -= alto * 1.8
    for n, poste in enumerate(red.postes, start=1):
        deflexion = f"{_n(poste.angulo, 0)}°" if poste.angulo is not None else "—"
        fila = (
            f"{n:>3}  {poste.id:<10}  {poste.estructura_nombre:<28}  "
            f"{poste.codigo or 'código por definir':<20}  deflexión {deflexion:<6}"
            + (f"  T {_n(poste.transformador_kva, 1)} kVA" if poste.transformador_kva else "")
        )
        _texto(msp, fila, x0, y, alto * 0.75)
        y -= alto * 1.3
    _texto(
        msp,
        "BORRADOR sujeto a revisión y firma de un profesional habilitado. Coordenadas WGS84 "
        "proyectadas en metros alrededor del arranque.",
        x0,
        y - alto,
        alto * 0.7,
    )
    return _verificado(doc)


def generar_unifilar_mt(red: RedCalculada) -> bytes:
    """Unifilar de la extensión: arranque, seccionador fusible, línea y transformadores."""
    doc, msp = _documento()
    ext = red.extension
    a = ext.arranque
    alto = 2.2
    _texto(msp, f"RED CNEL EP {_n(ext.tension_kv, 1)} kV", 8, 1, alto)
    detalle = f"Ik = {_n(red.ik_arranque_ka, 2)} kA"
    if a.alimentador:
        detalle = f"Alimentador {a.alimentador} · {detalle}"
    _texto(msp, detalle, 8, -2.5, alto)
    msp.add_circle((0, 0), 4, dxfattribs={"layer": "MT-NUEVA"})
    _texto(msp, "~", 0, 0, 4, alineacion=TextEntityAlignment.MIDDLE_CENTER)
    msp.add_line((0, -4), (0, -12), dxfattribs={"layer": "MT-NUEVA"})
    # Seccionador fusible.
    msp.add_lwpolyline(
        [(-2, -12), (2, -12), (2, -20), (-2, -20)], close=True, dxfattribs={"layer": "MT-NUEVA"}
    )
    msp.add_line((0, -12), (0, -20), dxfattribs={"layer": "MT-NUEVA"})
    _texto(msp, f"SECCIONADOR FUSIBLE {red.fusible_derivacion or ''}", 4, -16, alto)
    msp.add_line((0, -20), (0, -28), dxfattribs={"layer": "MT-NUEVA"})
    # Barra de la línea.
    trafos = [p for p in red.postes if p.transformador_kva]
    ancho = max(len(trafos), 1) * 30 + 20
    msp.add_lwpolyline(
        [(0, -28), (ancho, -28)], dxfattribs={"layer": "MT-NUEVA", "const_width": 0.8}
    )
    _texto(
        msp,
        f"{ext.conductor} · {_n(red.longitud_m, 1)} m · {ext.fases}F · ΔV {_n(red.caida_pct, 2)} %",
        2,
        -26,
        alto,
    )
    for n, poste in enumerate(trafos):
        x = 20 + n * 30
        msp.add_line((x, -28), (x, -34), dxfattribs={"layer": "MT-NUEVA"})
        msp.add_lwpolyline(
            [(x - 1.5, -34), (x + 1.5, -34), (x + 1.5, -39), (x - 1.5, -39)],
            close=True,
            dxfattribs={"layer": "MT-NUEVA"},
        )
        _texto(msp, poste.fusible or "", x + 2.5, -37, 1.8)
        msp.add_line((x, -39), (x, -42), dxfattribs={"layer": "MT-NUEVA"})
        msp.add_circle((x, -45), 3, dxfattribs={"layer": "MT-TRAFOS"})
        msp.add_circle((x, -50), 3, dxfattribs={"layer": "MT-TRAFOS"})
        for k, linea in enumerate(
            (poste.id, f"{_n(poste.transformador_kva or 0, 1)} kVA", f"{ext.fases}F")
        ):
            _texto(msp, linea, x, -55 - k * 3, 1.8, alineacion=TextEntityAlignment.TOP_CENTER)
    _texto(msp, f"DIAGRAMA UNIFILAR MT · {ext.nombre}", 0, -70, 3.2)
    _texto(msp, "BORRADOR sujeto a revisión y firma de un profesional habilitado.", 0, -75, 1.8)
    return _verificado(doc)


def generar_kml(red: RedCalculada) -> bytes:
    """Línea y postes nuevos en KML (WGS84), para Google Earth o un SIG."""
    ext = red.extension
    a = ext.arranque
    coordenadas = " ".join(f"{p.lon},{p.lat},0" for p in [red.arranque, *red.postes])
    marcas = [
        f"<Placemark><name>{escape(red.arranque.id)}</name>"
        f"<description>Arranque{escape(' · ' + a.alimentador) if a.alimentador else ''}"
        f"</description><styleUrl>#arranque</styleUrl>"
        f"<Point><coordinates>{a.lon},{a.lat},0</coordinates></Point></Placemark>"
    ]
    for n, p in enumerate(red.postes, start=1):
        descripcion = f"{p.estructura_nombre}" + (f" · {p.codigo}" if p.codigo else "")
        if p.transformador_kva:
            descripcion += f" · transformador {p.transformador_kva} kVA, fusible {p.fusible}"
        marcas.append(
            f"<Placemark><name>{n} · {escape(p.id)}</name>"
            f"<description>{escape(descripcion)}</description><styleUrl>#poste</styleUrl>"
            f"<Point><coordinates>{p.lon},{p.lat},0</coordinates></Point></Placemark>"
        )
    kml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>{escape(ext.nombre)}</name>"
        '<Style id="linea"><LineStyle><color>ff0000ff</color><width>3</width></LineStyle></Style>'
        '<Style id="poste"><IconStyle><scale>0.7</scale></IconStyle></Style>'
        '<Style id="arranque"><IconStyle><scale>1.1</scale></IconStyle></Style>'
        f"<Placemark><name>Red MT {escape(ext.conductor)}</name>"
        f"<description>{ext.tension_kv} kV · {ext.fases}F · {redondear(red.longitud_m, 1)} m"
        f"</description><styleUrl>#linea</styleUrl>"
        f"<LineString><tessellate>1</tessellate><coordinates>{coordenadas}</coordinates>"
        "</LineString></Placemark>" + "".join(marcas) + "</Document></kml>\n"
    )
    return kml.encode("utf-8")
