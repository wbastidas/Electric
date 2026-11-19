"""Rutas de urbanizaciones y lotizaciones."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Literal

from electric.cli import AVISO_BORRADOR
from electric.errores import ErrorElectric
from electric.perfiles import Perfil
from electric.salida_cad import renderizar
from electric.urbanizacion import (
    CargaComunal,
    Manzana,
    Urbanizacion,
    UrbanizacionCalculada,
    calcular_urbanizacion,
    generar_plano_urbanizacion,
)
from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from electric_api.config import Config
from electric_api.db import UrbanizacionBD, ahora
from electric_api.esquemas import Esquema, ResultadoOut
from electric_api.problemas import Problema
from electric_api.servicio import Perfiles, resultado_a_salida

rutas = APIRouter(prefix="/api/v1", tags=["urbanizaciones"])


def _sesion(request: Request) -> Iterator[Session]:
    with request.app.state.sesiones() as sesion:
        yield sesion


def _perfiles(request: Request) -> Perfiles:
    perfiles: Perfiles = request.app.state.perfiles
    return perfiles


SesionDep = Annotated[Session, Depends(_sesion)]
PerfilesDep = Annotated[Perfiles, Depends(_perfiles)]


class BorradorUrbanizacion(Esquema):
    nombre: str = Field(min_length=1, max_length=200)
    perfil: str = "cnel-ep"
    propietario: str = Field(default="", max_length=200)
    estrato: str = "C"
    sistema: str = "monofasico_trifilar_120_240"
    fases_transformador: Literal[1, 3] = 1
    kva_max_transformador: Decimal | None = Field(default=None, gt=0)
    ancho_calle_m: Decimal = Field(default=Decimal(10), gt=0)
    separacion_luminarias_m: Decimal | None = Field(default=None, gt=0)
    potencia_luminaria_w: Decimal | None = Field(default=None, gt=0)
    manzanas: list[Manzana] = Field(default=[], max_length=60)
    comunales: list[CargaComunal] = Field(default=[], max_length=50)


class GuardarUrbanizacion(Esquema):
    revision: int
    datos: BorradorUrbanizacion


class UrbanizacionResumen(Esquema):
    id: str
    nombre: str
    propietario: str
    lotes: int
    actualizado: str


class UrbanizacionDetalle(Esquema):
    id: str
    revision: int
    creado: str
    actualizado: str
    datos: BorradorUrbanizacion


class CircuitoOut(Esquema):
    lado: str
    lotes: int
    longitud_m: float
    corriente_a: float
    conductor: str | None
    caida_pct: float | None


class SectorOut(Esquema):
    id: str
    calle: int
    lotes: int
    luminarias: int
    comunal_kva: float
    demanda_kva: float
    kva: float | None
    circuitos: list[CircuitoOut]


class CalculoUrbanizacion(Esquema):
    estado: Literal["listo", "incompleto"]
    revision: int
    aviso: str
    pendientes: list[str] = []
    lotes: int = 0
    calles: int = 0
    dmu_kva: float = 0
    demanda_kva: float = 0
    alumbrado_kva: float = 0
    luminarias: int = 0
    kva_instalados: float = 0
    corriente_mt_a: float = 0
    tension_mt_kv: float = 0
    sectores: list[SectorOut] = []
    resultados: list[ResultadoOut] = []
    avisos: list[str] = []


def _perfil(perfiles: Perfiles, id: str) -> Perfil:
    perfil = next((p for p in perfiles.todos() if p.meta.id == id), None)
    if perfil is None or not perfil.demandas_usuario():
        raise Problema(422, "perfil_no_disponible", "El perfil no admite urbanizaciones", id)
    return perfil


def _buscar(sesion: Session, id: str) -> UrbanizacionBD:
    fila = sesion.get(UrbanizacionBD, id)
    if fila is None:
        raise Problema(404, "urbanizacion_no_encontrada", "Urbanización no encontrada")
    return fila


def _detalle(fila: UrbanizacionBD) -> UrbanizacionDetalle:
    return UrbanizacionDetalle(
        id=fila.id,
        revision=fila.revision,
        creado=fila.creado,
        actualizado=fila.actualizado,
        datos=BorradorUrbanizacion.model_validate_json(fila.datos),
    )


def _f(valor: Decimal) -> float:
    return round(float(valor), 4)


def _calcular(datos: BorradorUrbanizacion, perfil: Perfil) -> UrbanizacionCalculada | list[str]:
    if not datos.manzanas:
        return ["Agregue al menos una manzana con sus lotes."]
    try:
        u = Urbanizacion.model_validate(datos.model_dump(exclude={"perfil", "propietario"}))
        return calcular_urbanizacion(u, perfil)
    except ValidationError as error:
        return [e["msg"] for e in error.errors()]
    except (ErrorElectric, ValueError) as error:
        return [str(error)]


def _nueva(sesion: Session, datos: BorradorUrbanizacion) -> UrbanizacionBD:
    momento = ahora()
    fila = UrbanizacionBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        revision=1,
        datos=datos.model_dump_json(),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    return fila


@rutas.get("/urbanizaciones")
def listar(sesion: SesionDep) -> list[UrbanizacionResumen]:
    filas = sesion.scalars(select(UrbanizacionBD).order_by(UrbanizacionBD.actualizado.desc()))
    salida = []
    for f in filas.all():
        datos = BorradorUrbanizacion.model_validate_json(f.datos)
        salida.append(
            UrbanizacionResumen(
                id=f.id,
                nombre=f.nombre,
                propietario=datos.propietario,
                lotes=sum(m.lotes for m in datos.manzanas),
                actualizado=f.actualizado,
            )
        )
    return salida


@rutas.post("/urbanizaciones", status_code=201)
def crear(
    datos: BorradorUrbanizacion, sesion: SesionDep, perfiles: PerfilesDep
) -> UrbanizacionDetalle:
    _perfil(perfiles, datos.perfil)
    fila = _nueva(sesion, datos)
    sesion.commit()
    return _detalle(fila)


@rutas.get("/urbanizaciones/{id}")
def leer(id: str, sesion: SesionDep) -> UrbanizacionDetalle:
    return _detalle(_buscar(sesion, id))


@rutas.put("/urbanizaciones/{id}")
def guardar(
    id: str, cuerpo: GuardarUrbanizacion, sesion: SesionDep, perfiles: PerfilesDep
) -> UrbanizacionDetalle:
    fila = _buscar(sesion, id)
    if cuerpo.revision != fila.revision:
        raise Problema(
            409,
            "revision_desactualizada",
            "La urbanización cambió desde que la abrió",
            f"Usted editaba la revisión {cuerpo.revision} y la actual es {fila.revision}.",
        )
    _perfil(perfiles, cuerpo.datos.perfil)
    fila.nombre = cuerpo.datos.nombre
    fila.datos = cuerpo.datos.model_dump_json()
    fila.revision += 1
    fila.actualizado = ahora()
    sesion.commit()
    return _detalle(fila)


@rutas.delete("/urbanizaciones/{id}", status_code=204)
def borrar(id: str, sesion: SesionDep) -> Response:
    sesion.delete(_buscar(sesion, id))
    sesion.commit()
    return Response(status_code=204)


@rutas.get("/urbanizaciones/{id}/calculo")
def calcular(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> CalculoUrbanizacion:
    fila = _buscar(sesion, id)
    datos = BorradorUrbanizacion.model_validate_json(fila.datos)
    perfil = _perfil(perfiles, datos.perfil)
    c = _calcular(datos, perfil)
    if isinstance(c, list):
        return CalculoUrbanizacion(
            estado="incompleto", revision=fila.revision, aviso=AVISO_BORRADOR, pendientes=c
        )
    return CalculoUrbanizacion(
        estado="listo",
        revision=fila.revision,
        aviso=AVISO_BORRADOR,
        lotes=len(c.lotes),
        calles=len(c.calles),
        dmu_kva=_f(c.dmu_kva),
        demanda_kva=_f(c.demanda_kva),
        alumbrado_kva=_f(c.alumbrado_kva),
        luminarias=sum(len(k.luminarias) for k in c.calles),
        kva_instalados=_f(c.kva_instalados),
        corriente_mt_a=_f(c.corriente_mt_a),
        tension_mt_kv=_f(c.tension_mt_kv),
        sectores=[
            SectorOut(
                id=s.id,
                calle=s.calle,
                lotes=len(s.lotes),
                luminarias=s.luminarias,
                comunal_kva=_f(s.comunal_kva),
                demanda_kva=_f(s.demanda_kva),
                kva=_f(s.kva) if s.kva is not None else None,
                circuitos=[
                    CircuitoOut(
                        lado=x.lado,
                        lotes=x.lotes,
                        longitud_m=_f(x.longitud_m),
                        corriente_a=_f(x.corriente_a),
                        conductor=x.conductor.texto if x.conductor else None,
                        caida_pct=_f(x.conductor.caida_pct) if x.conductor else None,
                    )
                    for x in s.circuitos
                ],
            )
            for s in c.sectores
        ],
        resultados=[resultado_a_salida(r, perfil) for r in c.resultados],
        avisos=list(c.avisos),
    )


TIPOS = {"dxf": "application/dxf", "png": "image/png", "pdf": "application/pdf"}


@rutas.get(
    "/urbanizaciones/{id}/plano.{formato}",
    response_class=Response,
    responses={200: {"content": {t: {} for t in TIPOS.values()}}},
)
def descargar_plano(
    id: str, formato: Literal["dxf", "png", "pdf"], sesion: SesionDep, perfiles: PerfilesDep
) -> Response:
    fila = _buscar(sesion, id)
    datos = BorradorUrbanizacion.model_validate_json(fila.datos)
    c = _calcular(datos, _perfil(perfiles, datos.perfil))
    if isinstance(c, list):
        raise Problema(
            422, "urbanizacion_incompleta", "La urbanización está incompleta", " ".join(c)
        )
    dxf = generar_plano_urbanizacion(c)
    contenido = dxf if formato == "dxf" else renderizar(dxf, formato)
    disposicion = "attachment" if formato == "dxf" else "inline"
    return Response(
        contenido,
        media_type=TIPOS[formato],
        headers={"Content-Disposition": f'{disposicion}; filename="urbanizacion.{formato}"'},
    )


@rutas.post("/ejemplos/urbanizacion", status_code=201)
def crear_ejemplo(
    request: Request, sesion: SesionDep, perfiles: PerfilesDep
) -> UrbanizacionDetalle:
    """Crea la lotización de ejemplo del repositorio."""
    config: Config = request.app.state.config
    ruta = config.ejemplos / "urbanizacion" / "urbanizacion.json"
    if not ruta.is_file():
        raise Problema(404, "ejemplo_no_disponible", "El ejemplo no está disponible")
    _perfil(perfiles, "cnel-ep")
    fila = _nueva(sesion, BorradorUrbanizacion.model_validate_json(ruta.read_text("utf-8")))
    sesion.commit()
    return _detalle(fila)
