"""Esquemas de entrada y salida de la API."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from electric.diseno.edicion import Edicion
from electric.diseno.opciones import Respuestas
from electric.modelo.entidades import (
    CargaEspecial,
    Circuito,
    Predio,
    Preferencias,
    Proyectista,
    Punto,
    RefPerfil,
    Supuesto,
    Tablero,
)
from electric.modelo.plano import Plano
from electric.perfiles.esquema import Estado, RefTabla
from pydantic import BaseModel, ConfigDict, Field


class Esquema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Borrador(Esquema):
    """Proyecto en edición.

    Tiene los mismos campos que el proyecto del núcleo, pero admite estar
    incompleto: lo que falta se devuelve como lista de pendientes al calcular.
    """

    nombre: str = Field(min_length=1, max_length=200)
    uso: str = "vivienda_unifamiliar"
    area_construida_m2: Decimal | None = Field(default=None, gt=0)
    perfil: RefPerfil
    predio: Predio = Predio()
    proyectista: Proyectista = Proyectista()
    sistema: str | None = None
    puntos: list[Punto] = []
    cargas_especiales: list[CargaEspecial] = []
    circuitos: list[Circuito] = []
    tablero: Tablero | None = None
    supuestos: list[Supuesto] = []
    #: Ambientes leídos del plano y ubicación de la instalación diseñada.
    plano: Plano | None = None
    #: Criterios del diseño automático de este escenario.
    preferencias: Preferencias = Preferencias()


class ProyectoResumen(Esquema):
    id: str
    nombre: str
    revision: int
    propietario: str
    creado: str
    actualizado: str
    #: Vivienda de varios pisos a la que pertenece, si es una planta.
    edificacion_id: str | None = None


class PlantaRef(Esquema):
    edificacion_id: str
    edificacion: str
    piso: str


class ProyectoDetalle(Esquema):
    id: str
    revision: int
    creado: str
    actualizado: str
    datos: Borrador
    #: Acción que se desharía con «Deshacer»; nada si no hay a qué volver.
    deshacer: str | None = None
    #: Nombre del escenario, si el proyecto tiene varios.
    escenario: str | None = None
    #: Si el proyecto es una planta de una vivienda de varios pisos.
    planta: PlantaRef | None = None


class Guardar(Esquema):
    #: Revisión que el cliente tenía al empezar a editar.
    revision: int
    datos: Borrador


class Pendiente(Esquema):
    """Algo que el usuario debe resolver antes de poder calcular."""

    codigo: str
    mensaje: str


class DatoResumenOut(Esquema):
    etiqueta: str
    texto: str
    id: str
    sujeto: str
    estado: Estado


class FilaCuadroOut(Esquema):
    circuito: str
    tipo: str
    fase: str
    carga: str
    corriente: str
    breaker: str
    conductor: str
    tierra: str
    ducto: str
    longitud: str
    caida: str


class ValorOut(Esquema):
    clave: str
    texto: str


class ResultadoOut(Esquema):
    id: str
    sujeto: str
    nombre: str
    texto: str
    unidad: str
    formula: str
    entradas: list[ValorOut]
    detalle: list[ValorOut]
    tablas: list[RefTabla]
    supuestos: list[str]
    avisos: list[str]
    estado: Estado


class TablaPendiente(Esquema):
    id: str
    version: str
    estado: Estado


class Calculos(Esquema):
    #: `listo` trae resultados; `incompleto` trae solo los pendientes.
    estado: Literal["listo", "incompleto"]
    revision: int
    aviso: str
    pendientes: list[Pendiente] = []
    huella: str | None = None
    resumen: list[DatoResumenOut] = []
    cuadro: list[FilaCuadroOut] = []
    resultados: list[ResultadoOut] = []
    avisos: list[str] = []
    supuestos: list[str] = []
    tablas_sin_verificar: list[TablaPendiente] = []


class Revision(Esquema):
    #: Revisión que el cliente tenía; evita pisar cambios de otra persona.
    revision: int


class Editar(Esquema):
    revision: int
    ediciones: list[Edicion] = Field(min_length=1, max_length=200)


class DisenoOut(Esquema):
    proyecto: ProyectoDetalle
    #: Decisiones del diseño automático que conviene revisar.
    avisos: list[str]


class LineaFondo(Esquema):
    #: muro, puerta, ventana, mobiliario, cota u otro.
    clase: str
    #: Polilínea en metros: [[x, y], …].
    puntos: list[tuple[float, float]]


class TextoFondo(Esquema):
    x: float
    y: float
    texto: str


class Fondo(Esquema):
    """Plano del arquitecto como primitivas simples, para dibujarlo de referencia."""

    archivo: str
    unidad: str
    capas: dict[str, str]
    lineas: list[LineaFondo]
    textos: list[TextoFondo]
    #: Límites del dibujo: x mínimo, y mínimo, x máximo, y máximo.
    limites: tuple[float, float, float, float]


class OpcionUso(Esquema):
    uso: str
    equipos: list[str]
    aire: bool = False
    tomas_distribucion: str = "perimetro"


class OpcionEstilo(Esquema):
    id: str
    nombre: str
    descripcion: str


class OpcionZona(Esquema):
    id: str
    nombre: str
    aire: bool


class Asistente(Esquema):
    revision: int
    respuestas: Respuestas


class NuevoEscenario(Esquema):
    nombre: str = Field(min_length=1, max_length=80)


class EscenarioOut(Esquema):
    """Un escenario del proyecto, resumido para compararlo con los demás."""

    id: str
    nombre: str
    revision: int
    estado: Literal["listo", "incompleto"]
    iluminacion: str
    zona_climatica: str | None
    luminarias: int
    tomacorrientes: int
    aires: int
    circuitos: int
    resumen: list[DatoResumenOut] = []


class EntradaBitacora(Esquema):
    revision: int
    accion: str
    autor: str
    fecha: str
    huella: str
    resumen: str


class SistemaOut(Esquema):
    id: str
    descripcion: str


class CargaOut(Esquema):
    tipo: str
    potencia: Decimal
    especial: bool
    conexion: str


class TablaOut(Esquema):
    id: str
    version: str
    estado: Estado
    fuente: str
    nota: str | None


class PerfilOut(Esquema):
    id: str
    version: str
    nombre: str
    distribuidora: str
    nota: str | None
    sistema_defecto: str
    sistemas: list[SistemaOut]
    cargas: list[CargaOut]
    #: Usos de ambiente que admite el diseño automático; vacío si el perfil no lo trae.
    usos: list[OpcionUso]
    estilos: list[OpcionEstilo] = []
    zonas: list[OpcionZona] = []
    tablas: list[TablaOut]
