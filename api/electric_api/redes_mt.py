"""Rutas de redes de media tensión: extensión de red sobre el mapa."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Literal

from electric.cli import AVISO_BORRADOR
from electric.errores import ErrorElectric
from electric.mt import (
    ErrorSIG,
    ExtensionMT,
    RedCalculada,
    RedExistente,
    calcular_red,
    consultar_geoportal,
    generar_kml,
    generar_planimetria,
    generar_unifilar_mt,
    leer_geojson,
)
from electric.mt.modelo import Arranque, PosteNuevo
from electric.perfiles import Perfil
from electric.salida_cad import renderizar
from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from electric_api.config import Config
from electric_api.db import RedMTBD, ahora
from electric_api.esquemas import Esquema, ResultadoOut
from electric_api.problemas import Problema
from electric_api.servicio import Perfiles, resultado_a_salida

rutas = APIRouter(prefix="/api/v1", tags=["redes-mt"])


def _sesion(request: Request) -> Iterator[Session]:
    with request.app.state.sesiones() as sesion:
        yield sesion


def _perfiles(request: Request) -> Perfiles:
    perfiles: Perfiles = request.app.state.perfiles
    return perfiles


SesionDep = Annotated[Session, Depends(_sesion)]
PerfilesDep = Annotated[Perfiles, Depends(_perfiles)]


# --- Esquemas ----------------------------------------------------------------------


class BorradorRedMT(Esquema):
    """Extensión en edición: puede no tener arranque ni postes todavía."""

    nombre: str = Field(min_length=1, max_length=200)
    perfil: str = "cnel-ep"
    propietario: str = Field(default="", max_length=200)
    tension_kv: Decimal = Field(default=Decimal("13.8"), gt=0)
    fases: Literal[1, 3] = 3
    conductor: str = "ACSR 1/0 AWG"
    zona: Literal["urbana", "rural"] = "urbana"
    fp: Decimal = Field(default=Decimal("0.9"), gt=0, le=1)
    arranque: Arranque | None = None
    postes: list[PosteNuevo] = Field(default=[], max_length=2000)


class GuardarRedMT(Esquema):
    revision: int
    datos: BorradorRedMT


class RedMTResumen(Esquema):
    id: str
    nombre: str
    propietario: str
    postes: int
    actualizado: str


class RedMTDetalle(Esquema):
    id: str
    revision: int
    creado: str
    actualizado: str
    datos: BorradorRedMT
    existente: RedExistente | None


class VanoOut(Esquema):
    desde: str
    hasta: str
    longitud_m: float
    carga_kva: float
    caida_pct: float
    caida_acumulada_pct: float
    excede: bool


class PosteOut(Esquema):
    id: str
    lat: float
    lon: float
    angulo: float | None
    estructura: str
    estructura_nombre: str
    codigo: str | None
    transformador_kva: float | None
    fusible: str | None


class CalculoRedMT(Esquema):
    estado: Literal["listo", "incompleto"]
    revision: int
    aviso: str
    pendientes: list[str] = []
    longitud_m: float = 0
    kva_total: float = 0
    corriente_a: float = 0
    caida_pct: float = 0
    ik_arranque_ka: float = 0
    ik_final_ka: float = 0
    fusible_derivacion: str | None = None
    postes: list[PosteOut] = []
    vanos: list[VanoOut] = []
    resultados: list[ResultadoOut] = []
    avisos: list[str] = []


class OpcionMT(Esquema):
    id: str
    nombre: str


class OpcionesMT(Esquema):
    conductores: list[OpcionMT]
    estructuras: list[OpcionMT]
    #: Si el perfil tiene configuradas las URL de las capas del geoportal.
    geoportal_configurado: bool


class Existente(Esquema):
    red: RedExistente
    avisos: list[str]


# --- Utilidades --------------------------------------------------------------------


def _perfil(perfiles: Perfiles, id: str) -> Perfil:
    perfil = next((p for p in perfiles.todos() if p.meta.id == id), None)
    if perfil is None or not perfil.conductores_mt():
        raise Problema(
            422, "perfil_no_disponible", "El perfil no admite redes de media tensión", id
        )
    return perfil


def _buscar(sesion: Session, id: str) -> RedMTBD:
    fila = sesion.get(RedMTBD, id)
    if fila is None:
        raise Problema(404, "red_no_encontrada", "La red de media tensión no existe")
    return fila


def _existente(fila: RedMTBD) -> RedExistente | None:
    return RedExistente.model_validate_json(fila.existente) if fila.existente else None


def _detalle(fila: RedMTBD) -> RedMTDetalle:
    return RedMTDetalle(
        id=fila.id,
        revision=fila.revision,
        creado=fila.creado,
        actualizado=fila.actualizado,
        datos=BorradorRedMT.model_validate_json(fila.datos),
        existente=_existente(fila),
    )


def _f(valor: Decimal) -> float:
    return float(round(valor, 4))


def _calcular(datos: BorradorRedMT, perfil: Perfil) -> RedCalculada | list[str]:
    pendientes = []
    if datos.arranque is None:
        pendientes.append("Marque el punto de arranque en la red existente.")
    if not datos.postes:
        pendientes.append("Agregue al menos un poste nuevo.")
    if pendientes:
        return pendientes
    try:
        extension = ExtensionMT.model_validate(datos.model_dump(exclude={"perfil", "propietario"}))
        return calcular_red(extension, perfil)
    except ValidationError as error:
        return [e["msg"] for e in error.errors()]
    except ErrorElectric as error:
        return [str(error)]


def _red_calculada(sesion: Session, id: str, perfiles: Perfiles) -> tuple[RedMTBD, RedCalculada]:
    fila = _buscar(sesion, id)
    datos = BorradorRedMT.model_validate_json(fila.datos)
    red = _calcular(datos, _perfil(perfiles, datos.perfil))
    if isinstance(red, list):
        raise Problema(422, "red_incompleta", "Todavía no se puede dibujar la red", " ".join(red))
    return fila, red


# --- Rutas -------------------------------------------------------------------------


@rutas.get("/red-mt/opciones")
def opciones_mt(perfiles: PerfilesDep, perfil: Annotated[str, Query()] = "cnel-ep") -> OpcionesMT:
    p = _perfil(perfiles, perfil)
    tipos, _ = p.estructuras_mt()
    return OpcionesMT(
        conductores=[
            OpcionMT(id=c.calibre, nombre=f"{c.calibre} ({c.ampacidad} A)")
            for c in p.conductores_mt()
        ],
        estructuras=[OpcionMT(id=t.id, nombre=t.nombre) for t in tipos],
        geoportal_configurado=all(c.url for c in p.capas_sig()) and bool(p.capas_sig()),
    )


@rutas.get("/redes-mt")
def listar_redes(sesion: SesionDep) -> list[RedMTResumen]:
    filas = sesion.scalars(select(RedMTBD).order_by(RedMTBD.actualizado.desc())).all()
    salida = []
    for f in filas:
        datos = BorradorRedMT.model_validate_json(f.datos)
        salida.append(
            RedMTResumen(
                id=f.id,
                nombre=f.nombre,
                propietario=datos.propietario,
                postes=len(datos.postes),
                actualizado=f.actualizado,
            )
        )
    return salida


def _nueva(sesion: Session, datos: BorradorRedMT) -> RedMTBD:
    momento = ahora()
    fila = RedMTBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        revision=1,
        datos=datos.model_dump_json(),
        existente="",
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    return fila


@rutas.post("/redes-mt", status_code=201)
def crear_red(datos: BorradorRedMT, sesion: SesionDep, perfiles: PerfilesDep) -> RedMTDetalle:
    _perfil(perfiles, datos.perfil)
    fila = _nueva(sesion, datos)
    sesion.commit()
    return _detalle(fila)


@rutas.get("/redes-mt/{id}")
def leer_red(id: str, sesion: SesionDep) -> RedMTDetalle:
    return _detalle(_buscar(sesion, id))


@rutas.put("/redes-mt/{id}")
def guardar_red(
    id: str, cuerpo: GuardarRedMT, sesion: SesionDep, perfiles: PerfilesDep
) -> RedMTDetalle:
    fila = _buscar(sesion, id)
    if cuerpo.revision != fila.revision:
        raise Problema(
            409,
            "revision_desactualizada",
            "La red cambió desde que la abrió",
            f"Usted editaba la revisión {cuerpo.revision} y la actual es {fila.revision}.",
        )
    _perfil(perfiles, cuerpo.datos.perfil)
    fila.nombre = cuerpo.datos.nombre
    fila.datos = cuerpo.datos.model_dump_json()
    fila.revision += 1
    fila.actualizado = ahora()
    sesion.commit()
    return _detalle(fila)


@rutas.delete("/redes-mt/{id}", status_code=204)
def borrar_red(id: str, sesion: SesionDep) -> Response:
    sesion.delete(_buscar(sesion, id))
    sesion.commit()
    return Response(status_code=204)


@rutas.get("/redes-mt/{id}/calculo")
def calcular_red_mt(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> CalculoRedMT:
    fila = _buscar(sesion, id)
    datos = BorradorRedMT.model_validate_json(fila.datos)
    perfil = _perfil(perfiles, datos.perfil)
    red = _calcular(datos, perfil)
    if isinstance(red, list):
        return CalculoRedMT(
            estado="incompleto", revision=fila.revision, aviso=AVISO_BORRADOR, pendientes=red
        )
    return CalculoRedMT(
        estado="listo",
        revision=fila.revision,
        aviso=AVISO_BORRADOR,
        longitud_m=_f(red.longitud_m),
        kva_total=_f(red.kva_total),
        corriente_a=_f(red.corriente_a),
        caida_pct=_f(red.caida_pct),
        ik_arranque_ka=_f(red.ik_arranque_ka),
        ik_final_ka=_f(red.ik_final_ka),
        fusible_derivacion=red.fusible_derivacion,
        postes=[
            PosteOut(
                id=p.id,
                lat=float(p.lat),
                lon=float(p.lon),
                angulo=float(p.angulo) if p.angulo is not None else None,
                estructura=p.estructura,
                estructura_nombre=p.estructura_nombre,
                codigo=p.codigo,
                transformador_kva=float(p.transformador_kva) if p.transformador_kva else None,
                fusible=p.fusible,
            )
            for p in red.postes
        ],
        vanos=[
            VanoOut(
                desde=v.desde,
                hasta=v.hasta,
                longitud_m=_f(v.longitud_m),
                carga_kva=_f(v.carga_kva),
                caida_pct=_f(v.caida_pct),
                caida_acumulada_pct=_f(v.caida_acumulada_pct),
                excede=v.excede,
            )
            for v in red.vanos
        ],
        resultados=[resultado_a_salida(r, perfil) for r in red.resultados],
        avisos=list(red.avisos),
    )


@rutas.post("/redes-mt/{id}/existente/geoportal")
def existente_geoportal(
    id: str,
    sesion: SesionDep,
    perfiles: PerfilesDep,
    lat: Annotated[Decimal, Query(ge=-90, le=90)],
    lon: Annotated[Decimal, Query(ge=-180, le=180)],
    radio: Annotated[int, Query(ge=20, le=3000)] = 300,
) -> Existente:
    """Red existente alrededor de un punto, consultando el geoportal de CNEL."""
    fila = _buscar(sesion, id)
    perfil = _perfil(perfiles, BorradorRedMT.model_validate_json(fila.datos).perfil)
    try:
        red, avisos = consultar_geoportal(perfil, lat, lon, radio)
    except ErrorSIG as error:
        raise Problema(
            502,
            error.codigo,
            "No se pudo leer el geoportal de CNEL",
            f"{error}. Mientras tanto puede cargar la red existente desde un archivo GeoJSON.",
        ) from error
    fila.existente = red.model_dump_json()
    fila.actualizado = ahora()
    sesion.commit()
    return Existente(red=red, avisos=avisos)


@rutas.post("/redes-mt/{id}/existente/archivo")
def existente_archivo(
    id: str,
    sesion: SesionDep,
    perfiles: PerfilesDep,
    contenido: Annotated[bytes, Body(media_type="application/octet-stream")],
) -> Existente:
    """Red existente desde un GeoJSON exportado del SIG."""
    fila = _buscar(sesion, id)
    perfil = _perfil(perfiles, BorradorRedMT.model_validate_json(fila.datos).perfil)
    try:
        red, avisos = leer_geojson(contenido, perfil)
    except ErrorElectric as error:
        raise Problema(422, error.codigo, "No se pudo leer la red existente", str(error)) from error
    fila.existente = red.model_dump_json()
    fila.actualizado = ahora()
    sesion.commit()
    return Existente(red=red, avisos=avisos)


@rutas.get(
    "/redes-mt/{id}/red.kml",
    response_class=Response,
    responses={200: {"content": {"application/vnd.google-earth.kml+xml": {}}}},
)
def descargar_kml(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> Response:
    _, red = _red_calculada(sesion, id, perfiles)
    return Response(
        generar_kml(red),
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": 'attachment; filename="red.kml"'},
    )


TIPOS = {"dxf": "application/dxf", "png": "image/png", "pdf": "application/pdf"}


@rutas.get(
    "/redes-mt/{id}/{plano}.{formato}",
    response_class=Response,
    responses={200: {"content": {t: {} for t in TIPOS.values()}}},
)
def descargar_plano(
    id: str,
    plano: Literal["planimetria", "unifilar"],
    formato: Literal["dxf", "png", "pdf"],
    sesion: SesionDep,
    perfiles: PerfilesDep,
) -> Response:
    fila, red = _red_calculada(sesion, id, perfiles)
    dxf = (
        generar_planimetria(red, _existente(fila))
        if plano == "planimetria"
        else (generar_unifilar_mt(red))
    )
    contenido = dxf if formato == "dxf" else renderizar(dxf, formato)
    disposicion = "attachment" if formato == "dxf" else "inline"
    return Response(
        contenido,
        media_type=TIPOS[formato],
        headers={"Content-Disposition": f'{disposicion}; filename="{plano}.{formato}"'},
    )


@rutas.post("/ejemplos/red-mt", status_code=201)
def crear_ejemplo_red(request: Request, sesion: SesionDep, perfiles: PerfilesDep) -> RedMTDetalle:
    """Crea la extensión de red de ejemplo del repositorio."""
    config: Config = request.app.state.config
    ruta = config.ejemplos / "red-mt" / "extension.json"
    if not ruta.is_file():
        raise Problema(404, "ejemplo_no_disponible", "El ejemplo no está disponible")
    _perfil(perfiles, "cnel-ep")
    extension = ExtensionMT.model_validate_json(ruta.read_text("utf-8"))
    datos = BorradorRedMT.model_validate(extension.model_dump())
    fila = _nueva(sesion, datos)
    sesion.commit()
    return _detalle(fila)
