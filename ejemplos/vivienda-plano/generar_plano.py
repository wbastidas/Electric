"""Genera el plano de prueba `planta.dxf`: una vivienda de una planta de 12 × 10 m.

Es un plano sintético, dibujado como lo haría un arquitecto: muros de doble
línea con vanos, puertas con hoja y arco, ventanas, nombres de ambientes,
mobiliario y textos que no son ambientes. Sirve de caso de prueba fijo para la
lectura del plano y el diseño automático; no reemplaza a planos reales.

    python generar_plano.py        # reescribe planta.dxf
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
from shapely.geometry import LineString, box
from shapely.ops import unary_union

E = 0.15  # espesor de muro, m

# Ejes de muro (x1, y1, x2, y2), en metros.
MUROS = [
    (0, 0, 12, 0), (12, 0, 12, 10), (12, 10, 0, 10), (0, 10, 0, 0),  # perímetro
    (0, 5, 4, 5), (4, 5, 12, 5),      # sala y cocina / dormitorio 1 y pasillo
    (4, 6, 12, 6),                     # pasillo / dormitorios
    (4, 5, 4, 10),                     # dormitorio 1 / pasillo y baño
    (6, 6, 6, 10), (9, 6, 9, 10),      # baño / dormitorio 2 / dormitorio 3
    (6.5, 0, 6.5, 5),                  # sala / cocina
    (9.5, 0, 9.5, 5),                  # cocina / baño social y lavandería
    (9.5, 2.5, 12, 2.5),               # lavandería / baño social
]

# Puertas: (x, y) de la bisagra sobre el eje, dirección del vano, ancho y lado al que abre.
# dirección: "x" o "y"; sentido: +1 o -1 a lo largo del muro; abre: +1 o -1 perpendicular.
PUERTAS = [
    (1.0, 0, "x", +1, 1.0, +1),     # entrada principal, abre hacia la sala
    (5.0, 5, "x", +1, 0.9, -1),     # pasillo → sala
    (4, 5.1, "y", +1, 0.8, -1),     # pasillo → dormitorio 1
    (4.6, 6, "x", +1, 0.7, +1),     # pasillo → baño
    (6.6, 6, "x", +1, 0.8, +1),     # pasillo → dormitorio 2
    (9.6, 6, "x", +1, 0.8, +1),     # pasillo → dormitorio 3
    (10.3, 5, "x", +1, 0.7, -1),    # pasillo → baño social
    (6.5, 1.5, "y", +1, 0.9, +1),   # sala → cocina
    (9.5, 0.8, "y", +1, 0.8, +1),   # cocina → lavandería
]

# Ventanas: (x, y) de inicio sobre el eje, dirección y ancho.
VENTANAS = [
    (3.0, 0, "x", 2.0), (7.3, 0, "x", 1.4), (10.3, 0, "x", 1.0),
    (0, 1.5, "y", 2.0), (0, 6.8, "y", 1.8),
    (1.2, 10, "x", 1.6), (4.7, 10, "x", 0.6), (6.8, 10, "x", 1.4), (9.8, 10, "x", 1.4),
    (12, 3.4, "y", 0.6),
]

AMBIENTES = [
    ("SALA - COMEDOR", 3.2, 2.6), ("COCINA", 8.0, 2.8), ("LAVANDERÍA", 10.75, 1.3),
    ("BAÑO SOCIAL", 10.75, 4.1), ("PASILLO", 8.0, 5.5), ("DORMITORIO MASTER", 2.0, 7.6),
    ("BAÑO", 5.0, 8.4), ("DORMITORIO 2", 7.5, 8.2), ("DORMITORIO 3", 10.5, 8.2),
]


def _vano(x: float, y: float, direccion: str, sentido: int, ancho: float):
    """Rectángulo que abre el muro en el vano."""
    if direccion == "x":
        x2 = x + sentido * ancho
        return box(min(x, x2), y - E, max(x, x2), y + E)
    y2 = y + sentido * ancho
    return box(x - E, min(y, y2), x + E, max(y, y2))


def generar(destino: Path) -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.M
    for nombre, color in [
        ("A-MUROS", 7), ("A-PUERTAS", 3), ("A-VENTANAS", 5),
        ("A-TEXTOS", 2), ("A-MOBILIARIO", 9), ("A-COTAS", 1),
    ]:
        doc.layers.add(nombre, color=color)
    msp = doc.modelspace()

    macizo = unary_union(
        [LineString([(a, b), (c, d)]).buffer(E / 2, cap_style="square", join_style="mitre")
         for a, b, c, d in MUROS]
    )
    vanos = [_vano(x, y, d, s, a) for x, y, d, s, a, _ in PUERTAS]
    vanos += [_vano(x, y, d, +1, a) for x, y, d, a in VENTANAS]
    macizo = macizo.difference(unary_union(vanos))

    # Muros: el contorno de cada tramo macizo, línea por línea.
    partes = list(macizo.geoms) if macizo.geom_type == "MultiPolygon" else [macizo]
    for parte in partes:
        for anillo in [parte.exterior, *parte.interiors]:
            puntos = list(anillo.coords)
            for p, q in zip(puntos, puntos[1:]):
                msp.add_line(p, q, dxfattribs={"layer": "A-MUROS"})

    # Puertas: hoja abierta a 90° y arco de barrido, con la bisagra en la cara del muro.
    for x, y, direccion, sentido, ancho, abre in PUERTAS:
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

    # Ventanas: las dos caras del muro y el vidrio al centro.
    for x, y, direccion, ancho in VENTANAS:
        for d in (-E / 2, 0, E / 2):
            if direccion == "x":
                msp.add_line((x, y + d), (x + ancho, y + d), dxfattribs={"layer": "A-VENTANAS"})
            else:
                msp.add_line((x + d, y), (x + d, y + ancho), dxfattribs={"layer": "A-VENTANAS"})

    for nombre, x, y in AMBIENTES:
        msp.add_text(nombre, height=0.18, dxfattribs={"layer": "A-TEXTOS"}).set_placement(
            (x, y), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
        )

    # Ruido realista: mobiliario, una cota y el rótulo de la lámina.
    for a, b, c, d in [(0.4, 7.0, 2.2, 9.0), (6.4, 8.6, 7.8, 9.8), (9.4, 8.6, 10.8, 9.8),
                       (7.0, 0.2, 9.3, 0.8), (1.0, 2.0, 3.0, 2.9)]:
        msp.add_lwpolyline([(a, b), (c, b), (c, d), (a, d)], close=True,
                           dxfattribs={"layer": "A-MOBILIARIO"})
    msp.add_circle((5.0, 9.3), 0.25, dxfattribs={"layer": "A-MOBILIARIO"})
    msp.add_text("12.00", height=0.15, dxfattribs={"layer": "A-COTAS"}).set_placement(
        (6, -0.6), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
    )
    msp.add_line((0, -0.4), (12, -0.4), dxfattribs={"layer": "A-COTAS"})
    msp.add_text("PLANTA BAJA  ESC 1:100", height=0.25, dxfattribs={"layer": "A-TEXTOS"}).set_placement(
        (6, -1.3), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
    )
    doc.saveas(destino)


if __name__ == "__main__":
    salida = Path(__file__).with_name("planta.dxf")
    generar(salida)
    print(f"escrito {salida}")
