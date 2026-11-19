"""Edificios con varias unidades: departamentos, locales y oficinas.

Cada unidad tiene su medidor en el centro de medición del edificio, desde el
que sale su alimentador hasta el tablero de la unidad. Los servicios generales
(ascensores, bombas, áreas comunes) tienen su propio medidor. Según la demanda,
el edificio se atiende desde la red, con transformador propio o con cámara de
transformación, y puede tener generador de respaldo con transferencia.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from electric.perfiles.esquema import Dato

UsoUnidad = Literal["departamento", "local", "oficina", "bodega"]
Respaldo = Literal["ninguno", "servicios_generales", "total"]


class TipoUnidad(Dato):
    """Un tipo de unidad que se repite en uno o varios pisos."""

    id: str = Field(min_length=1, max_length=40)
    uso: UsoUnidad = "departamento"
    #: Tipo de usuario de la tabla de demanda (estrato A–E para departamentos).
    estrato: str = "C"
    #: Área útil; obligatoria en locales y oficinas sin demanda indicada.
    area_m2: Decimal | None = Field(default=None, gt=0)
    #: Demanda de diseño de la unidad si ya se calculó (p. ej. desde su plano).
    demanda_kva: Decimal | None = Field(default=None, gt=0)
    #: Fases del alimentador de la unidad: 1 (127 V), 2 (220 V entre fases) o 3.
    fases: Literal[1, 2, 3] = 2
    #: Pisos donde aparece; 0 es la planta baja.
    pisos: tuple[int, ...] = Field(min_length=1)
    por_piso: int = Field(default=1, ge=1, le=50)

    @model_validator(mode="after")
    def _pisos_validos(self) -> TipoUnidad:
        if any(p < -5 or p > 80 for p in self.pisos):
            raise ValueError("los pisos van de -5 (subsuelos) a 80")
        if len(set(self.pisos)) != len(self.pisos):
            raise ValueError(f"{self.id}: hay pisos repetidos")
        return self

    @property
    def cantidad(self) -> int:
        return len(self.pisos) * self.por_piso


class CargaGeneral(Dato):
    """Carga de servicios generales del edificio."""

    descripcion: str = Field(min_length=1, max_length=80)
    kw: Decimal = Field(gt=0)
    cantidad: int = Field(default=1, ge=1)
    fp: Decimal = Field(default=Decimal("0.85"), gt=0, le=1)
    motor: bool = False
    #: Si va en el generador cuando el respaldo es de servicios generales.
    respaldo: bool = True


class Edificio(Dato):
    nombre: str = Field(min_length=1, max_length=200)
    sistema: str = "trifasico_127_220"
    #: Piso del centro de medición (0: planta baja).
    nivel_medidores: int = 0
    altura_piso_m: Decimal | None = Field(default=None, gt=0)
    recorrido_horizontal_m: Decimal | None = Field(default=None, ge=0)
    distancia_transformador_m: Decimal | None = Field(default=None, ge=0)
    unidades: tuple[TipoUnidad, ...] = Field(min_length=1)
    servicios: tuple[CargaGeneral, ...] = ()
    respaldo: Respaldo = "ninguno"
    resistividad_ohm_m: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _ids_unicos(self) -> Edificio:
        ids = [u.id for u in self.unidades]
        if len(set(ids)) != len(ids):
            raise ValueError("los tipos de unidad deben tener nombres distintos")
        return self
