"""Subestación de cliente 69/13,8 kV con un transformador de potencia."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from electric.perfiles.esquema import Dato


class Subestacion(Dato):
    nombre: str = Field(min_length=1, max_length=200)
    #: Demanda máxima que atenderá la subestación.
    demanda_mva: Decimal = Field(gt=0, le=200)
    fp: Decimal = Field(default=Decimal("0.92"), gt=0, le=1)
    tension_at_kv: Decimal | None = Field(default=None, gt=0)
    tension_mt_kv: Decimal | None = Field(default=None, gt=0)
    #: Potencia de cortocircuito en el punto de conexión; si falta, el supuesto del perfil.
    scc_at_mva: Decimal | None = Field(default=None, gt=0)
    alimentadores: int = Field(default=4, ge=1, le=16)
    #: Malla de tierra: dimensiones del patio y resistividad medida.
    largo_malla_m: Decimal = Field(default=Decimal(40), gt=0, le=500)
    ancho_malla_m: Decimal = Field(default=Decimal(30), gt=0, le=500)
    resistividad_ohm_m: Decimal | None = Field(default=None, gt=0)
    tiempo_falla_s: Decimal | None = Field(default=None, gt=0, le=3)
