"""Datos de entrada de un proyecto industrial.

Una industria se describe con su cuadro de cargas (una fila por máquina o
grupo de máquinas iguales), el sistema de tensión con que se alimentará y,
si se conoce, el transformador de CNEL más cercano.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Unidad = Literal["kW", "HP", "kVA"]
#: Caballos de fuerza a kilovatios.
KW_POR_HP = Decimal("0.746")


class Dato(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Maquina(Dato):
    """Una fila del cuadro de cargas.

    Lo que se deja vacío se completa con los valores típicos del tipo de carga
    del perfil, y la memoria lo dice.
    """

    id: str = Field(min_length=1, max_length=40)
    descripcion: str = Field(default="", max_length=200)
    tablero: str = Field(default="TP", min_length=1, max_length=40)
    #: motor, resistiva, iluminacion, tomacorrientes, soldadora, aire u otro.
    tipo: str = "motor"
    cantidad: int = Field(default=1, ge=1, le=1000)
    #: Potencia de placa de una unidad. En motores es la potencia en el eje.
    potencia: Decimal = Field(gt=0)
    unidad: Unidad = "kW"
    fases: Literal[1, 3] = 3
    #: Tensión de placa; si falta, la del sistema.
    tension_v: Decimal | None = Field(default=None, gt=0)
    fp: Decimal | None = Field(default=None, gt=0, le=1)
    eficiencia: Decimal | None = Field(default=None, gt=0, le=1)
    factor_utilizacion: Decimal | None = Field(default=None, gt=0, le=1)
    factor_simultaneidad: Decimal | None = Field(default=None, gt=0, le=1)
    #: Método de arranque de los motores; si falta, directo.
    arranque: str | None = None


class Coordenadas(Dato):
    lat: Decimal = Field(ge=-90, le=90)
    lon: Decimal = Field(ge=-180, le=180)


class TransformadorExistente(Dato):
    """El transformador de CNEL desde el que se podría atender la industria."""

    codigo: str | None = None
    kva: Decimal = Field(gt=0)
    fases: Literal[1, 3] = 3
    #: Demanda actual medida que entrega CNEL; si falta se estima por clientes.
    demanda_kva: Decimal | None = Field(default=None, ge=0)
    #: Clientes conectados por estrato, por ejemplo {"C": 12, "comercial": 2}.
    clientes: dict[str, int] = Field(default_factory=dict)
    #: Longitud de la acometida en baja tensión hasta la industria.
    distancia_m: Decimal = Field(ge=0)
    impedancia_pct: Decimal | None = Field(default=None, gt=0)
    origen: Literal["manual", "geoportal"] = "manual"

    @model_validator(mode="after")
    def _clientes_validos(self) -> TransformadorExistente:
        if any(n < 0 for n in self.clientes.values()):
            raise ValueError("el número de clientes no puede ser negativo")
        return self


class Industria(Dato):
    nombre: str = Field(min_length=1, max_length=200)
    #: Sistema de tensión de la tabla del perfil; las industrias suelen ser trifásicas.
    sistema: str = "trifasico_127_220"
    maquinas: tuple[Maquina, ...] = Field(min_length=1, max_length=2000)
    #: Si falta, el del perfil.
    fp_objetivo: Decimal | None = Field(default=None, gt=0, le=1)
    ubicacion: Coordenadas | None = None
    existente: TransformadorExistente | None = None
    #: Distancia del tablero principal a cada tablero de distribución.
    distancias_m: dict[str, Decimal] = Field(default_factory=dict)
    #: Potencia de cortocircuito de la red de CNEL en el punto de conexión; si
    #: falta, la del perfil.
    scc_red_mva: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _ids_unicos(self) -> Industria:
        vistos: set[str] = set()
        for maquina in self.maquinas:
            if maquina.id in vistos:
                raise ValueError(f"la máquina '{maquina.id}' está repetida en el cuadro")
            vistos.add(maquina.id)
        return self
