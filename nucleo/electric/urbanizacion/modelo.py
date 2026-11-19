"""Urbanización o lotización: manzanas de lotes con calles entre ellas.

Las manzanas se ordenan de arriba hacia abajo y cada una tiene dos filas de
lotes espalda con espalda. Entre dos manzanas hay una calle, y hay calles
también arriba de la primera y abajo de la última: cada calle tiene lotes a
sus dos lados. La red de baja tensión y el alumbrado van por las calles, con
transformadores por sectores, y la red de media tensión llega por una avenida
lateral hasta cada calle.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from electric.perfiles.esquema import Dato


class Manzana(Dato):
    id: str = Field(min_length=1, max_length=20)
    #: Lotes de la manzana; se reparten en dos filas.
    lotes: int = Field(ge=1, le=400)
    frente_m: Decimal = Field(default=Decimal(10), gt=0, le=100)
    fondo_m: Decimal = Field(default=Decimal(20), gt=0, le=200)


class CargaComunal(Dato):
    """Casa comunal, bombeo de agua potable, etc., en la calle indicada."""

    descripcion: str = Field(min_length=1, max_length=80)
    kva: Decimal = Field(gt=0)
    calle: int = Field(default=0, ge=0)


class Urbanizacion(Dato):
    nombre: str = Field(min_length=1, max_length=200)
    #: Tipo de usuario de la tabla de demanda (estrato A–E).
    estrato: str = "C"
    sistema: str = "monofasico_trifilar_120_240"
    fases_transformador: Literal[1, 3] = 1
    #: Mayor transformador por sector; si falta, el del perfil.
    kva_max_transformador: Decimal | None = Field(default=None, gt=0)
    ancho_calle_m: Decimal = Field(default=Decimal(10), gt=0)
    separacion_luminarias_m: Decimal | None = Field(default=None, gt=0)
    potencia_luminaria_w: Decimal | None = Field(default=None, gt=0)
    manzanas: tuple[Manzana, ...] = Field(min_length=1, max_length=60)
    comunales: tuple[CargaComunal, ...] = ()

    @model_validator(mode="after")
    def _validar(self) -> Urbanizacion:
        ids = [m.id for m in self.manzanas]
        if len(set(ids)) != len(ids):
            raise ValueError("las manzanas deben tener nombres distintos")
        if any(c.calle > len(self.manzanas) for c in self.comunales):
            raise ValueError(f"las calles van de 0 a {len(self.manzanas)}")
        return self
