"""Aplicación FastAPI."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated

from electric.calculo import calcular
from electric.diseno import disenar
from electric.errores import ErrorElectric
from electric.flujo import proyecto_desde_plano
from electric.ingesta import leer_dxf
from electric.interpretacion import interpretar
from electric.modelo import Proyecto, a_json_canonico, hash_canonico
from electric.perfiles import Perfil
from electric.salida_cad import generar_dxf, renderizar
from fastapi import APIRouter, Body, Depends, FastAPI, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from electric_api import problemas
from electric_api.config import Config, leer_config
from electric_api.db import ArchivoBD, BitacoraBD, ProyectoBD, ahora, crear_motor, crear_sesiones
from electric_api.esquemas import (
    Borrador,
    Calculos,
    DisenoOut,
    EntradaBitacora,
    Fondo,
    Guardar,
    PerfilOut,
    ProyectoDetalle,
    ProyectoResumen,
    Revision,
)
from electric_api.problemas import Problema
from electric_api.servicio import (
    Perfiles,
    calcular_borrador,
    fondo_del_plano,
    perfil_a_salida,
    proyecto_del_borrador,
)

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
    archivo = sesion.get(ArchivoBD, id)
    if archivo is not None:
        sesion.delete(archivo)
    sesion.flush()
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


# --- Plano, diseño automático y salida CAD ---------------------------------


def _perfil_de(datos: Borrador, perfiles: Perfiles) -> Perfil:
    perfil = perfiles.buscar(datos.perfil.id, datos.perfil.version)
    if perfil is None:
        raise Problema(422, "perfil_no_disponible", "El perfil del proyecto no está disponible")
    return perfil


def _exigir_revision(fila: ProyectoBD, revision: int) -> None:
    if revision != fila.revision:
        raise Problema(
            409,
            "revision_desactualizada",
            "El proyecto cambió desde que lo abrió",
            f"Usted tenía la revisión {revision} y la actual es {fila.revision}. Recargue.",
        )


def _actualizar(sesion: Session, fila: ProyectoBD, datos: Borrador, accion: str) -> ProyectoDetalle:
    fila.nombre = datos.nombre
    fila.datos = a_json_canonico(datos)
    fila.revision += 1
    fila.actualizado = ahora()
    _anotar(sesion, fila, accion, datos)
    sesion.commit()
    return _detalle(fila)


def _archivo(sesion: Session, id: str) -> ArchivoBD:
    archivo = sesion.get(ArchivoBD, id)
    if archivo is None:
        raise Problema(404, "sin_plano", "El proyecto no tiene un plano cargado")
    return archivo


@rutas.post("/proyectos/{id}/plano")
def subir_plano(
    id: str,
    sesion: SesionDep,
    perfiles: PerfilesDep,
    contenido: Annotated[bytes, Body(media_type="application/octet-stream")],
    revision: Annotated[int, Query()],
    nombre: Annotated[str, Query(max_length=200)] = "plano.dxf",
    escala: Annotated[float | None, Query(gt=0, description="Metros por unidad de dibujo")] = None,
) -> ProyectoDetalle:
    """Carga el plano del arquitecto y detecta sus ambientes.

    Reemplaza el plano anterior y descarta el diseño que dependía de él.
    """
    fila = _buscar(sesion, id)
    _exigir_revision(fila, revision)
    datos = Borrador.model_validate_json(fila.datos)
    perfil = _perfil_de(datos, perfiles)
    try:
        plano = interpretar(leer_dxf(contenido, nombre, factor_a_metros=escala), perfil)
    except ErrorElectric as error:
        raise Problema(422, error.codigo, "No se pudo interpretar el plano", str(error)) from error

    anterior = sesion.get(ArchivoBD, id)
    if anterior is not None:
        sesion.delete(anterior)
        sesion.flush()
    sesion.add(ArchivoBD(proyecto_id=id, nombre=nombre, sha256=plano.sha256, contenido=contenido))
    datos = datos.model_copy(
        update={"plano": plano, "area_construida_m2": plano.area_construida_m2}
    )
    return _actualizar(sesion, fila, datos, "cargar plano")


@rutas.get("/proyectos/{id}/plano/fondo")
def leer_fondo(id: str, sesion: SesionDep) -> Fondo:
    fila = _buscar(sesion, id)
    archivo = _archivo(sesion, id)
    datos = Borrador.model_validate_json(fila.datos)
    factor = float(datos.plano.factor_a_metros) if datos.plano else 1.0
    return fondo_del_plano(archivo.contenido, archivo.nombre, factor)


@rutas.post("/proyectos/{id}/diseno")
def disenar_instalacion(
    id: str, cuerpo: Revision, sesion: SesionDep, perfiles: PerfilesDep
) -> DisenoOut:
    """Diseña la instalación sobre los ambientes del plano.

    Reemplaza puntos y circuitos; conserva las cargas especiales declaradas.
    """
    fila = _buscar(sesion, id)
    _exigir_revision(fila, cuerpo.revision)
    datos = Borrador.model_validate_json(fila.datos)
    if datos.plano is None:
        raise Problema(409, "sin_plano", "Cargue un plano antes de diseñar")
    perfil = _perfil_de(datos, perfiles)
    limpio = datos.plano.model_copy(
        update={"ubicaciones": (), "interruptores": (), "recorridos": ()}
    )
    try:
        diseno = disenar(limpio, tuple(datos.cargas_especiales), perfil)
    except ErrorElectric as error:
        raise Problema(
            422, error.codigo, "No se pudo diseñar la instalación", str(error)
        ) from error
    datos = datos.model_copy(
        update={
            "puntos": list(diseno.puntos),
            "cargas_especiales": list(diseno.cargas_especiales),
            "circuitos": list(diseno.circuitos),
            "plano": diseno.plano,
        }
    )
    return DisenoOut(
        proyecto=_actualizar(sesion, fila, datos, "diseñar"), avisos=list(diseno.avisos)
    )


_TIPOS = {"dxf": "application/dxf", "png": "image/png", "pdf": "application/pdf"}


@rutas.get(
    "/proyectos/{id}/salida.{formato}",
    response_class=Response,
    responses={200: {"content": {tipo: {} for tipo in _TIPOS.values()}}},
)
def descargar_salida(id: str, formato: str, sesion: SesionDep, perfiles: PerfilesDep) -> Response:
    """Plano con la instalación: DXF con capas E-*, o su imagen PNG o PDF."""
    if formato not in _TIPOS:
        raise Problema(404, "formato_desconocido", "Formatos disponibles: dxf, png, pdf")
    fila = _buscar(sesion, id)
    archivo = _archivo(sesion, id)
    datos = Borrador.model_validate_json(fila.datos)
    perfil = _perfil_de(datos, perfiles)
    proyecto = proyecto_del_borrador(id, datos)
    if not isinstance(proyecto, Proyecto):
        faltan = "; ".join(p.mensaje for p in proyecto)
        raise Problema(
            409, "proyecto_incompleto", "Falta información para generar el plano", faltan
        )
    try:
        dxf = generar_dxf(archivo.contenido, proyecto, calcular(proyecto, perfil), perfil)
        salida = dxf if formato == "dxf" else renderizar(dxf, "png" if formato == "png" else "pdf")
    except ErrorElectric as error:
        raise Problema(409, error.codigo, "No se pudo generar el plano", str(error)) from error
    return Response(
        salida,
        media_type=_TIPOS[formato],
        headers={"Content-Disposition": f'attachment; filename="red-{fila.revision}.{formato}"'},
    )


@rutas.post("/ejemplos/vivienda-plano", status_code=201)
def crear_ejemplo_con_plano(
    request: Request, sesion: SesionDep, perfiles: PerfilesDep
) -> ProyectoDetalle:
    """Crea el modelo de prueba: la vivienda del repositorio, ya diseñada sobre su plano."""
    config: Config = request.app.state.config
    ruta = config.ejemplos / "vivienda-plano" / "planta.dxf"
    perfil = next((p for p in perfiles.todos() if p.meta.id == "cnel-ep"), None)
    if perfil is None or not ruta.is_file():
        raise Problema(
            404, "ejemplo_no_disponible", "El ejemplo no está disponible en este servidor"
        )
    contenido = ruta.read_bytes()
    id = str(uuid.uuid4())
    resultado = proyecto_desde_plano(
        contenido,
        ruta.name,
        perfil,
        id=id,
        nombre="Vivienda de prueba con plano",
        equipos=("ducha", "cocina"),
        alimentador_m=Decimal(12),
    )
    datos = Borrador.model_validate(resultado.proyecto.model_dump(exclude={"id"}))
    momento = ahora()
    fila = ProyectoBD(
        id=id,
        nombre=datos.nombre,
        revision=1,
        datos=a_json_canonico(datos),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    sesion.flush()
    assert resultado.proyecto.plano is not None
    sesion.add(
        ArchivoBD(
            proyecto_id=id,
            nombre=ruta.name,
            sha256=resultado.proyecto.plano.sha256,
            contenido=contenido,
        )
    )
    _anotar(sesion, fila, "crear", datos)
    sesion.commit()
    return _detalle(fila)


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
    app.state.config = config
    problemas.registrar(app)
    app.include_router(rutas)
    if config.web.is_dir():
        app.mount("/", StaticFiles(directory=config.web, html=True), name="web")
    return app
