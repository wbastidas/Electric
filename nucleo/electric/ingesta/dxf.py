"""Lectura de DXF con ezdxf.

El archivo se trata como no confiable: se lee en modo de recuperación, con
límite de tamaño, y nunca se modifica. Lo que no se entiende se señala con una
bandera para que el usuario decida; no se completa en silencio (RF-14).
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import unicodedata
from dataclasses import dataclass, field

from ezdxf import recover
from ezdxf.entities.dxfgfx import DXFGraphic
from ezdxf.lldxf.const import DXFError

from electric.errores import DatoInvalido

TAMANO_MAX = 100 * 1024 * 1024  # RNF-05

#: Código $INSUNITS del DXF → factor a metros.
_UNIDADES: dict[int, tuple[str, float]] = {
    1: ("pulgadas", 0.0254),
    2: ("pies", 0.3048),
    4: ("milímetros", 0.001),
    5: ("centímetros", 0.01),
    6: ("metros", 1.0),
}

#: Clase de una capa según su nombre, en español e inglés (RF-10). El orden importa.
_PATRONES_CAPA: tuple[tuple[str, str], ...] = (
    ("cota", r"cota|dim|acot"),
    ("puerta", r"puerta|door"),
    ("ventana", r"ventana|window|vidrio|glaz"),
    ("mobiliario", r"mobil|mueble|furn|sanit|aparato|equip"),
    ("texto", r"text|nombre|rotul|ambiente|anno|label"),
    ("muro", r"muro|pared|wall|mamp|tabique"),
)
CLASES = ("muro", "puerta", "ventana", "texto", "mobiliario", "cota", "otro")


def sin_tildes(texto: str) -> str:
    normal = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in normal if unicodedata.category(c) != "Mn")


def clasificar_capa(nombre: str) -> str:
    limpio = sin_tildes(nombre)
    for clase, patron in _PATRONES_CAPA:
        if re.search(patron, limpio):
            return clase
    return "otro"


@dataclass(frozen=True)
class Segmento:
    capa: str
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class Arco:
    capa: str
    cx: float
    cy: float
    radio: float
    #: Ángulos en grados, sentido antihorario.
    inicio: float
    fin: float

    def extremos(self) -> tuple[tuple[float, float], tuple[float, float]]:
        def punto(angulo: float) -> tuple[float, float]:
            a = math.radians(angulo)
            return (self.cx + self.radio * math.cos(a), self.cy + self.radio * math.sin(a))

        return punto(self.inicio), punto(self.fin)

    def polilinea(self, pasos: int = 12) -> list[tuple[float, float]]:
        fin = self.fin if self.fin > self.inicio else self.fin + 360
        return [
            (
                self.cx
                + self.radio
                * math.cos(math.radians(self.inicio + (fin - self.inicio) * i / pasos)),
                self.cy
                + self.radio
                * math.sin(math.radians(self.inicio + (fin - self.inicio) * i / pasos)),
            )
            for i in range(pasos + 1)
        ]


@dataclass(frozen=True)
class Texto:
    capa: str
    x: float
    y: float
    texto: str


@dataclass
class PlanoLeido:
    nombre: str
    sha256: str
    unidad: str
    factor_a_metros: float
    #: Capa → clase (muro, puerta, ventana, texto, mobiliario, cota, otro).
    capas: dict[str, str]
    segmentos: list[Segmento] = field(default_factory=list)
    arcos: list[Arco] = field(default_factory=list)
    textos: list[Texto] = field(default_factory=list)
    banderas: list[str] = field(default_factory=list)

    def de_clase(self, clase: str) -> list[Segmento]:
        return [s for s in self.segmentos if self.capas.get(s.capa) == clase]

    def arcos_de_clase(self, clase: str) -> list[Arco]:
        return [a for a in self.arcos if self.capas.get(a.capa) == clase]


def _aplanar(entidades: object, profundidad: int = 0) -> list[DXFGraphic]:
    """Entidades con los bloques anidados expandidos (RF-09)."""
    planas: list[DXFGraphic] = []
    for entidad in entidades:  # type: ignore[attr-defined]
        if entidad.dxftype() == "INSERT" and profundidad < 8:
            planas.extend(_aplanar(entidad.virtual_entities(), profundidad + 1))
        else:
            planas.append(entidad)
    return planas


def leer_dxf(
    contenido: bytes,
    nombre: str,
    mapeo_capas: dict[str, str] | None = None,
    factor_a_metros: float | None = None,
) -> PlanoLeido:
    """Lee un DXF y devuelve sus primitivas en metros.

    `mapeo_capas` corrige la clase de una capa; `factor_a_metros` fija la
    escala cuando el archivo no declara unidades.
    """
    if len(contenido) > TAMANO_MAX:
        raise DatoInvalido("el archivo supera el tamaño máximo de 100 MB")
    try:
        doc, _ = recover.read(io.BytesIO(contenido))
    except (DXFError, OSError, ValueError) as error:
        raise DatoInvalido(f"el archivo no es un DXF legible: {error}") from error

    banderas: list[str] = []
    codigo = int(doc.header.get("$INSUNITS", 0))
    unidad, factor = _UNIDADES.get(codigo, ("sin declarar", 0.0))
    if factor_a_metros is not None:
        factor = factor_a_metros
        unidad = f"{unidad} (escala fijada por el usuario)"
    elif not factor:
        raise DatoInvalido(
            "el plano no declara sus unidades; indique cuántos metros mide una unidad del dibujo"
        )

    msp = doc.modelspace()
    entidades = _aplanar(msp)
    capas = {capa.dxf.name: clasificar_capa(capa.dxf.name) for capa in doc.layers}
    for capa, clase in (mapeo_capas or {}).items():
        if clase not in CLASES:
            raise DatoInvalido(f"clase de capa desconocida: {clase}")
        capas[capa] = clase

    leido = PlanoLeido(
        nombre=nombre,
        sha256=hashlib.sha256(contenido).hexdigest(),
        unidad=unidad,
        factor_a_metros=factor,
        capas=capas,
        banderas=banderas,
    )
    f = factor
    ignoradas: set[str] = set()
    for e in entidades:
        capa = e.dxf.layer
        capas.setdefault(capa, clasificar_capa(capa))
        tipo = e.dxftype()
        if tipo == "LINE":
            leido.segmentos.append(
                Segmento(
                    capa, e.dxf.start.x * f, e.dxf.start.y * f, e.dxf.end.x * f, e.dxf.end.y * f
                )
            )
        elif tipo in ("LWPOLYLINE", "POLYLINE"):
            if tipo == "LWPOLYLINE":
                puntos = [(p[0] * f, p[1] * f) for p in e.get_points("xy")]  # type: ignore[attr-defined]
                cerrada = bool(e.closed)  # type: ignore[attr-defined]
            else:
                puntos = [(v.dxf.location.x * f, v.dxf.location.y * f) for v in e.vertices]  # type: ignore[attr-defined]
                cerrada = bool(e.is_closed)  # type: ignore[attr-defined]
            if cerrada and puntos:
                puntos.append(puntos[0])
            for (x1, y1), (x2, y2) in zip(puntos, puntos[1:], strict=False):
                leido.segmentos.append(Segmento(capa, x1, y1, x2, y2))
        elif tipo == "ARC":
            leido.arcos.append(
                Arco(
                    capa,
                    e.dxf.center.x * f,
                    e.dxf.center.y * f,
                    e.dxf.radius * f,
                    e.dxf.start_angle,
                    e.dxf.end_angle,
                )
            )
        elif tipo == "CIRCLE":
            leido.arcos.append(
                Arco(capa, e.dxf.center.x * f, e.dxf.center.y * f, e.dxf.radius * f, 0.0, 360.0)
            )
        elif tipo == "TEXT":
            punto = e.get_placement()[1] if e.dxf.hasattr("align_point") else e.dxf.insert  # type: ignore[attr-defined]
            punto = punto or e.dxf.insert
            leido.textos.append(Texto(capa, punto.x * f, punto.y * f, e.dxf.text.strip()))
        elif tipo == "MTEXT":
            leido.textos.append(
                Texto(capa, e.dxf.insert.x * f, e.dxf.insert.y * f, e.plain_text().strip())  # type: ignore[attr-defined]
            )
        else:
            ignoradas.add(tipo)
    if ignoradas:
        banderas.append(f"entidades no interpretadas: {', '.join(sorted(ignoradas))}")
    if not leido.de_clase("muro"):
        banderas.append("ninguna capa se reconoció como muros; revise el mapeo de capas")
    return leido
