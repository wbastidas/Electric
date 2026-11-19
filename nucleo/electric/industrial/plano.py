"""Plano de la nave: ubicación de tableros y máquinas y recorridos de los alimentadores.

En el DXF de la nave, cada tablero y cada máquina se marca con un texto (o un
bloque, o el atributo de un bloque) con el mismo código que en el cuadro de
cargas: «TP», «TD-1», «M-3»… Se toma el punto de inserción del texto o del
bloque. El recorrido se mide en ángulo recto (como una bandeja que sigue los
ejes de la nave) más las bajadas y subidas del perfil, y se redondea hacia
arriba al metro.

La implantación es el mismo plano con una capa nueva para los recorridos y
sus rótulos (tablero, conductor y longitud).
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from ezdxf import recover
from ezdxf.document import Drawing
from ezdxf.entities.dxfentity import DXFEntity
from ezdxf.lldxf.const import DXFError

from electric.errores import DatoInvalido
from electric.industrial.estudios import PRINCIPAL, Estudios
from electric.industrial.modelo import Maquina
from electric.perfiles.carga import Perfil

_UNIDADES = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}
CAPA_RECORRIDOS = "E-ALIM-RECORRIDO"
CAPA_ROTULOS = "E-ALIM-TEXTO"


def normal(texto: str) -> str:
    """Código comparable: mayúsculas, sin espacios, guiones ni puntos."""
    return re.sub(r"[\s\-_.]", "", texto.upper())


@dataclass(frozen=True)
class LecturaPlano:
    #: Metros por unidad de dibujo.
    escala: float
    unidad: str
    #: Código → (x, y) en unidades de dibujo.
    puntos: dict[str, tuple[float, float]]
    #: Tablero → recorrido desde el tablero principal.
    distancias_m: dict[str, Decimal]
    #: Máquina → recorrido desde su tablero.
    longitudes_m: dict[str, Decimal]
    faltan: tuple[str, ...]
    avisos: tuple[str, ...] = field(default=())


def _textos(entidades: Iterable[DXFEntity]) -> Iterable[tuple[str, tuple[float, float]]]:
    for e in entidades:
        tipo = e.dxftype()
        try:
            if tipo == "TEXT":
                yield e.dxf.text, (e.dxf.insert.x, e.dxf.insert.y)
            elif tipo == "MTEXT":
                yield e.plain_text(), (e.dxf.insert.x, e.dxf.insert.y)  # type: ignore[attr-defined]
            elif tipo == "INSERT":
                punto = (e.dxf.insert.x, e.dxf.insert.y)
                yield e.dxf.name, punto
                for atributo in e.attribs:  # type: ignore[attr-defined]
                    yield atributo.dxf.text, punto
        except AttributeError:
            continue


def _abrir(contenido: bytes) -> Drawing:
    try:
        doc, _ = recover.read(io.BytesIO(contenido))
    except (DXFError, OSError, ValueError) as error:
        raise DatoInvalido(f"el archivo no es un DXF legible: {error}") from error
    return doc


def _escala(doc: Drawing, factor_a_metros: float | None) -> tuple[float, str]:
    if factor_a_metros:
        return factor_a_metros, "fijada por el usuario"
    codigo = int(doc.header.get("$INSUNITS", 0))
    if codigo in _UNIDADES:
        return _UNIDADES[codigo], {1: "pulgadas", 2: "pies", 4: "mm", 5: "cm", 6: "m"}[codigo]
    raise DatoInvalido(
        "el plano no declara sus unidades; indique cuántos metros mide una unidad del dibujo"
    )


def _recorrido(
    a: tuple[float, float], b: tuple[float, float], escala: float, extra: float
) -> Decimal:
    metros = (abs(a[0] - b[0]) + abs(a[1] - b[1])) * escala + extra
    return Decimal(max(1, math.ceil(metros)))


def leer_plano_nave(
    contenido: bytes,
    maquinas: Sequence[Maquina],
    perfil: Perfil,
    factor_a_metros: float | None = None,
) -> LecturaPlano:
    doc = _abrir(contenido)
    escala, unidad = _escala(doc, factor_a_metros)
    tableros = sorted({m.tablero for m in maquinas} | {PRINCIPAL})
    buscados = {normal(c): c for c in [*tableros, *(m.id for m in maquinas)]}
    puntos: dict[str, tuple[float, float]] = {}
    repetidos: set[str] = set()
    for texto, punto in _textos(doc.modelspace()):
        for parte in (texto.strip(), *texto.strip().split()[:1]):
            codigo = buscados.get(normal(parte))
            if codigo is None:
                continue
            if codigo in puntos and puntos[codigo] != punto:
                repetidos.add(codigo)
            else:
                puntos.setdefault(codigo, punto)
            break
    extra = float(perfil.parametro("bajadas_recorrido_m")[0])
    avisos = [
        f"«{c}» aparece varias veces en el plano; se tomó el primero." for c in sorted(repetidos)
    ]
    distancias: dict[str, Decimal] = {}
    longitudes: dict[str, Decimal] = {}
    principal = puntos.get(PRINCIPAL)
    if principal is None:
        avisos.append("No se encontró el tablero principal «TP» en el plano.")
    for tablero in tableros:
        if tablero != PRINCIPAL and principal is not None and tablero in puntos:
            distancias[tablero] = _recorrido(principal, puntos[tablero], escala, extra)
    for m in maquinas:
        origen = puntos.get(m.tablero)
        if origen is not None and m.id in puntos:
            longitudes[m.id] = _recorrido(origen, puntos[m.id], escala, extra)
    faltan = tuple(c for c in [*tableros, *(m.id for m in maquinas)] if c not in puntos)
    return LecturaPlano(
        escala=escala,
        unidad=unidad,
        puntos=puntos,
        distancias_m=distancias,
        longitudes_m=longitudes,
        faltan=faltan,
        avisos=tuple(avisos),
    )


def _ruta(doc: Drawing, a: tuple[float, float], b: tuple[float, float], color: int) -> None:
    """Recorrido en L: primero en x, luego en y."""
    doc.modelspace().add_lwpolyline(
        [a, (b[0], a[1]), b], dxfattribs={"layer": CAPA_RECORRIDOS, "color": color}
    )


def generar_implantacion(
    contenido: bytes,
    lectura: LecturaPlano,
    maquinas: Sequence[Maquina],
    estudios: Estudios | None = None,
) -> bytes:
    """El plano de la nave con los recorridos de alimentadores y circuitos."""
    doc = _abrir(contenido)
    for capa, color in ((CAPA_RECORRIDOS, 1), (CAPA_ROTULOS, 7)):
        if capa not in doc.layers:
            doc.layers.add(capa, color=color)
    msp = doc.modelspace()
    alto = 0.25 / lectura.escala  # 25 cm de altura de texto en el dibujo
    conductores = {a.tablero: a for a in (estudios.alimentadores if estudios else [])}
    circuitos = {c.maquina: c for c in (estudios.circuitos if estudios else [])}
    p = lectura.puntos
    if PRINCIPAL in p:
        for tablero, metros in lectura.distancias_m.items():
            _ruta(doc, p[PRINCIPAL], p[tablero], 1)
            a = conductores.get(tablero)
            texto = f"{tablero}: {a.conductor.texto if a and a.conductor else '—'} · {metros} m"
            # Sobre el tramo horizontal del recorrido, a mitad de camino.
            medio = ((p[PRINCIPAL][0] + p[tablero][0]) / 2, p[PRINCIPAL][1] + alto * 0.6)
            msp.add_text(texto, height=alto, dxfattribs={"layer": CAPA_ROTULOS}).set_placement(
                medio
            )
    for m in maquinas:
        if m.id not in lectura.longitudes_m:
            continue
        _ruta(doc, p[m.tablero], p[m.id], 3)
        c = circuitos.get(m.id)
        calibre = c.conductor.texto if c and c.conductor else "—"
        texto = f"{m.id}: {calibre} · {lectura.longitudes_m[m.id]} m"
        msp.add_text(texto, height=alto * 0.8, dxfattribs={"layer": CAPA_ROTULOS}).set_placement(
            (p[m.id][0], p[m.id][1] - alto * 1.5)
        )
    salida = io.StringIO()
    doc.write(salida)
    return salida.getvalue().encode("utf-8")
