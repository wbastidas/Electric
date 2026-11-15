"""Resultado de un cálculo: el número y todo lo necesario para explicarlo (RF-23)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TypeVar

from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import Estado, RefTabla, peor_estado

Valor = Decimal | str
T = TypeVar("T")

#: Sujeto de los resultados que describen el proyecto completo.
PROYECTO = "proyecto"
#: Sujeto del tramo entre el medidor y el tablero.
ALIMENTADOR = "alimentador"


@dataclass(frozen=True)
class Resultado:
    id: str
    sujeto: str
    nombre: str
    valor: Valor
    unidad: str
    #: Fórmula tal como se muestra al usuario y en la memoria.
    formula: str
    entradas: dict[str, Valor] = field(default_factory=dict)
    #: Valores secundarios que acompañan al principal.
    detalle: dict[str, Valor] = field(default_factory=dict)
    tablas: tuple[RefTabla, ...] = ()
    #: Sobrescrituras aplicadas, con su justificación (RF-25).
    supuestos: tuple[str, ...] = ()
    avisos: tuple[str, ...] = ()
    #: El peor estado de las tablas usadas, propias o de los cálculos previos.
    estado: Estado = "verificado"

    @property
    def decimal(self) -> Decimal:
        if not isinstance(self.valor, Decimal):
            raise TypeError(f"{self.id} de {self.sujeto} no es numérico")
        return self.valor

    def det(self, clave: str) -> Decimal:
        """Valor numérico del detalle."""
        valor = self.detalle[clave]
        if not isinstance(valor, Decimal):
            raise TypeError(f"el detalle '{clave}' de {self.id} no es numérico")
        return valor


class Rastro:
    """Acumula las tablas y los supuestos que usa un cálculo."""

    def __init__(self) -> None:
        self._tablas: list[RefTabla] = []
        self._supuestos: list[str] = []

    def usar(self, consulta: tuple[T, RefTabla]) -> T:
        valor, ref = consulta
        self.anotar(ref)
        return valor

    def anotar(self, *refs: RefTabla) -> None:
        for ref in refs:
            if ref not in self._tablas:
                self._tablas.append(ref)

    def supuesto(self, texto: str) -> None:
        if texto not in self._supuestos:
            self._supuestos.append(texto)

    @property
    def tablas(self) -> tuple[RefTabla, ...]:
        return tuple(self._tablas)

    @property
    def supuestos(self) -> tuple[str, ...]:
        return tuple(self._supuestos)

    @property
    def estado(self) -> Estado:
        return peor_estado([t.estado for t in self._tablas])


def redondear(valor: Decimal, decimales: int) -> Decimal:
    return valor.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def presentar(valor: Valor, unidad: str, perfil: Perfil) -> str:
    """Texto para mostrar: redondeo del perfil y coma decimal."""
    if isinstance(valor, str):
        return valor
    decimales = perfil.decimales(unidad)
    if decimales is not None:
        texto = format(redondear(valor, decimales), "f")
    else:
        # Sin unidad con redondeo declarado: seis decimales como máximo, sin ceros de relleno.
        texto = format(redondear(valor, 6), "f")
        if "." in texto:
            texto = texto.rstrip("0").rstrip(".")
    texto = texto.replace(".", ",")
    return f"{texto} {unidad}".strip()
