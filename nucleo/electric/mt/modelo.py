"""Datos de una extensión de red de media tensión.

La red nueva arranca en un poste de la red existente (tomado del geoportal o
dado por coordenadas) y sigue por una lista ordenada de postes nuevos. En los
postes se pueden colgar transformadores nuevos.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Dato(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Coordenada(Dato):
    lat: Decimal = Field(ge=-90, le=90)
    lon: Decimal = Field(ge=-180, le=180)


class PosteNuevo(Dato):
    id: str = Field(min_length=1, max_length=40)
    lat: Decimal = Field(ge=-90, le=90)
    lon: Decimal = Field(ge=-180, le=180)
    #: Potencia del transformador nuevo montado en este poste, si hay.
    transformador_kva: Decimal | None = Field(default=None, gt=0)
    #: Estructura elegida por el proyectista; si falta, la propone el diseño.
    estructura: str | None = None


class Arranque(Dato):
    """Punto de conexión en la red existente de CNEL."""

    lat: Decimal = Field(ge=-90, le=90)
    lon: Decimal = Field(ge=-180, le=180)
    #: Código del poste existente en el SIG, si se eligió del geoportal.
    poste: str | None = None
    alimentador: str | None = None
    #: Potencia de cortocircuito en el punto de arranque; si falta, la del perfil.
    scc_mva: Decimal | None = Field(default=None, gt=0)
    #: Caída de tensión que ya existe hasta el punto de arranque.
    caida_previa_pct: Decimal = Field(default=Decimal(0), ge=0)


class ExtensionMT(Dato):
    nombre: str = Field(min_length=1, max_length=200)
    tension_kv: Decimal = Field(default=Decimal("13.8"), gt=0)
    fases: Literal[1, 3] = 3
    conductor: str = "ACSR 1/0 AWG"
    zona: Literal["urbana", "rural"] = "urbana"
    fp: Decimal = Field(default=Decimal("0.9"), gt=0, le=1)
    arranque: Arranque
    postes: tuple[PosteNuevo, ...] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _ids(self) -> ExtensionMT:
        ids = [p.id for p in self.postes]
        repetidos = sorted({i for i in ids if ids.count(i) > 1})
        if repetidos:
            raise ValueError(f"postes repetidos: {', '.join(repetidos)}")
        return self


# --- Red existente leída del SIG -----------------------------------------------------


class PosteSIG(Dato):
    id: str
    lat: Decimal
    lon: Decimal
    estructura: str | None = None
    material: str | None = None
    altura: str | None = None
    alimentador: str | None = None


class TramoSIG(Dato):
    id: str
    puntos: tuple[Coordenada, ...]
    conductor: str | None = None
    fases: str | None = None
    alimentador: str | None = None
    tension: str | None = None


class TransformadorSIG(Dato):
    id: str
    lat: Decimal
    lon: Decimal
    kva: Decimal | None = None
    fases: str | None = None
    clientes: int | None = None
    alimentador: str | None = None


class ProteccionSIG(Dato):
    id: str
    lat: Decimal
    lon: Decimal
    tipo: str | None = None
    capacidad: str | None = None
    alimentador: str | None = None


class RedExistente(Dato):
    postes: tuple[PosteSIG, ...] = ()
    tramos: tuple[TramoSIG, ...] = ()
    transformadores: tuple[TransformadorSIG, ...] = ()
    protecciones: tuple[ProteccionSIG, ...] = ()
    #: De dónde salió: "geoportal", "archivo" o la descripción de la fuente.
    origen: str = ""
