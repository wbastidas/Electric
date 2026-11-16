"""Detección de ambientes a partir de los muros del plano.

Método: se cierran los vanos de las puertas, se arman los polígonos que forman
muros y ventanas, y se descartan los que son el interior de un muro (demasiado
angostos para ser un ambiente). El uso sale del texto que cae dentro de cada
polígono, comparado con las plantillas del perfil.

Lo que no se puede resolver queda como bandera para el usuario (RF-14).
"""

from __future__ import annotations

import math
import re
from decimal import Decimal

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from electric.ingesta.dxf import Arco, PlanoLeido, Segmento, sin_tildes
from electric.modelo.plano import Ambiente, Plano, Pt, Puerta, cm, mm
from electric.perfiles.carga import Perfil

#: Un polígono que no admite un círculo de este radio es el interior de un muro.
RADIO_MINIMO_M = 0.25
AREA_MINIMA_M2 = 1.0
TOLERANCIA_M = 0.03
ESPESOR_MAX_M = 0.5

Coord = tuple[float, float]


def _dist(a: Coord, b: Coord) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cierres_de_puerta(arco: Arco, muros: list[Segmento]) -> list[tuple[Coord, Coord]] | None:
    """Segmentos que cierran el vano de una puerta, en ambas caras del muro.

    La bisagra es el centro del arco; el otro marco es el extremo del arco que
    toca el final de un muro. El marco en la bisagra da el espesor del muro.
    """
    finales = [(s.x1, s.y1) for s in muros] + [(s.x2, s.y2) for s in muros]
    centro = (arco.cx, arco.cy)
    candidatos = sorted(arco.extremos(), key=lambda p: min(_dist(p, f) for f in finales))
    marco = candidatos[0]
    if min(_dist(marco, f) for f in finales) > TOLERANCIA_M:
        return None
    cierres = [(centro, marco)]
    ux, uy = (marco[0] - centro[0]) / arco.radio, (marco[1] - centro[1]) / arco.radio
    for s in muros:
        for a, b in (((s.x1, s.y1), (s.x2, s.y2)), ((s.x2, s.y2), (s.x1, s.y1))):
            largo = _dist(a, b)
            if _dist(a, centro) > TOLERANCIA_M or not 0 < largo <= ESPESOR_MAX_M:
                continue
            vx, vy = b[0] - a[0], b[1] - a[1]
            if abs(vx * ux + vy * uy) < 1e-6 * largo + 1e-9:  # perpendicular al vano
                cierres.append(((centro[0] + vx, centro[1] + vy), (marco[0] + vx, marco[1] + vy)))
                return cierres
    return cierres


def reconocer_uso(nombre: str, perfil: Perfil) -> str | None:
    """Uso de un ambiente según las palabras de su nombre; `None` si no se reconoce."""
    limpio = sin_tildes(nombre)
    filas, _ = perfil.plantillas()
    for fila in filas:
        for patron in fila.patrones:
            if re.search(rf"\b{re.escape(patron)}", limpio):
                return fila.uso
    return None


def interpretar(leido: PlanoLeido, perfil: Perfil) -> Plano:
    """Ambientes, puertas y área construida del plano leído."""
    muros = leido.de_clase("muro")
    banderas = list(leido.banderas)
    lineas = [LineString([(s.x1, s.y1), (s.x2, s.y2)]) for s in muros + leido.de_clase("ventana")]

    vanos: list[list[tuple[Coord, Coord]]] = []
    for arco in leido.arcos_de_clase("puerta"):
        if arco.fin - arco.inicio >= 360:
            continue
        cierres = _cierres_de_puerta(arco, muros)
        if cierres is None:
            banderas.append(
                f"puerta en ({arco.cx:.2f}, {arco.cy:.2f}) sin muro donde cerrar el vano"
            )
            continue
        vanos.append(cierres)
        lineas.extend(LineString(list(c)) for c in cierres)

    caras = [c for c in polygonize(unary_union(lineas)) if isinstance(c, Polygon)]
    if not caras:
        banderas.append("no se pudo cerrar ningún ambiente con los muros del plano")
    recintos = [
        c for c in caras if c.area >= AREA_MINIMA_M2 and not c.buffer(-RADIO_MINIMO_M).is_empty
    ]
    recintos.sort(key=lambda c: (-round(c.centroid.y, 2), round(c.centroid.x, 2)))

    textos = [t for t in leido.textos if leido.capas.get(t.capa) != "cota" and t.texto]
    ambientes: list[Ambiente] = []
    for n, recinto in enumerate(recintos, start=1):
        dentro = [t for t in textos if recinto.contains(Point(t.x, t.y))]
        reconocidos = [(t, reconocer_uso(t.texto, perfil)) for t in dentro]
        con_uso = [(t, u) for t, u in reconocidos if u is not None]
        dudas: list[str] = []
        if con_uso:
            nombre, uso = con_uso[0][0].texto, con_uso[0][1]
            if len({u for _, u in con_uso}) > 1:
                dudas.append("tiene textos de usos distintos; confirme el uso")
        elif dentro:
            nombre, uso = dentro[0].texto, "otro"
            dudas.append("no se reconoce el uso por su nombre; elija uno")
        else:
            nombre, uso = "", "otro"
            dudas.append("no tiene nombre en el plano; indique su uso")
        simple = recinto.simplify(0.001)
        borde = simple.exterior if isinstance(simple, Polygon) else recinto.exterior
        contorno = list(borde.coords)[:-1]
        ambientes.append(
            Ambiente(
                id=f"A{n}",
                nombre=nombre,
                uso=uso or "otro",
                poligono=tuple(Pt(x=mm(x), y=mm(y)) for x, y in contorno),
                area_m2=cm(recinto.area),
                perimetro_m=cm(recinto.exterior.length),
                banderas=tuple(dudas),
            )
        )

    puertas = []
    for n, cierres in enumerate(sorted(vanos), start=1):
        bisagra, marco = cierres[0]
        caras_del_vano = [LineString(list(c)) for c in cierres]
        vecinos = tuple(
            a.id
            for a, r in zip(ambientes, recintos, strict=True)
            if any(r.distance(cara) <= TOLERANCIA_M for cara in caras_del_vano)
        )
        puertas.append(
            Puerta(
                id=f"P{n}",
                bisagra=Pt(x=mm(bisagra[0]), y=mm(bisagra[1])),
                extremo=Pt(x=mm(marco[0]), y=mm(marco[1])),
                ambientes=vecinos,
            )
        )

    construida = unary_union(caras).area if caras else 0.0
    return Plano(
        archivo=leido.nombre,
        sha256=leido.sha256,
        factor_a_metros=Decimal(str(leido.factor_a_metros)),
        area_construida_m2=cm(construida),
        ambientes=tuple(ambientes),
        puertas=tuple(puertas),
        banderas=tuple(banderas),
    )
