"""Genera los planos de prueba de una vivienda de dos plantas de 10 × 8 m.

Un DXF por planta, con las mismas coordenadas: la escalera y los muros
exteriores coinciden, así el tablero principal y los subtableros quedan
alineados en vertical. Como el ejemplo de una planta, son planos sintéticos
dibujados a la manera de un arquitecto (muros de doble línea, puertas con
arco, ventanas, textos y mobiliario).

    python generar_planos.py        # reescribe planta-baja.dxf y planta-alta.dxf
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from shapely.geometry import LineString, box
from shapely.ops import unary_union

E = 0.15  # espesor de muro, m
PERIMETRO = [(0, 0, 10, 0), (10, 0, 10, 8), (10, 8, 0, 8), (0, 8, 0, 0)]

PLANTAS = {
    "planta-baja.dxf": {
        "titulo": "PLANTA BAJA  ESC 1:100",
        "muros": [*PERIMETRO, (0, 5, 6, 5), (6, 0, 6, 8), (6, 4, 10, 4), (8, 4, 8, 8),
                  (2.5, 5, 2.5, 8)],
        # (x, y) de la bisagra, dirección del vano, sentido, ancho, lado al que abre.
        "puertas": [
            (2.0, 0, "x", +1, 1.0, +1),    # entrada principal → sala
            (6, 1.5, "y", +1, 0.9, +1),    # sala → cocina
            (0.8, 5, "x", +1, 0.9, +1),    # sala → escalera
            (4.0, 5, "x", +1, 0.8, +1),    # sala → estudio
            (6.6, 4, "x", +1, 0.8, +1),    # cocina → lavandería
            (8.6, 4, "x", +1, 0.7, +1),    # cocina → baño social
            (6.5, 8, "x", +1, 0.8, -1),    # puerta posterior → lavandería
        ],
        "ventanas": [(3.5, 0, "x", 1.6), (7.5, 0, "x", 1.4), (0, 2, "y", 1.8),
                     (10, 1.5, "y", 1.2), (10, 6, "y", 0.6), (3.5, 8, "x", 1.5),
                     (0, 6, "y", 1.2)],
        "ambientes": [("SALA - COMEDOR", 3.0, 2.6), ("COCINA", 8.0, 2.0),
                      ("LAVANDERÍA", 7.0, 6.2), ("BAÑO SOCIAL", 9.0, 6.2),
                      ("ESCALERA", 1.25, 6.8), ("ESTUDIO", 4.25, 6.6)],
        "mobiliario": [(0.5, 0.5, 2.5, 1.4), (3.0, 3.0, 5.0, 4.2), (6.3, 0.2, 9.7, 0.8)],
    },
    "planta-alta.dxf": {
        "titulo": "PLANTA ALTA  ESC 1:100",
        "muros": [*PERIMETRO, (0, 4, 10, 4), (0, 5, 10, 5), (5, 0, 5, 4), (7, 0, 7, 4),
                  (2.5, 5, 2.5, 8), (7, 5, 7, 8)],
        "puertas": [
            (3.5, 4, "x", +1, 0.9, -1),    # hall → dormitorio master
            (5, 1.0, "y", +1, 0.7, +1),    # master → baño master
            (8.0, 4, "x", +1, 0.9, -1),    # hall → dormitorio 2
            (4.0, 5, "x", +1, 0.9, +1),    # hall → dormitorio 3
            (8.0, 5, "x", +1, 0.7, +1),    # hall → baño
            (0.8, 5, "x", +1, 0.9, +1),    # hall → escalera
        ],
        "ventanas": [(1.5, 0, "x", 2.0), (8.0, 0, "x", 1.4), (5.7, 0, "x", 0.6),
                     (4.0, 8, "x", 1.6), (8.5, 8, "x", 0.6), (0, 6, "y", 1.2),
                     (10, 2, "y", 1.2)],
        "ambientes": [("DORMITORIO MASTER", 2.5, 2.4), ("BAÑO MASTER", 6.0, 2.6),
                      ("DORMITORIO 2", 8.5, 2.4), ("HALL", 5.0, 4.5),
                      ("ESCALERA", 1.25, 6.8), ("DORMITORIO 3", 4.75, 6.6),
                      ("BAÑO", 8.5, 6.6)],
        "mobiliario": [(0.6, 0.4, 2.6, 2.4), (7.6, 0.4, 9.4, 2.2), (3.0, 6.2, 4.6, 7.8)],
    },
}


def _vano(x: float, y: float, direccion: str, sentido: int, ancho: float):
    if direccion == "x":
        x2 = x + sentido * ancho
        return box(min(x, x2), y - E, max(x, x2), y + E)
    y2 = y + sentido * ancho
    return box(x - E, min(y, y2), x + E, max(y, y2))


def generar(destino: Path, planta: dict) -> None:  # type: ignore[type-arg]
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.M
    for nombre, color in [("A-MUROS", 7), ("A-PUERTAS", 3), ("A-VENTANAS", 5),
                          ("A-TEXTOS", 2), ("A-MOBILIARIO", 9)]:
        doc.layers.add(nombre, color=color)
    msp = doc.modelspace()

    macizo = unary_union(
        [LineString([(a, b), (c, d)]).buffer(E / 2, cap_style="square", join_style="mitre")
         for a, b, c, d in planta["muros"]]
    )
    vanos = [_vano(x, y, d, s, a) for x, y, d, s, a, _ in planta["puertas"]]
    vanos += [_vano(x, y, d, +1, a) for x, y, d, a in planta["ventanas"]]
    macizo = macizo.difference(unary_union(vanos))
    partes = list(macizo.geoms) if macizo.geom_type == "MultiPolygon" else [macizo]
    for parte in partes:
        for anillo in [parte.exterior, *parte.interiors]:
            puntos = list(anillo.coords)
            for p, q in zip(puntos, puntos[1:]):
                msp.add_line(p, q, dxfattribs={"layer": "A-MUROS"})

    for x, y, direccion, sentido, ancho, abre in planta["puertas"]:
        if direccion == "x":
            bisagra = (x, y + abre * E / 2)
            hoja = (x, bisagra[1] + abre * ancho)
            inicio, fin = (0, 90) if (sentido, abre) == (1, 1) else (270, 360)
        else:
            bisagra = (x + abre * E / 2, y)
            hoja = (bisagra[0] + abre * ancho, y)
            inicio, fin = (0, 90) if (sentido, abre) == (1, 1) else (90, 180)
        msp.add_line(bisagra, hoja, dxfattribs={"layer": "A-PUERTAS"})
        msp.add_arc(bisagra, ancho, inicio, fin, dxfattribs={"layer": "A-PUERTAS"})

    for x, y, direccion, ancho in planta["ventanas"]:
        for d in (-E / 2, 0, E / 2):
            if direccion == "x":
                msp.add_line((x, y + d), (x + ancho, y + d), dxfattribs={"layer": "A-VENTANAS"})
            else:
                msp.add_line((x + d, y), (x + d, y + ancho), dxfattribs={"layer": "A-VENTANAS"})

    centro = ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
    for nombre, x, y in planta["ambientes"]:
        msp.add_text(nombre, height=0.18, dxfattribs={"layer": "A-TEXTOS"}).set_placement(
            (x, y), align=centro
        )
    for a, b, c, d in planta["mobiliario"]:
        msp.add_lwpolyline([(a, b), (c, b), (c, d), (a, d)], close=True,
                           dxfattribs={"layer": "A-MOBILIARIO"})
    # Peldaños de la escalera.
    for k in range(1, 8):
        y = 5 + k * 3 / 8
        msp.add_line((0.15, y), (2.35, y), dxfattribs={"layer": "A-MOBILIARIO"})
    msp.add_text(planta["titulo"], height=0.25, dxfattribs={"layer": "A-TEXTOS"}).set_placement(
        (5, -1.0), align=centro
    )
    doc.saveas(destino)


if __name__ == "__main__":
    for archivo, planta in PLANTAS.items():
        salida = Path(__file__).with_name(archivo)
        generar(salida, planta)
        print(f"escrito {salida}")
