"""Generación del DXF de salida (RF-29).

El plano del arquitecto queda como referencia en gris y la instalación se
escribe en capas propias `E-*`. El archivo original no se toca: se trabaja
sobre una copia en memoria. Al terminar, el resultado se vuelve a abrir y se
audita; si tiene errores, no se entrega.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from decimal import Decimal

from ezdxf import recover
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace

from electric.calculo.cuadro import cuadro_de_cargas, resumen
from electric.calculo.motor import Calculado
from electric.errores import DatoInvalido, ErrorElectric
from electric.modelo.entidades import Proyecto
from electric.perfiles.carga import Perfil

AVISO = "BORRADOR sujeto a revisión y firma de un profesional habilitado"
GRIS = 8

#: Capa → (color ACI, descripción). No hay norma ecuatoriana de capas: son configurables.
CAPAS: dict[str, tuple[int, str]] = {
    "E-ILUM": (2, "Luminarias e interruptores"),
    "E-TOMA": (4, "Tomacorrientes"),
    "E-ESPE": (6, "Cargas especiales"),
    "E-TABL": (1, "Tableros"),
    "E-CIRC": (3, "Recorridos de circuitos"),
    "E-TEXT": (7, "Textos, leyenda y cuadro de cargas"),
}
COLORES_CIRCUITO = (1, 3, 5, 6, 30, 4, 200, 94, 2, 140)

R = 0.12  # radio de símbolo, en metros


def _bloques(doc: Drawing, f: float) -> None:
    """Símbolos como bloques con atributos (ID, circuito, potencia, altura)."""
    r = R / f

    def nuevo(nombre: str):  # type: ignore[no-untyped-def]
        bloque = doc.blocks.new(nombre)
        for n, etiqueta in enumerate(("ID", "CIRCUITO", "POTENCIA", "ALTURA")):
            bloque.add_attdef(
                etiqueta,
                (r * 1.4, r * (0.6 - n * 0.9)),
                dxfattribs={"height": r * 0.7, "invisible": 1},
            )
        return bloque

    luz = nuevo("E_LUMINARIA")
    luz.add_circle((0, 0), r)
    luz.add_line((-r * 0.7, -r * 0.7), (r * 0.7, r * 0.7))
    luz.add_line((-r * 0.7, r * 0.7), (r * 0.7, -r * 0.7))

    toma = nuevo("E_TOMACORRIENTE")
    toma.add_circle((0, 0), r)
    toma.add_line((-r * 0.45, -r * 0.6), (-r * 0.45, r * 0.6))
    toma.add_line((r * 0.45, -r * 0.6), (r * 0.45, r * 0.6))

    interruptor = nuevo("E_INTERRUPTOR")
    interruptor.add_circle((0, 0), r * 0.6)
    interruptor.add_line((r * 0.42, r * 0.42), (r * 1.3, r * 1.3))
    interruptor.add_line((r * 1.3, r * 1.3), (r * 1.7, r * 0.9))

    especial = nuevo("E_ESPECIAL")
    especial.add_lwpolyline([(-r, -r), (r, -r), (r, r), (-r, r)], close=True)
    especial.add_line((-r, -r), (r, r))

    tablero = nuevo("E_TABLERO")
    tablero.add_lwpolyline([(-r * 2, -r), (r * 2, -r), (r * 2, r), (-r * 2, r)], close=True)
    tablero.add_solid([(-r * 2, -r), (r * 2, -r), (-r * 2, r)])


def _texto(
    msp: Modelspace,
    texto: str,
    x: float,
    y: float,
    alto: float,
    capa: str = "E-TEXT",
    alineacion: TextEntityAlignment = TextEntityAlignment.LEFT,
) -> None:
    msp.add_text(texto, height=alto, dxfattribs={"layer": capa}).set_placement(
        (x, y), align=alineacion
    )


def _tabla(
    msp: Modelspace, filas: Sequence[tuple[str, ...]], x: float, y: float, alto: float
) -> float:
    """Dibuja una tabla de texto con líneas; devuelve la coordenada y de su borde inferior."""
    anchos = [
        max(len(f[n]) for f in filas) * alto * 0.85 + alto * 1.6 for n in range(len(filas[0]))
    ]
    paso = alto * 2.1
    total = sum(anchos)
    for n, fila in enumerate(filas):
        cx = x
        for celda, ancho in zip(fila, anchos, strict=True):
            _texto(msp, celda, cx + alto * 0.7, y - paso * n - paso * 0.72, alto)
            cx += ancho
    for n in range(len(filas) + 1):
        msp.add_line((x, y - paso * n), (x + total, y - paso * n), dxfattribs={"layer": "E-TEXT"})
    cx = x
    for ancho in [0.0, *anchos]:
        cx += ancho
        msp.add_line((cx, y), (cx, y - paso * len(filas)), dxfattribs={"layer": "E-TEXT"})
    return y - paso * len(filas)


def generar_dxf(
    original: bytes, proyecto: Proyecto, calculado: Calculado | None, perfil: Perfil
) -> bytes:
    """DXF con el plano original en gris y la instalación en capas `E-*`."""
    plano = proyecto.plano
    if plano is None or not plano.ubicaciones:
        raise DatoInvalido("el proyecto no tiene una instalación diseñada sobre un plano")
    try:
        doc, _ = recover.read(io.BytesIO(original))
    except Exception as error:  # noqa: BLE001 - cualquier fallo de lectura es el mismo problema
        raise DatoInvalido(f"no se pudo leer el plano original: {error}") from error

    f = float(plano.factor_a_metros)  # unidades del dibujo → metros
    msp = doc.modelspace()
    for capa_original in doc.layers:
        capa_original.color = GRIS
    for entidad in msp:
        if entidad.dxf.hasattr("color"):
            entidad.dxf.discard("color")
    for nombre, (color, _) in CAPAS.items():
        if nombre not in doc.layers:
            doc.layers.add(nombre, color=color)
    if "DASHED" not in doc.linetypes:
        doc.linetypes.add("DASHED", pattern=[0.6 / f, 0.4 / f, -0.2 / f], description="Dashed")
    _bloques(doc, f)

    def u(valor: Decimal) -> float:
        return float(valor) / f

    alto = 0.13 / f
    circuito_de = {p.id: p.circuito for p in proyecto.puntos}
    circuito_de.update({c.id: c.circuito for c in proyecto.cargas_especiales})
    tipo_de = {p.id: p.tipo for p in proyecto.puntos}
    tipo_de.update({c.id: c.tipo for c in proyecto.cargas_especiales})
    especiales = {c.id for c in proyecto.cargas_especiales}
    orden = {c.id: n for n, c in enumerate(proyecto.circuitos)}

    def potencia(id: str) -> str:
        if calculado is None or id not in circuito_de:
            return ""
        valor = calculado.res("RC-01", circuito_de[id]).entradas.get(id)
        return f"{valor} W" if valor is not None else ""

    # Recorridos, uno por circuito, con su etiqueta en el primer tramo.
    for recorrido in plano.recorridos:
        color = COLORES_CIRCUITO[orden.get(recorrido.circuito, 0) % len(COLORES_CIRCUITO)]
        puntos = [(u(p.x), u(p.y)) for p in recorrido.puntos]
        msp.add_lwpolyline(puntos, dxfattribs={"layer": "E-CIRC", "color": color})
        for a, b in recorrido.derivaciones:
            msp.add_line(
                (u(a.x), u(a.y)),
                (u(b.x), u(b.y)),
                dxfattribs={"layer": "E-CIRC", "color": color, "linetype": "DASHED"},
            )
        if len(puntos) > 1:
            ultimo = puntos[-1]
            _texto(msp, recorrido.circuito, ultimo[0] + alto, ultimo[1] + alto, alto, "E-CIRC")

    for ubicacion in plano.ubicaciones:
        x, y = u(ubicacion.x), u(ubicacion.y)
        if ubicacion.id == proyecto.tablero.id:
            bloque, capa = "E_TABLERO", "E-TABL"
        elif ubicacion.id in especiales:
            bloque, capa = "E_ESPECIAL", "E-ESPE"
        elif tipo_de.get(ubicacion.id) == "punto_luz":
            bloque, capa = "E_LUMINARIA", "E-ILUM"
        else:
            bloque, capa = "E_TOMACORRIENTE", "E-TOMA"
        insercion = msp.add_blockref(bloque, (x, y), dxfattribs={"layer": capa})
        insercion.add_auto_attribs(
            {
                "ID": ubicacion.id,
                "CIRCUITO": circuito_de.get(ubicacion.id, ""),
                "POTENCIA": potencia(ubicacion.id),
                "ALTURA": f"{ubicacion.altura_m} m",
            }
        )
        if ubicacion.id == proyecto.tablero.id:
            _texto(msp, ubicacion.id, x + alto * 2.2, y + alto, alto, "E-TABL")
        elif ubicacion.id in especiales:
            _texto(
                msp,
                tipo_de[ubicacion.id].upper(),
                x + alto * 1.4,
                y - alto * 0.4,
                alto * 0.8,
                "E-ESPE",
            )
    for interruptor in plano.interruptores:
        insercion = msp.add_blockref(
            "E_INTERRUPTOR", (u(interruptor.x), u(interruptor.y)), dxfattribs={"layer": "E-ILUM"}
        )
        insercion.add_auto_attribs(
            {
                "ID": interruptor.id,
                "CIRCUITO": interruptor.circuito,
                "POTENCIA": "",
                "ALTURA": f"{interruptor.altura_m} m",
            }
        )

    # A la derecha del plano: aviso, resumen, leyenda y cuadro de cargas.
    xs = [u(p.x) for a in plano.ambientes for p in a.poligono]
    ys = [u(p.y) for a in plano.ambientes for p in a.poligono]
    x0, y = max(xs) + 1.5 / f, max(ys)
    _texto(msp, AVISO, x0, y, alto * 1.3)
    y -= alto * 3
    _texto(msp, f"{proyecto.nombre} · perfil {perfil.meta.id} {perfil.meta.version}", x0, y, alto)
    y -= alto * 3
    if calculado is not None:
        for dato in resumen(calculado, perfil):
            _texto(msp, f"{dato.etiqueta}: {dato.texto}", x0, y, alto)
            y -= alto * 1.9
        y -= alto
        _texto(msp, "CUADRO DE CARGAS", x0, y, alto * 1.2)
        y -= alto * 1.2
        encabezado = (
            "Circuito",
            "Tipo",
            "Fase",
            "Carga",
            "Corriente",
            "Breaker",
            "Conductor",
            "Tierra",
            "Ducto",
            "Longitud",
            "Caída",
        )
        filas = [encabezado] + [
            (
                fila.circuito,
                fila.tipo,
                fila.fase,
                fila.carga,
                fila.corriente,
                fila.breaker,
                fila.conductor,
                fila.tierra,
                fila.ducto,
                fila.longitud,
                fila.caida,
            )
            for fila in cuadro_de_cargas(calculado, perfil)
        ]
        y = _tabla(msp, filas, x0, y, alto) - alto * 3
    _texto(msp, "LEYENDA", x0, y, alto * 1.2)
    y -= alto * 3
    for bloque, capa, nombre in (
        ("E_LUMINARIA", "E-ILUM", "Luminaria de techo"),
        ("E_INTERRUPTOR", "E-ILUM", "Interruptor"),
        ("E_TOMACORRIENTE", "E-TOMA", "Tomacorriente"),
        ("E_ESPECIAL", "E-ESPE", "Carga especial"),
        ("E_TABLERO", "E-TABL", "Tablero de distribución"),
    ):
        msp.add_blockref(bloque, (x0 + alto * 2, y + alto * 0.4), dxfattribs={"layer": capa})
        _texto(msp, nombre, x0 + alto * 5, y, alto)
        y -= alto * 2.6

    return _verificado(doc)


def _verificado(doc: Drawing) -> bytes:
    """Escribe el DXF, lo vuelve a abrir y comprueba que no tenga errores."""
    auditor = doc.audit()
    if auditor.has_errors:
        raise ErrorElectric(f"el DXF generado tiene {len(auditor.errors)} errores de entidades")
    salida = io.StringIO()
    doc.write(salida)
    contenido = salida.getvalue().encode(doc.output_encoding, errors="replace")
    try:
        _, revision = recover.read(io.BytesIO(contenido))
    except Exception as error:  # noqa: BLE001
        raise ErrorElectric(f"el DXF generado no se pudo volver a abrir: {error}") from error
    if revision.has_errors:
        raise ErrorElectric("el DXF generado tiene errores al volver a abrirlo")
    return contenido
