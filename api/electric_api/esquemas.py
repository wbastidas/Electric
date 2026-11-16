"""Esquemas de entrada y salida de la API."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from electric.modelo.entidades import (
    CargaEspecial,
    Circuito,
    Predio,
    Proyectista,
    Punto,
    RefPerfil,
    Supuesto,
    Tablero,
)
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


class ProyectoResumen(Esquema):
    id: str
    nombre: str
    revision: int
    propietario: str
    creado: str
    actualizado: str


class ProyectoDetalle(Esquema):
    id: str
    revision: int
    creado: str
    actualizado: str
    datos: Borrador


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
    tablas: list[TablaOut]
