"""Aplicación FastAPI."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from electric.modelo import a_json_canonico, hash_canonico
from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from electric_api import problemas
from electric_api.config import Config, leer_config
from electric_api.db import BitacoraBD, ProyectoBD, ahora, crear_motor, crear_sesiones
from electric_api.esquemas import (
    Borrador,
    Calculos,
    EntradaBitacora,
    Guardar,
    PerfilOut,
    ProyectoDetalle,
    ProyectoResumen,
)
from electric_api.problemas import Problema
from electric_api.servicio import Perfiles, calcular_borrador, perfil_a_salida

#: Sin inicio de sesión todavía: la autenticación y los roles llegan en un incremento posterior.
AUTOR = "sin identificar"

rutas = APIRouter(prefix="/api/v1")


def _sesion(request: Request) -> Iterator[Session]:
    with request.app.state.sesiones() as sesion:
        yield sesion


def _perfiles(request: Request) -> Perfiles:
    perfiles: Perfiles = request.app.state.perfiles
    return perfiles


SesionDep = Annotated[Session, Depends(_sesion)]
PerfilesDep = Annotated[Perfiles, Depends(_perfiles)]


def _buscar(sesion: Session, id: str) -> ProyectoBD:
    proyecto = sesion.get(ProyectoBD, id)
    if proyecto is None:
        raise Problema(404, "proyecto_no_encontrado", "El proyecto no existe")
    return proyecto


def _detalle(fila: ProyectoBD) -> ProyectoDetalle:
    return ProyectoDetalle(
        id=fila.id,
        revision=fila.revision,
        creado=fila.creado,
        actualizado=fila.actualizado,
        datos=Borrador.model_validate_json(fila.datos),
    )


def _resumen_cambio(datos: Borrador) -> str:
    return (
        f"{len(datos.circuitos)} circuitos, {len(datos.puntos)} puntos, "
        f"{len(datos.cargas_especiales)} cargas especiales, {len(datos.supuestos)} supuestos"
    )


def _anotar(sesion: Session, fila: ProyectoBD, accion: str, datos: Borrador) -> None:
    sesion.add(
        BitacoraBD(
            proyecto_id=fila.id,
            revision=fila.revision,
            accion=accion,
            autor=AUTOR,
            fecha=ahora(),
            huella=hash_canonico(datos),
            resumen=_resumen_cambio(datos),
        )
    )


def _exigir_perfil(datos: Borrador, perfiles: Perfiles) -> None:
    if perfiles.buscar(datos.perfil.id, datos.perfil.version) is None:
        raise Problema(
            422,
            "perfil_no_disponible",
            "El perfil indicado no está disponible",
            f"{datos.perfil.id} {datos.perfil.version}",
        )


@rutas.get("/perfiles")
def listar_perfiles(perfiles: PerfilesDep) -> list[PerfilOut]:
    return [perfil_a_salida(p) for p in perfiles.todos()]


@rutas.get("/proyectos")
def listar_proyectos(sesion: SesionDep) -> list[ProyectoResumen]:
    filas = sesion.scalars(select(ProyectoBD).order_by(ProyectoBD.actualizado.desc())).all()
    return [
        ProyectoResumen(
            id=f.id,
            nombre=f.nombre,
            revision=f.revision,
            propietario=Borrador.model_validate_json(f.datos).predio.propietario,
            creado=f.creado,
            actualizado=f.actualizado,
        )
        for f in filas
    ]


@rutas.post("/proyectos", status_code=201)
def crear_proyecto(datos: Borrador, sesion: SesionDep, perfiles: PerfilesDep) -> ProyectoDetalle:
    _exigir_perfil(datos, perfiles)
    momento = ahora()
    fila = ProyectoBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        revision=1,
        datos=a_json_canonico(datos),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    _anotar(sesion, fila, "crear", datos)
    sesion.commit()
    return _detalle(fila)


@rutas.get("/proyectos/{id}")
def leer_proyecto(id: str, sesion: SesionDep) -> ProyectoDetalle:
    return _detalle(_buscar(sesion, id))


@rutas.put("/proyectos/{id}")
def guardar_proyecto(
    id: str, cuerpo: Guardar, sesion: SesionDep, perfiles: PerfilesDep
) -> ProyectoDetalle:
    fila = _buscar(sesion, id)
    if cuerpo.revision != fila.revision:
        raise Problema(
            409,
            "revision_desactualizada",
            "El proyecto cambió desde que lo abrió",
            f"Usted editaba la revisión {cuerpo.revision} y la actual es {fila.revision}. "
            "Recargue el proyecto y repita el cambio.",
        )
    _exigir_perfil(cuerpo.datos, perfiles)
    fila.nombre = cuerpo.datos.nombre
    fila.datos = a_json_canonico(cuerpo.datos)
    fila.revision += 1
    fila.actualizado = ahora()
    _anotar(sesion, fila, "guardar", cuerpo.datos)
    sesion.commit()
    return _detalle(fila)


@rutas.delete("/proyectos/{id}", status_code=204)
def borrar_proyecto(id: str, sesion: SesionDep) -> Response:
    fila = _buscar(sesion, id)
    for entrada in sesion.scalars(select(BitacoraBD).where(BitacoraBD.proyecto_id == id)):
        sesion.delete(entrada)
    sesion.delete(fila)
    sesion.commit()
    return Response(status_code=204)


@rutas.get("/proyectos/{id}/calculos")
def leer_calculos(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> Calculos:
    fila = _buscar(sesion, id)
    return calcular_borrador(
        fila.id, fila.revision, Borrador.model_validate_json(fila.datos), perfiles
    )


@rutas.get("/proyectos/{id}/bitacora")
def leer_bitacora(id: str, sesion: SesionDep) -> list[EntradaBitacora]:
    _buscar(sesion, id)
    filas = sesion.scalars(
        select(BitacoraBD).where(BitacoraBD.proyecto_id == id).order_by(BitacoraBD.id.desc())
    ).all()
    return [
        EntradaBitacora(
            revision=f.revision,
            accion=f.accion,
            autor=f.autor,
            fecha=f.fecha,
            huella=f.huella,
            resumen=f.resumen,
        )
        for f in filas
    ]


def crear_app(config: Config | None = None) -> FastAPI:
    config = config or leer_config()
    app = FastAPI(
        title="Electric",
        version="0.1.0",
        description="API de la plataforma de proyectos eléctricos CNEL EP.",
        separate_input_output_schemas=False,
    )
    app.state.sesiones = crear_sesiones(crear_motor(config.base_de_datos))
    app.state.perfiles = Perfiles(config.perfiles)
    problemas.registrar(app)
    app.include_router(rutas)
    if config.web.is_dir():
        app.mount("/", StaticFiles(directory=config.web, html=True), name="web")
    return app
