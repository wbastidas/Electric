"""Plano esquemático de la urbanización en DXF: manzanas y lotes, calles, red de
media tensión por la avenida lateral, transformadores por sector, circuitos de
baja tensión y luminarias, con el cuadro de sectores."""

from __future__ import annotations

from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace

from electric.industrial.analisis import _t
from electric.salida_cad.dxf import _verificado
from electric.urbanizacion.calculo import UrbanizacionCalculada, _filas

CAPAS = {
    "A-LOTES": 8,
    "A-CALLES": 9,
    "E-MT": 1,
    "E-BT": 3,
    "E-TRAFO": 6,
    "E-AP": 2,
    "E-TEXTO": 7,
}


def _texto(msp: Modelspace, texto: str, x: float, y: float, alto: float,
           capa: str = "E-TEXTO", centro: bool = False) -> None:  # fmt: skip
    t = msp.add_text(texto, height=alto, dxfattribs={"layer": capa})
    t.set_placement(
        (x, y), align=TextEntityAlignment.MIDDLE_CENTER if centro else TextEntityAlignment.LEFT
    )


def generar_plano_urbanizacion(c: UrbanizacionCalculada) -> bytes:
    doc = Drawing.new("R2010")
    doc.units = 6  # metros
    doc.header["$INSUNITS"] = 6
    for capa, color in CAPAS.items():
        doc.layers.add(capa, color=color)
    msp = doc.modelspace()
    u = c.urbanizacion
    w = float(u.ancho_calle_m)
    ancho = max(float(m.frente_m) * _filas(m.lotes)[0] for m in u.manzanas)
    # y del eje de cada calle, de arriba hacia abajo.
    ejes: list[float] = []
    y = 0.0
    for m in u.manzanas:
        ejes.append(y - w / 2)
        y -= w
        f, fondo = float(m.frente_m), float(m.fondo_m)
        norte, sur = _filas(m.lotes)
        n = 1
        for fila, cantidad in ((0, norte), (1, sur)):
            y0 = y - fila * fondo
            for col in range(cantidad):
                x0 = col * f
                msp.add_lwpolyline([(x0, y0), (x0 + f, y0), (x0 + f, y0 - fondo), (x0, y0 - fondo)],
                                   close=True, dxfattribs={"layer": "A-LOTES"})  # fmt: skip
                _texto(
                    msp, str(n), x0 + f / 2, y0 - fondo / 2, min(f, fondo) * 0.18, "A-LOTES", True
                )
                n += 1
        _texto(msp, f"MZ {m.id}", ancho + 3, y - fondo, 2.0)
        y -= 2 * fondo
    ejes.append(y - w / 2)
    y_fin = y - w
    # Calles y avenida lateral.
    for eje in ejes:
        for borde in (eje + w / 2, eje - w / 2):
            msp.add_line((-w, borde), (ancho + 2, borde), dxfattribs={"layer": "A-CALLES"})
    msp.add_line((-w, 0), (-w, y_fin), dxfattribs={"layer": "A-CALLES"})
    # Red de MT por la avenida y por cada calle con transformadores.
    x_mt = -w / 2
    con_trafo = sorted({s.calle for s in c.sectores})
    if con_trafo:
        msp.add_line((x_mt, ejes[0] + w), (x_mt, ejes[con_trafo[-1]]), dxfattribs={"layer": "E-MT"})
        _texto(msp, f"MT {_t(c.tension_mt_kv, 1)} kV", x_mt + 0.5, ejes[0] + w * 0.8, 1.8, "E-MT")
    for k in con_trafo:
        ultimo = max(s.x for s in c.sectores if s.calle == k)
        msp.add_line((x_mt, ejes[k] + 1.5), (ultimo, ejes[k] + 1.5), dxfattribs={"layer": "E-MT"})
    # Transformadores y circuitos de BT.
    for s in c.sectores:
        ye = ejes[s.calle]
        msp.add_circle((s.x, ye + 1.5), 1.2, dxfattribs={"layer": "E-TRAFO"})
        kva = f"{_t(s.kva, 1)} kVA" if s.kva else "sin trafo"
        _texto(msp, f"{s.id} {kva}", s.x + 1.5, ye + 3.2, 1.6, "E-TRAFO")
        for circ in s.circuitos:
            signo = -1 if circ.lado == "izquierda" else 1
            fin = s.x + signo * float(circ.longitud_m)
            msp.add_line((s.x, ye - 1.5), (fin, ye - 1.5), dxfattribs={"layer": "E-BT"})
            calibre = circ.conductor.texto if circ.conductor else "sin solución"
            _texto(msp, f"{calibre} · {_t(circ.longitud_m, 0)} m", (s.x + fin) / 2 - 4, ye - 3.5,
                   1.1, "E-BT")  # fmt: skip
    # Alumbrado público.
    for calle in c.calles:
        for i, x in enumerate(calle.luminarias):
            yy = ejes[calle.numero] + (w / 2 - 0.8) * (1 if i % 2 else -1)
            msp.add_circle((x, yy), 0.5, dxfattribs={"layer": "E-AP"})
    # Cuadro de sectores.
    x0, yy = ancho + 25, 0.0
    _texto(msp, "CUADRO DE TRANSFORMADORES", x0, yy, 2.2)
    yy -= 4
    for s in c.sectores:
        _texto(msp, f"{s.id} · calle {s.calle} · {len(s.lotes)} lotes · {s.luminarias} lum. · "
               f"D {_t(s.demanda_kva, 1)} kVA · {_t(s.kva, 1) if s.kva else '—'} kVA",
               x0, yy, 1.5)  # fmt: skip
        yy -= 2.6
    yy -= 2
    for linea in (
        f"{len(c.lotes)} lotes, estrato {u.estrato}, DMU {_t(c.dmu_kva, 1)} kVA",
        f"Demanda en MT {_t(c.demanda_kva, 1)} kVA, I = {_t(c.corriente_mt_a, 2)} A",
        f"Transformadores instalados {_t(c.kva_instalados, 1)} kVA",
        f"Alumbrado público {sum(len(k.luminarias) for k in c.calles)} luminarias, "
        f"{_t(c.alumbrado_kva, 2)} kVA",
        u.nombre.upper(),
        "PLANO ESQUEMÁTICO — BORRADOR, REQUIERE REVISIÓN Y FIRMA",
    ):
        _texto(msp, linea, x0, yy, 1.8)
        yy -= 3
    return _verificado(doc)
