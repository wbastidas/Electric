"""Geometría del proyecto: ambientes leídos del plano y ubicación de la instalación.

Todas las coordenadas van en metros, con precisión de milímetro. El archivo del
arquitecto nunca se modifica; aquí solo se guarda lo que se interpretó de él.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

MM = Decimal("0.001")
CM = Decimal("0.01")


def mm(valor: float | Decimal) -> Decimal:
    """Redondea a milímetros; fija el resultado de la geometría en coma flotante."""
    return Decimal(str(valor)).quantize(MM) + 0


def cm(valor: float | Decimal) -> Decimal:
    return Decimal(str(valor)).quantize(CM) + 0


class Geo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Pt(Geo):
    x: Decimal
    y: Decimal


class Ambiente(Geo):
    id: str
    #: Texto del plano que nombra el ambiente; vacío si no tiene.
    nombre: str
    #: Uso según las plantillas del perfil; "otro" si no se reconoce.
    uso: str
    poligono: tuple[Pt, ...]
    area_m2: Decimal
    perimetro_m: Decimal
    #: Dudas que el usuario debe resolver (sin nombre, uso desconocido…).
    banderas: tuple[str, ...] = ()


class Puerta(Geo):
    id: str
    #: Vano sobre la cara del muro: de la bisagra al otro marco.
    bisagra: Pt
    extremo: Pt
    ambientes: tuple[str, ...] = ()


class Ubicacion(Geo):
    """Posición de un punto, una carga especial o el tablero."""

    id: str
    x: Decimal
    y: Decimal
    altura_m: Decimal
    ambiente: str | None = None


class Interruptor(Geo):
    id: str
    x: Decimal
    y: Decimal
    altura_m: Decimal
    ambiente: str
    circuito: str


class Recorrido(Geo):
    """Recorrido ortogonal de un circuito desde el tablero."""

    circuito: str
    puntos: tuple[Pt, ...]
    #: Derivaciones a interruptores; se dibujan, no cuentan para la caída de tensión.
    derivaciones: tuple[tuple[Pt, Pt], ...] = ()
    #: Longitud física de tubería: recorrido en planta más las bajadas.
    longitud_m: Decimal


class Plano(Geo):
    archivo: str
    sha256: str
    #: Factor que lleva las unidades del dibujo a metros.
    factor_a_metros: Decimal
    area_construida_m2: Decimal
    ambientes: tuple[Ambiente, ...]
    puertas: tuple[Puerta, ...] = ()
    ubicaciones: tuple[Ubicacion, ...] = ()
    interruptores: tuple[Interruptor, ...] = ()
    recorridos: tuple[Recorrido, ...] = ()
    banderas: tuple[str, ...] = ()
