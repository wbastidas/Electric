"""Genera el plano de ejemplo de una nave industrial (nave.dxf) y su cuadro (cuadro.csv).

Nave de 48 × 24 m en metros. Los tableros y las máquinas se marcan con su
código: algunos como bloques con atributo y otros como texto, para mostrar
las dos formas que reconoce Electric.

    python generar_plano.py
"""

from __future__ import annotations

from pathlib import Path

import ezdxf

AQUI = Path(__file__).parent

TABLEROS = {"TP": (2, 2), "TD-1": (14, 22), "TD-2": (34, 22), "TD-3": (46, 2)}
MAQUINAS = [
    # código, descripción, tipo, kW, tablero, posición
    ("M-1", "Compresor de tornillo", "motor", 30, "TD-1", (6, 16)),
    ("M-2", "Torno CNC", "motor", 15, "TD-1", (12, 12)),
    ("M-3", "Fresadora", "motor", 11, "TD-1", (20, 14)),
    ("M-4", "Prensa hidráulica", "motor", 22, "TD-2", (28, 15)),
    ("M-5", "Puente grúa", "motor", 15, "TD-2", (40, 18)),
    ("S-1", "Soldadora", "soldadora", 12, "TD-2", (36, 8)),
    ("H-1", "Horno de secado", "resistiva", 25, "TD-3", (42, 10)),
    ("IL-1", "Iluminación de la nave", "iluminacion", 6, "TD-3", (24, 4)),
]


def main() -> None:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6  # metros
    msp = doc.modelspace()
    doc.layers.add("A-MUROS", color=8)
    doc.layers.add("E-TABLEROS", color=1)
    doc.layers.add("E-MAQUINAS", color=5)
    msp.add_lwpolyline([(0, 0), (48, 0), (48, 24), (0, 24)], close=True, dxfattribs={"layer": "A-MUROS"})
    msp.add_lwpolyline([(0.2, 0.2), (47.8, 0.2), (47.8, 23.8), (0.2, 23.8)], close=True,
                       dxfattribs={"layer": "A-MUROS"})  # fmt: skip
    msp.add_text("NAVE INDUSTRIAL DE EJEMPLO - 48 x 24 m", height=0.6,
                 dxfattribs={"layer": "A-MUROS"}).set_placement((1, 25))  # fmt: skip

    tablero = doc.blocks.new("TABLERO")
    tablero.add_lwpolyline([(-0.4, -0.2), (0.4, -0.2), (0.4, 0.2), (-0.4, 0.2)], close=True)
    tablero.add_attdef("CODIGO", (0.5, 0), height=0.35)
    for codigo, (x, y) in TABLEROS.items():
        bloque = msp.add_blockref("TABLERO", (x, y), dxfattribs={"layer": "E-TABLEROS"})
        bloque.add_auto_attribs({"CODIGO": codigo})

    for n, (codigo, desc, _, _, _, (x, y)) in enumerate(MAQUINAS):
        msp.add_lwpolyline([(x - 1, y - 0.8), (x + 1, y - 0.8), (x + 1, y + 0.8), (x - 1, y + 0.8)],
                           close=True, dxfattribs={"layer": "E-MAQUINAS"})  # fmt: skip
        # Mitad con el código como texto suelto, mitad como «código descripción».
        texto = codigo if n % 2 else f"{codigo} {desc}"
        msp.add_text(texto, height=0.35, dxfattribs={"layer": "E-MAQUINAS"}).set_placement((x, y))
    doc.saveas(AQUI / "nave.dxf")

    lineas = ["Código,Descripción,Tipo,Potencia,Tablero"]
    lineas += [f"{c},{d},{t},{kw},{tab}" for c, d, t, kw, tab, _ in MAQUINAS]
    (AQUI / "cuadro.csv").write_text("\n".join(lineas) + "\n", "utf-8")


if __name__ == "__main__":
    main()
