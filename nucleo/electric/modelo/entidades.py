"""Entidades de entrada del modelo del proyecto.

Todas son inmutables. El modelo guarda unidades SI (metros, watts, voltios,
amperios); los calibres AWG son etiquetas de catálogo del perfil.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Origen = Literal["auto", "editado", "fijado"]
TipoCircuito = Literal["iluminacion", "tomacorrientes", "especial"]
Conexion = Literal["fase_neutro", "linea"]
Fase = Literal["A", "B", "C", "AB", "BC", "AC", "ABC"]

#: Parámetros del perfil que un ingeniero puede sobrescribir con justificación (RF-25).
PARAMETROS_SOBRESCRIBIBLES = frozenset(
    {
        "factor_potencia",
        "temperatura_ambiente_c",
        "factor_demanda_iluminacion",
        "factor_demanda_tomacorrientes",
        "factor_demanda_especiales",
    }
)


class Entidad(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RefPerfil(Entidad):
    """Perfil normativo y versión con la que se calcula el proyecto."""

    id: str
    version: str


class Predio(Entidad):
    """Datos del predio y de su propietario (RF-01)."""

    propietario: str = ""
    direccion: str = ""
    clave_catastral: str = ""
    unidad_negocio: str = ""
    plantas: int = Field(default=1, ge=1)


class Proyectista(Entidad):
    """Profesional que revisa y firma el proyecto (RF-03)."""

    nombre: str = ""
    titulo: str = ""
    registro_senescyt: str = ""
    registro_cnel: str = ""


class Punto(Entidad):
    """Punto de luz o tomacorriente de uso general."""

    id: str
    tipo: str
    circuito: str
    potencia_w: Decimal | None = Field(default=None, gt=0)
    ambiente: str | None = None
    origen: Origen = "fijado"


class CargaEspecial(Entidad):
    """Equipo declarado con circuito propio (ducha, cocina, A/C…)."""

    id: str
    tipo: str
    circuito: str
    #: Potencia de placa; si falta, se usa el valor por defecto del perfil.
    potencia_w: Decimal | None = Field(default=None, gt=0)
    #: Si falta, se usa la conexión por defecto del perfil para ese equipo.
    conexion: Conexion | None = None
    origen: Origen = "fijado"


class Circuito(Entidad):
    id: str
    tipo: TipoCircuito
    #: Longitud real del recorrido desde el tablero hasta el punto más lejano.
    longitud_m: Decimal = Field(gt=0)
    #: Fase asignada; si falta, el motor la asigna al balancear (RC-10).
    fase: Fase | None = None
    #: Conductores portadores de corriente que comparten el ducto.
    portadores_en_ducto: int | None = Field(default=None, ge=1)
    zona_humeda: bool = False


class Tablero(Entidad):
    id: str = "TD-1"
    #: Longitud del alimentador desde el medidor hasta el tablero.
    alimentador_longitud_m: Decimal = Field(gt=0)


class Supuesto(Entidad):
    """Sobrescritura de un parámetro del perfil, con su justificación (RF-25)."""

    parametro: str
    valor: Decimal
    justificacion: str = Field(min_length=1)
    autor: str = Field(min_length=1)
    fecha: str

    @model_validator(mode="after")
    def _parametro_conocido(self) -> Self:
        if self.parametro not in PARAMETROS_SOBRESCRIBIBLES:
            permitidos = ", ".join(sorted(PARAMETROS_SOBRESCRIBIBLES))
            raise ValueError(
                f"el parámetro '{self.parametro}' no se puede sobrescribir; "
                f"permitidos: {permitidos}"
            )
        return self


class Proyecto(Entidad):
    id: str
    nombre: str
    uso: str = "vivienda_unifamiliar"
    area_construida_m2: Decimal = Field(gt=0)
    perfil: RefPerfil
    predio: Predio = Predio()
    proyectista: Proyectista = Proyectista()
    #: Sistema de tensión del perfil; si falta, se usa el sistema por defecto.
    sistema: str | None = None
    puntos: tuple[Punto, ...] = ()
    cargas_especiales: tuple[CargaEspecial, ...] = ()
    circuitos: tuple[Circuito, ...]
    tablero: Tablero
    supuestos: tuple[Supuesto, ...] = ()

    @model_validator(mode="after")
    def _coherencia(self) -> Self:
        ids = (
            [p.id for p in self.puntos]
            + [c.id for c in self.cargas_especiales]
            + [c.id for c in self.circuitos]
            + [self.tablero.id]
        )
        repetidos = sorted({i for i in ids if ids.count(i) > 1})
        if repetidos:
            raise ValueError(f"identificadores repetidos: {', '.join(repetidos)}")

        circuitos = {c.id: c for c in self.circuitos}
        if not circuitos:
            raise ValueError("el proyecto no tiene circuitos")

        ocupacion: dict[str, int] = dict.fromkeys(circuitos, 0)
        for punto in self.puntos:
            circuito = circuitos.get(punto.circuito)
            if circuito is None:
                raise ValueError(f"el punto {punto.id} apunta a un circuito inexistente")
            if circuito.tipo == "especial":
                raise ValueError(f"el punto {punto.id} está en el circuito especial {circuito.id}")
            ocupacion[circuito.id] += 1
        for carga in self.cargas_especiales:
            circuito = circuitos.get(carga.circuito)
            if circuito is None:
                raise ValueError(f"la carga {carga.id} apunta a un circuito inexistente")
            if circuito.tipo != "especial":
                raise ValueError(
                    f"la carga especial {carga.id} debe ir en un circuito de tipo 'especial'"
                )
            if ocupacion[circuito.id]:
                raise ValueError(f"el circuito especial {circuito.id} tiene más de una carga")
            ocupacion[circuito.id] += 1
        vacios = sorted(i for i, n in ocupacion.items() if n == 0)
        if vacios:
            raise ValueError(f"circuitos sin puntos ni cargas: {', '.join(vacios)}")

        parametros = [s.parametro for s in self.supuestos]
        if len(parametros) != len(set(parametros)):
            raise ValueError("hay más de un supuesto para el mismo parámetro")
        return self
