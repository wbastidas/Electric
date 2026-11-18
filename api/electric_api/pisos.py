"""Rutas de viviendas de varios pisos.

Una edificación agrupa un proyecto por planta. Cada planta se carga con su
plano, se diseña sola y se edita en el editor de siempre; la edificación junta
las plantas en el tablero principal y los subtableros con sus alimentadores.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Literal

from electric.calculo.resultado import ALIMENTADOR, PROYECTO
from electric.cli import AVISO_BORRADOR
from electric.errores import ErrorElectric
from electric.flujo import proyecto_desde_plano
from electric.modelo import a_json_canonico
from electric.modelo.entidades import Preferencias, RefPerfil
from electric.perfiles import Perfil
from electric.pisos import Edificacion, Piso, calcular_pisos, codigo_piso
from electric.salida_cad import renderizar
from electric.salida_cad.unifilar_pisos import generar_unifilar_pisos
from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from electric_api.config import Config
from electric_api.db import ArchivoBD, EdificacionBD, PisoBD, ProyectoBD, ahora
from electric_api.esquemas import Borrador, Esquema, ProyectoDetalle
from electric_api.problemas import Problema
from electric_api.servicio import Perfiles, proyecto_del_borrador

rutas = APIRouter(prefix="/api/v1", tags=["pisos"])


def _sesion(request: Request) -> Iterator[Session]:
    with request.app.state.sesiones() as sesion:
        yield sesion


def _perfiles(request: Request) -> Perfiles:
    perfiles: Perfiles = request.app.state.perfiles
    return perfiles


SesionDep = Annotated[Session, Depends(_sesion)]
PerfilesDep = Annotated[Perfiles, Depends(_perfiles)]


# --- Esquemas ----------------------------------------------------------------------


class DatosEdificacion(Esquema):
    nombre: str = Field(min_length=1, max_length=200)
    perfil: RefPerfil
    propietario: str = Field(default="", max_length=200)
    #: Longitud del alimentador del medidor al tablero principal.
    medidor_m: Decimal = Field(default=Decimal(15), gt=0)
    #: Altura de piso a piso, para el tramo vertical de los alimentadores.
    altura_piso_m: Decimal = Field(default=Decimal("2.8"), gt=0)
    #: Criterios de diseño de todas las plantas.
    preferencias: Preferencias = Preferencias()


class PisoOut(Esquema):
    proyecto_id: str
    nivel: int
    codigo: str
    nombre: str
    ambientes: int
    circuitos: int
    estado: Literal["listo", "sin_plano", "incompleto"]


class EdificacionResumen(Esquema):
    id: str
    nombre: str
    propietario: str
    pisos: int
    actualizado: str


class EdificacionDetalle(Esquema):
    id: str
    creado: str
    actualizado: str
    datos: DatosEdificacion
    pisos: list[PisoOut]


class SubtableroOut(Esquema):
    proyecto_id: str
    piso: str
    tablero: str
    longitud_m: float
    vertical_m: float
    horizontal_m: float
    demanda_kw: float
    breaker_a: float
    conductor: str
    caida_pct: float


class CalculoEdificacion(Esquema):
    estado: Literal["listo", "incompleto"]
    aviso: str
    pendientes: list[str] = []
    area_m2: float = 0
    demanda_kw: float = 0
    clasificacion: str = ""
    principal_a: float = 0
    alimentador: str = ""
    caida_pct: float = 0
    medidor: str = ""
    piso_principal: str = ""
    demanda_principal_kw: float = 0
    subtableros: list[SubtableroOut] = []
    avisos: list[str] = []


# --- Utilidades --------------------------------------------------------------------


def _buscar(sesion: Session, id: str) -> EdificacionBD:
    fila = sesion.get(EdificacionBD, id)
    if fila is None:
        raise Problema(404, "edificacion_no_encontrada", "La vivienda de varios pisos no existe")
    return fila


def _pisos(sesion: Session, id: str) -> list[PisoBD]:
    return list(
        sesion.scalars(
            select(PisoBD).where(PisoBD.edificacion_id == id).order_by(PisoBD.nivel)
        ).all()
    )


def _piso_out(sesion: Session, piso: PisoBD) -> PisoOut:
    proyecto = sesion.get(ProyectoBD, piso.proyecto_id)
    assert proyecto is not None
    datos = Borrador.model_validate_json(proyecto.datos)
    estado: Literal["listo", "sin_plano", "incompleto"] = "listo"
    if datos.plano is None:
        estado = "sin_plano"
    elif not datos.circuitos:
        estado = "incompleto"
    return PisoOut(
        proyecto_id=piso.proyecto_id,
        nivel=piso.nivel,
        codigo=codigo_piso(piso.nivel),
        nombre=piso.nombre,
        ambientes=len(datos.plano.ambientes) if datos.plano else 0,
        circuitos=len(datos.circuitos),
        estado=estado,
    )


def _detalle(sesion: Session, fila: EdificacionBD) -> EdificacionDetalle:
    return EdificacionDetalle(
        id=fila.id,
        creado=fila.creado,
        actualizado=fila.actualizado,
        datos=DatosEdificacion.model_validate_json(fila.datos),
        pisos=[_piso_out(sesion, p) for p in _pisos(sesion, fila.id)],
    )


def _perfil(perfiles: Perfiles, ref: RefPerfil) -> Perfil:
    perfil = perfiles.buscar(ref.id, ref.version)
    if perfil is None:
        raise Problema(422, "perfil_no_disponible", "El perfil indicado no está disponible", ref.id)
    return perfil


def _calcular(
    sesion: Session, fila: EdificacionBD, perfiles: Perfiles
) -> tuple[Edificacion, dict[str, str]] | list[str]:
    """La edificación calculada y el proyecto de cada nivel, o lo que falta."""
    datos = DatosEdificacion.model_validate_json(fila.datos)
    perfil = _perfil(perfiles, datos.perfil)
    pendientes: list[str] = []
    pisos: list[Piso] = []
    proyectos: dict[str, str] = {}
    filas = _pisos(sesion, fila.id)
    if len(filas) < 2:
        pendientes.append("Cargue el plano de al menos dos plantas.")
    for piso in filas:
        proyecto_bd = sesion.get(ProyectoBD, piso.proyecto_id)
        assert proyecto_bd is not None
        borrador = Borrador.model_validate_json(proyecto_bd.datos)
        proyecto = proyecto_del_borrador(piso.proyecto_id, borrador)
        if isinstance(proyecto, list):
            pendientes.append(f"{piso.nombre}: " + "; ".join(p.mensaje for p in proyecto))
            continue
        pisos.append(Piso(piso.nombre, piso.nivel, proyecto))
        proyectos[piso.nombre] = piso.proyecto_id
    if pendientes:
        return pendientes
    try:
        return (
            calcular_pisos(
                datos.nombre,
                pisos,
                perfil,
                medidor_m=datos.medidor_m,
                altura_piso_m=datos.altura_piso_m,
            ),
            proyectos,
        )
    except ErrorElectric as error:
        return [str(error)]


def _f(valor: Decimal) -> float:
    return float(round(valor, 3))


def _crear_piso(
    sesion: Session,
    edificacion: EdificacionBD,
    perfil: Perfil,
    contenido: bytes,
    archivo: str,
    nombre: str,
    nivel: int,
    equipos: tuple[str, ...],
    escala: float | None,
) -> PisoBD:
    from electric_api.app import _anotar  # evita la importación circular

    datos = DatosEdificacion.model_validate_json(edificacion.datos)
    if any(p.nivel == nivel for p in _pisos(sesion, edificacion.id)):
        raise Problema(409, "nivel_ocupado", "Ya hay una planta en ese nivel", f"Nivel {nivel}")
    preferencias = datos.preferencias
    if nivel > 0:
        preferencias = preferencias.model_copy(update={"exteriores": False})
    id = str(uuid.uuid4())
    try:
        resultado = proyecto_desde_plano(
            contenido,
            archivo,
            perfil,
            id=id,
            nombre=f"{datos.nombre} · {nombre}",
            equipos=equipos,
            alimentador_m=datos.medidor_m,
            factor_a_metros=escala,
            preferencias=preferencias,
        )
    except ErrorElectric as error:
        raise Problema(422, error.codigo, "No se pudo interpretar el plano", str(error)) from error
    borrador = Borrador.model_validate(resultado.proyecto.model_dump(exclude={"id"}))
    borrador = borrador.model_copy(
        update={"predio": borrador.predio.model_copy(update={"propietario": datos.propietario})}
    )
    momento = ahora()
    proyecto = ProyectoBD(
        id=id,
        nombre=borrador.nombre,
        revision=1,
        datos=a_json_canonico(borrador),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(proyecto)
    sesion.flush()
    assert resultado.proyecto.plano is not None
    sesion.add(
        ArchivoBD(
            proyecto_id=id,
            nombre=archivo,
            sha256=resultado.proyecto.plano.sha256,
            contenido=contenido,
        )
    )
    _anotar(sesion, proyecto, "crear", borrador, resumen=f"Planta {nombre} de {datos.nombre}")
    piso = PisoBD(proyecto_id=id, edificacion_id=edificacion.id, nivel=nivel, nombre=nombre)
    sesion.add(piso)
    edificacion.actualizado = momento
    return piso


# --- Rutas -------------------------------------------------------------------------


@rutas.get("/edificaciones")
def listar_edificaciones(sesion: SesionDep) -> list[EdificacionResumen]:
    filas = sesion.scalars(select(EdificacionBD).order_by(EdificacionBD.actualizado.desc()))
    return [
        EdificacionResumen(
            id=f.id,
            nombre=f.nombre,
            propietario=DatosEdificacion.model_validate_json(f.datos).propietario,
            pisos=len(_pisos(sesion, f.id)),
            actualizado=f.actualizado,
        )
        for f in filas.all()
    ]


@rutas.post("/edificaciones", status_code=201)
def crear_edificacion(
    datos: DatosEdificacion, sesion: SesionDep, perfiles: PerfilesDep
) -> EdificacionDetalle:
    _perfil(perfiles, datos.perfil)
    momento = ahora()
    fila = EdificacionBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        datos=datos.model_dump_json(),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    sesion.commit()
    return _detalle(sesion, fila)


@rutas.get("/edificaciones/{id}")
def leer_edificacion(id: str, sesion: SesionDep) -> EdificacionDetalle:
    return _detalle(sesion, _buscar(sesion, id))


@rutas.put("/edificaciones/{id}")
def guardar_edificacion(
    id: str, datos: DatosEdificacion, sesion: SesionDep, perfiles: PerfilesDep
) -> EdificacionDetalle:
    fila = _buscar(sesion, id)
    _perfil(perfiles, datos.perfil)
    fila.nombre = datos.nombre
    fila.datos = datos.model_dump_json()
    fila.actualizado = ahora()
    sesion.commit()
    return _detalle(sesion, fila)


@rutas.delete("/edificaciones/{id}", status_code=204)
def borrar_edificacion(id: str, sesion: SesionDep) -> Response:
    """Borra la vivienda y los proyectos de sus plantas."""
    from electric_api.app import borrar_proyecto

    fila = _buscar(sesion, id)
    for piso in _pisos(sesion, id):
        borrar_proyecto(piso.proyecto_id, sesion)
    sesion.delete(fila)
    sesion.commit()
    return Response(status_code=204)


@rutas.post("/edificaciones/{id}/pisos", status_code=201)
def subir_piso(
    id: str,
    sesion: SesionDep,
    perfiles: PerfilesDep,
    contenido: Annotated[bytes, Body(media_type="application/octet-stream")],
    nivel: Annotated[int, Query(ge=-5, le=40)],
    nombre: Annotated[str, Query(min_length=1, max_length=80)],
    archivo: Annotated[str, Query(max_length=200)] = "plano.dxf",
    equipos: Annotated[str, Query(max_length=300)] = "",
    escala: Annotated[float | None, Query(gt=0)] = None,
) -> EdificacionDetalle:
    """Agrega una planta con su plano: se lee, se diseña y queda como proyecto propio."""
    fila = _buscar(sesion, id)
    perfil = _perfil(perfiles, DatosEdificacion.model_validate_json(fila.datos).perfil)
    tipos = tuple(t.strip() for t in equipos.split(",") if t.strip())
    _crear_piso(sesion, fila, perfil, contenido, archivo, nombre, nivel, tipos, escala)
    sesion.commit()
    return _detalle(sesion, fila)


@rutas.get("/edificaciones/{id}/calculo")
def calcular_edificacion(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> CalculoEdificacion:
    fila = _buscar(sesion, id)
    resultado = _calcular(sesion, fila, perfiles)
    if isinstance(resultado, list):
        return CalculoEdificacion(estado="incompleto", aviso=AVISO_BORRADOR, pendientes=resultado)
    e, proyectos = resultado
    calc = e.calculado
    return CalculoEdificacion(
        estado="listo",
        aviso=AVISO_BORRADOR,
        area_m2=_f(e.area_m2),
        demanda_kw=_f(calc.res("RC-03", PROYECTO).decimal / 1000),
        clasificacion=str(calc.res("RC-05", PROYECTO).valor),
        principal_a=_f(calc.res("RC-09", ALIMENTADOR).decimal),
        alimentador=str(calc.res("RC-07", ALIMENTADOR).valor),
        caida_pct=_f(calc.res("RC-08", ALIMENTADOR).decimal),
        medidor=str(calc.res("RC-12", PROYECTO).valor),
        piso_principal=e.principal.nombre,
        demanda_principal_kw=_f(e.calculado_principal.res("RC-03", PROYECTO).decimal / 1000),
        subtableros=[
            SubtableroOut(
                proyecto_id=proyectos[s.piso.nombre],
                piso=s.piso.nombre,
                tablero=s.tablero,
                longitud_m=_f(s.longitud_m),
                vertical_m=_f(s.vertical_m),
                horizontal_m=_f(s.horizontal_m),
                demanda_kw=_f(s.demanda_w / 1000),
                breaker_a=_f(s.breaker_a),
                conductor=s.conductor,
                caida_pct=_f(s.caida_pct),
            )
            for s in e.subtableros
        ],
        avisos=list(e.avisos),
    )


TIPOS = {"dxf": "application/dxf", "png": "image/png", "pdf": "application/pdf"}


@rutas.get(
    "/edificaciones/{id}/unifilar.{formato}",
    response_class=Response,
    responses={200: {"content": {t: {} for t in TIPOS.values()}}},
)
def unifilar_edificacion(
    id: str, formato: Literal["dxf", "png", "pdf"], sesion: SesionDep, perfiles: PerfilesDep
) -> Response:
    resultado = _calcular(sesion, _buscar(sesion, id), perfiles)
    if isinstance(resultado, list):
        raise Problema(
            422, "edificacion_incompleta", "Todavía no se puede dibujar", " ".join(resultado)
        )
    dxf = generar_unifilar_pisos(resultado[0])
    contenido = dxf if formato == "dxf" else renderizar(dxf, formato)
    disposicion = "attachment" if formato == "dxf" else "inline"
    return Response(
        contenido,
        media_type=TIPOS[formato],
        headers={"Content-Disposition": f'{disposicion}; filename="unifilar.{formato}"'},
    )


@rutas.post("/ejemplos/vivienda-2-pisos", status_code=201)
def crear_ejemplo_pisos(
    request: Request, sesion: SesionDep, perfiles: PerfilesDep
) -> EdificacionDetalle:
    """Crea la vivienda de dos plantas del repositorio, con cada planta diseñada."""
    config: Config = request.app.state.config
    carpeta = config.ejemplos / "vivienda-2-pisos"
    perfil = next((p for p in perfiles.todos() if p.meta.id == "cnel-ep"), None)
    plantas = [
        ("planta-baja.dxf", "Planta baja", 0, ("cocina", "ducha")),
        ("planta-alta.dxf", "Planta alta", 1, ("ducha",)),
    ]
    if perfil is None or not all((carpeta / a).is_file() for a, *_ in plantas):
        raise Problema(
            404, "ejemplo_no_disponible", "El ejemplo no está disponible en este servidor"
        )
    datos = DatosEdificacion(
        nombre="Vivienda de dos plantas",
        perfil=RefPerfil(id=perfil.meta.id, version=perfil.meta.version),
        preferencias=Preferencias(zona_climatica="costa"),
    )
    momento = ahora()
    fila = EdificacionBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        datos=datos.model_dump_json(),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    sesion.flush()
    for archivo, nombre, nivel, equipos in plantas:
        contenido = (carpeta / archivo).read_bytes()
        _crear_piso(sesion, fila, perfil, contenido, archivo, nombre, nivel, equipos, None)
    sesion.commit()
    return _detalle(sesion, fila)


def piso_de(sesion: Session, proyecto_id: str) -> tuple[str, str, str] | None:
    """Edificación a la que pertenece un proyecto: id, nombre de la vivienda y de la planta."""
    piso = sesion.get(PisoBD, proyecto_id)
    if piso is None:
        return None
    edificacion = sesion.get(EdificacionBD, piso.edificacion_id)
    assert edificacion is not None
    return edificacion.id, edificacion.nombre, piso.nombre


__all__ = ["ProyectoDetalle", "piso_de", "rutas"]
