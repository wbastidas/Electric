"""Esquema de los perfiles normativos.

Un perfil es una carpeta con `perfil.yaml` y sus tablas. Cada tabla declara su
fuente y su estado de verificación. Las tablas guardan parámetros y la
referencia al numeral, nunca el texto de la norma (RL-04).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Estado = Literal["verificado", "por_verificar", "defecto_fuente"]
MetodoDemanda = Literal["por_categoria", "escalonado"]

#: De mejor a peor; un resultado hereda el peor estado de lo que usa.
ORDEN_ESTADO: dict[Estado, int] = {"verificado": 0, "por_verificar": 1, "defecto_fuente": 2}


def peor_estado(estados: list[Estado]) -> Estado:
    return max(estados, key=lambda e: ORDEN_ESTADO[e], default="verificado")


class Dato(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Fuente(Dato):
    norma: str
    numeral: str | None = None
    url: str | None = None


class Verificacion(Dato):
    """Quién comparó la tabla con el documento oficial y cuándo."""

    por: str
    fecha: date


class TablaBase(Dato):
    id: str
    version: str
    vigente_desde: date
    fuente: Fuente
    estado: Estado
    nota: str | None = None
    verificacion: Verificacion | None = None
    unidades: dict[str, str] = Field(default_factory=dict)


# --- Filas ---------------------------------------------------------------


class FilaCarga(Dato):
    tipo: str
    potencia: Decimal = Field(gt=0)
    especial: bool = False
    conexion: Literal["fase_neutro", "linea"] = "fase_neutro"


class FilaCircuitosMinimos(Dato):
    #: Límite superior del tramo de área; `None` es el último tramo.
    area_max: Decimal | None = None
    incluye_max: bool = True
    iluminacion: int | None = Field(default=None, ge=1)
    tomacorrientes: int | None = Field(default=None, ge=1)
    #: Si se da, el mínimo es un circuito de cada tipo por cada tantos m².
    por_cada_m2: Decimal | None = Field(default=None, gt=0)


class FilaFactorDemanda(Dato):
    categoria: str
    area_max: Decimal | None = None
    incluye_max: bool = True
    iluminacion: Decimal = Field(gt=0, le=1)
    tomacorrientes: Decimal = Field(gt=0, le=1)


class FilaFactorEspeciales(Dato):
    cantidad_min: int = Field(ge=1)
    factor: Decimal = Field(gt=0, le=1)


class FilaTramoDemanda(Dato):
    #: Límite superior del tramo de carga; `None` es el resto.
    hasta: Decimal | None = None
    factor: Decimal = Field(gt=0, le=1)


class FilaSistema(Dato):
    id: str
    descripcion: str
    fases: int = Field(ge=1, le=3)
    v_fase_neutro: Decimal = Field(gt=0)
    v_linea: Decimal = Field(gt=0)


class FilaConductor(Dato):
    calibre: str
    seccion_mm2: Decimal = Field(gt=0)
    ampacidad: Decimal = Field(gt=0)
    r_ohm_km: Decimal = Field(gt=0)
    x_ohm_km: Decimal = Field(ge=0)
    #: Área del conductor con aislamiento, para el relleno de ducto.
    area_aislado_mm2: Decimal = Field(gt=0)
    #: Mayor breaker admitido; si falta, el mayor normalizado ≤ ampacidad.
    breaker_max: Decimal | None = Field(default=None, gt=0)


class FilaFactorTemperatura(Dato):
    t_max: Decimal
    factor: Decimal = Field(gt=0)


class FilaFactorAgrupamiento(Dato):
    n_max: int = Field(ge=1)
    factor: Decimal = Field(gt=0, le=1)


class FilaMinimoCalibre(Dato):
    uso: Literal["iluminacion", "tomacorrientes", "especial", "alimentador"]
    calibre: str
    breaker_min: Decimal | None = Field(default=None, gt=0)


class FilaMedidor(Dato):
    #: Mayor breaker principal de la clase; `None` es la última clase.
    breaker_max: Decimal | None = None
    clase: str


class FilaDucto(Dato):
    designacion: str
    area_mm2: Decimal = Field(gt=0)


class FilaTierraEquipos(Dato):
    breaker_max: Decimal = Field(gt=0)
    calibre: str


class FilaParametro(Dato):
    clave: str
    valor: Decimal
    unidad: str | None = None
    nota: str | None = None


class FilaRedondeo(Dato):
    unidad: str
    decimales: int = Field(ge=0, le=9)


class FilaPlantilla(Dato):
    """Reglas de colocación automática para un tipo de ambiente."""

    uso: str
    #: Palabras que identifican el uso en el nombre del ambiente, sin tildes.
    patrones: tuple[str, ...] = ()
    area_por_luminaria_m2: Decimal = Field(gt=0)
    luminarias_min: int = Field(default=1, ge=0)
    separacion_tomas_m: Decimal = Field(gt=0)
    tomas_min: int = Field(default=1, ge=0)
    altura_tomas_m: Decimal = Field(gt=0)
    #: Equipos especiales que se ubican en este ambiente.
    equipos: tuple[str, ...] = ()
    zona_humeda: bool = False
    #: Orden de preferencia para ubicar el tablero; `None` si no lo admite.
    prioridad_tablero: int | None = None
    #: Se propone aire acondicionado si la zona climática lo pide.
    aire: bool = False
    #: Lleva el tomacorriente dedicado de la refrigeradora.
    refrigeradora: bool = False
    #: "perimetro": tomas repartidos por las paredes; "extremos": en los
    #: extremos de las paredes sin puerta (a los lados de cama o mesón).
    tomas_distribucion: Literal["perimetro", "extremos"] = "perimetro"
    #: Zona de la casa para las preguntas del asistente: "social" (sala,
    #: comedor, cocina, estudio), "dormitorios" o "servicio".
    zona_casa: Literal["social", "dormitorios", "servicio"] = "servicio"


class FilaEstiloLuz(Dato):
    """Estilo de iluminación: cuántas luminarias y cómo se reparten."""

    id: str
    nombre: str
    #: Si falta, se usa la densidad de la plantilla del ambiente.
    area_por_luminaria_m2: Decimal | None = Field(default=None, gt=0)
    luminarias_min: int = Field(default=1, ge=1)
    #: "eje": en fila a lo largo del lado mayor; "reticula": en cuadrícula.
    distribucion: Literal["eje", "reticula"] = "eje"
    descripcion: str = ""


class FilaZonaClimatica(Dato):
    id: str
    nombre: str
    #: Si se propone aire acondicionado en los ambientes que lo admiten.
    aire: bool
    btu_por_m2: Decimal = Field(gt=0)


class FilaAire(Dato):
    """Capacidad comercial de un equipo de aire acondicionado."""

    btu: int = Field(gt=0)
    potencia: Decimal = Field(gt=0)
    conexion: Literal["fase_neutro", "linea"] = "linea"


# --- Tablas --------------------------------------------------------------


class TablaCargas(TablaBase):
    tipo: Literal["cargas"]
    filas: tuple[FilaCarga, ...]


class TablaCircuitosMinimos(TablaBase):
    tipo: Literal["circuitos_minimos"]
    filas: tuple[FilaCircuitosMinimos, ...]


class TablaFactoresDemanda(TablaBase):
    tipo: Literal["factores_demanda"]
    filas: tuple[FilaFactorDemanda, ...]


class TablaFactoresEspeciales(TablaBase):
    tipo: Literal["factores_especiales"]
    filas: tuple[FilaFactorEspeciales, ...]


class TablaTramosDemanda(TablaBase):
    tipo: Literal["tramos_demanda"]
    filas: tuple[FilaTramoDemanda, ...]


class TablaSistemas(TablaBase):
    tipo: Literal["sistemas_tension"]
    filas: tuple[FilaSistema, ...]


class TablaConductores(TablaBase):
    """Catálogo ordenado de menor a mayor calibre."""

    tipo: Literal["conductores"]
    filas: tuple[FilaConductor, ...]


class TablaFactoresTemperatura(TablaBase):
    tipo: Literal["factores_temperatura"]
    filas: tuple[FilaFactorTemperatura, ...]


class TablaFactoresAgrupamiento(TablaBase):
    tipo: Literal["factores_agrupamiento"]
    filas: tuple[FilaFactorAgrupamiento, ...]


class TablaMinimosCalibre(TablaBase):
    tipo: Literal["minimos_calibre"]
    filas: tuple[FilaMinimoCalibre, ...]


class TablaSerie(TablaBase):
    """Serie de valores normalizados, de menor a mayor."""

    tipo: Literal["serie"]
    serie: Literal["breakers", "espacios_tablero", "barras"]
    filas: tuple[Decimal, ...]


class TablaMedidores(TablaBase):
    tipo: Literal["medidores"]
    filas: tuple[FilaMedidor, ...]


class TablaDuctos(TablaBase):
    tipo: Literal["ductos"]
    filas: tuple[FilaDucto, ...]


class TablaTierraEquipos(TablaBase):
    tipo: Literal["tierra_equipos"]
    filas: tuple[FilaTierraEquipos, ...]


class TablaParametros(TablaBase):
    tipo: Literal["parametros"]
    filas: tuple[FilaParametro, ...]


class TablaPlantillas(TablaBase):
    """Plantillas por tipo de ambiente; el orden decide a igualdad de patrones."""

    tipo: Literal["plantillas_ambiente"]
    filas: tuple[FilaPlantilla, ...]


class TablaEstilosLuz(TablaBase):
    tipo: Literal["estilos_iluminacion"]
    filas: tuple[FilaEstiloLuz, ...]


class TablaZonasClimaticas(TablaBase):
    tipo: Literal["zonas_climaticas"]
    filas: tuple[FilaZonaClimatica, ...]


class TablaAires(TablaBase):
    """Capacidades en orden creciente de BTU."""

    tipo: Literal["aires"]
    filas: tuple[FilaAire, ...]


class TablaRedondeo(TablaBase):
    tipo: Literal["redondeo"]
    filas: tuple[FilaRedondeo, ...]


Tabla = Annotated[
    TablaCargas
    | TablaCircuitosMinimos
    | TablaFactoresDemanda
    | TablaFactoresEspeciales
    | TablaTramosDemanda
    | TablaSistemas
    | TablaConductores
    | TablaFactoresTemperatura
    | TablaFactoresAgrupamiento
    | TablaMinimosCalibre
    | TablaSerie
    | TablaMedidores
    | TablaDuctos
    | TablaTierraEquipos
    | TablaParametros
    | TablaPlantillas
    | TablaEstilosLuz
    | TablaZonasClimaticas
    | TablaAires
    | TablaRedondeo,
    Field(discriminator="tipo"),
]


class MetaPerfil(Dato):
    """Contenido de `perfil.yaml`."""

    id: str
    version: str
    nombre: str
    distribuidora: str
    norma_base: str
    sistema_defecto: str
    demanda_metodo: MetodoDemanda
    nota: str | None = None
    tablas: tuple[str, ...]


class RefTabla(Dato):
    """Rastro de una consulta a una tabla: qué fila se usó y en qué estado está."""

    id: str
    version: str
    fila: str
    estado: Estado
