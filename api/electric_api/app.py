"""Aplicación FastAPI."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated

from electric.calculo import calcular
from electric.diseno import disenar, editar
from electric.diseno.opciones import NOMBRES, OPCIONES, preferencias_para
from electric.errores import ErrorElectric
from electric.flujo import proyecto_desde_plano
from electric.ingesta import leer_dxf
from electric.interpretacion import interpretar
from electric.modelo import CargaEspecial, Proyecto, a_json_canonico, hash_canonico
from electric.perfiles import Perfil
from electric.salida_cad import generar_dxf, renderizar
from fastapi import APIRouter, Body, Depends, FastAPI, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from electric_api import (
    edificios,
    industrial,
    pisos,
    problemas,
    redes_mt,
    subestaciones,
    urbanizaciones,
)
from electric_api.config import Config, leer_config
from electric_api.db import (
    ArchivoBD,
    BitacoraBD,
    EscenarioBD,
    PisoBD,
    ProyectoBD,
    VersionBD,
    ahora,
    crear_motor,
    crear_sesiones,
)
from electric_api.esquemas import (
    Asistente,
    Borrador,
    Calculos,
    DisenoOut,
    Editar,
    EntradaBitacora,
    EscenarioOut,
    Fondo,
    Guardar,
    NuevoEscenario,
    PerfilOut,
    PlantaRef,
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


def _version(sesion: Session, id: str, revision: int) -> VersionBD | None:
    return sesion.scalars(
        select(VersionBD).where(VersionBD.proyecto_id == id, VersionBD.revision == revision)
    ).first()


def _a_deshacer(sesion: Session, fila: ProyectoBD) -> tuple[VersionBD, BitacoraBD] | None:
    """Versión a la que volvería «Deshacer» y el cambio que se deshace."""
    actual = _version(sesion, fila.id, fila.revision)
    if actual is None or actual.base <= 1:
        return None
    destino = _version(sesion, fila.id, actual.base - 1)
    cambio = sesion.scalars(
        select(BitacoraBD).where(
            BitacoraBD.proyecto_id == fila.id, BitacoraBD.revision == actual.base
        )
    ).first()
    if destino is None or cambio is None:
        return None
    return destino, cambio


def _escenario(sesion: Session, id: str) -> EscenarioBD | None:
    return sesion.get(EscenarioBD, id)


def _detalle(fila: ProyectoBD) -> ProyectoDetalle:
    sesion = object_session(fila)
    previo = _a_deshacer(sesion, fila) if sesion is not None else None
    escenario = _escenario(sesion, fila.id) if sesion is not None else None
    planta = pisos.piso_de(sesion, fila.id) if sesion is not None else None
    return ProyectoDetalle(
        id=fila.id,
        revision=fila.revision,
        creado=fila.creado,
        actualizado=fila.actualizado,
        datos=Borrador.model_validate_json(fila.datos),
        deshacer=previo[1].accion if previo else None,
        escenario=escenario.nombre if escenario else None,
        planta=(
            PlantaRef(edificacion_id=planta[0], edificacion=planta[1], piso=planta[2])
            if planta
            else None
        ),
    )


def _resumen_cambio(datos: Borrador) -> str:
    return (
        f"{len(datos.circuitos)} circuitos, {len(datos.puntos)} puntos, "
        f"{len(datos.cargas_especiales)} cargas especiales, {len(datos.supuestos)} supuestos"
    )


def _anotar(
    sesion: Session,
    fila: ProyectoBD,
    accion: str,
    datos: Borrador,
    *,
    base: int | None = None,
    resumen: str | None = None,
) -> None:
    sesion.add(
        VersionBD(
            proyecto_id=fila.id,
            revision=fila.revision,
            base=fila.revision if base is None else base,
            datos=fila.datos,
        )
    )
    sesion.add(
        BitacoraBD(
            proyecto_id=fila.id,
            revision=fila.revision,
            accion=accion,
            autor=AUTOR,
            fecha=ahora(),
            huella=hash_canonico(datos),
            resumen=resumen or _resumen_cambio(datos),
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
            edificacion_id=planta[0] if (planta := pisos.piso_de(sesion, f.id)) else None,
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
    return _actualizar(sesion, fila, cuerpo.datos, "guardar")


@rutas.delete("/proyectos/{id}", status_code=204)
def borrar_proyecto(id: str, sesion: SesionDep) -> Response:
    fila = _buscar(sesion, id)
    for entrada in sesion.scalars(select(BitacoraBD).where(BitacoraBD.proyecto_id == id)):
        sesion.delete(entrada)
    for version in sesion.scalars(select(VersionBD).where(VersionBD.proyecto_id == id)):
        sesion.delete(version)
    escenario = sesion.get(EscenarioBD, id)
    if escenario is not None:
        sesion.delete(escenario)
    piso = sesion.get(PisoBD, id)
    if piso is not None:
        sesion.delete(piso)
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


def _actualizar(
    sesion: Session,
    fila: ProyectoBD,
    datos: Borrador,
    accion: str,
    *,
    base: int | None = None,
    resumen: str | None = None,
) -> ProyectoDetalle:
    fila.nombre = datos.nombre
    fila.datos = a_json_canonico(datos)
    fila.revision += 1
    fila.actualizado = ahora()
    _anotar(sesion, fila, accion, datos, base=base, resumen=resumen)
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
    # Lo que el usuario fijó en el plano se conserva; el resto se vuelve a colocar.
    limpio = datos.plano.model_copy(
        update={
            "ubicaciones": tuple(u for u in datos.plano.ubicaciones if u.fijo),
            "interruptores": tuple(s for s in datos.plano.interruptores if s.fijo),
            "recorridos": (),
        }
    )
    try:
        diseno = disenar(limpio, tuple(datos.cargas_especiales), perfil, datos.preferencias)
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


def _describir(cuerpo: Editar) -> str:
    textos = {
        "mover": "movió",
        "liberar": "liberó",
        "circuito": "cambió de circuito",
        "agregar": "agregó",
        "quitar": "quitó",
    }
    partes = []
    for e in cuerpo.ediciones:
        sujeto = getattr(e, "id", None) or getattr(e, "tipo", "")
        destino = f" a {e.circuito}" if e.op == "circuito" else ""
        partes.append(f"{textos[e.op]} {sujeto}{destino}")
    return "; ".join(partes)


@rutas.post("/proyectos/{id}/ediciones")
def editar_instalacion(
    id: str, cuerpo: Editar, sesion: SesionDep, perfiles: PerfilesDep
) -> DisenoOut:
    """Mueve, fija, agrega o quita elementos en el plano y vuelve a trazar los recorridos.

    Las ediciones se aplican en orden y todas o ninguna. Lo movido o agregado
    queda fijado: «Volver a diseñar» no lo mueve.
    """
    fila = _buscar(sesion, id)
    _exigir_revision(fila, cuerpo.revision)
    datos = Borrador.model_validate_json(fila.datos)
    perfil = _perfil_de(datos, perfiles)
    proyecto = proyecto_del_borrador(id, datos)
    if not isinstance(proyecto, Proyecto):
        faltan = "; ".join(p.mensaje for p in proyecto)
        raise Problema(409, "proyecto_incompleto", "Complete el proyecto antes de editar", faltan)
    try:
        editado = editar(proyecto, cuerpo.ediciones, perfil)
    except ErrorElectric as error:
        raise Problema(422, error.codigo, "No se pudo aplicar el cambio", str(error)) from error
    nuevos = Borrador.model_validate(editado.proyecto.model_dump(exclude={"id"}))
    return DisenoOut(
        proyecto=_actualizar(
            sesion, fila, nuevos, "editar en el plano", resumen=_describir(cuerpo)
        ),
        avisos=list(editado.avisos),
    )


@rutas.post("/proyectos/{id}/deshacer")
def deshacer(id: str, cuerpo: Revision, sesion: SesionDep) -> ProyectoDetalle:
    """Vuelve al estado anterior al último cambio. Repetirlo retrocede un paso más."""
    fila = _buscar(sesion, id)
    _exigir_revision(fila, cuerpo.revision)
    previo = _a_deshacer(sesion, fila)
    if previo is None:
        raise Problema(409, "nada_que_deshacer", "No hay un cambio anterior al que volver")
    destino, cambio = previo
    datos = Borrador.model_validate_json(destino.datos)
    archivo = sesion.get(ArchivoBD, id)
    if datos.plano is not None and (archivo is None or archivo.sha256 != datos.plano.sha256):
        raise Problema(
            409,
            "plano_reemplazado",
            "No se puede deshacer más allá del cambio de plano",
            "Para volver al plano anterior, cárguelo de nuevo.",
        )
    return _actualizar(
        sesion,
        fila,
        datos,
        "deshacer",
        base=destino.base,
        resumen=f"deshizo «{cambio.accion}» (revisión {cambio.revision}): {cambio.resumen}",
    )


# --- Escenarios ---------------------------------------------------------------


def _resumen_escenario(fila: ProyectoBD, nombre: str, perfiles: Perfiles) -> EscenarioOut:
    datos = Borrador.model_validate_json(fila.datos)
    calculos = calcular_borrador(fila.id, fila.revision, datos, perfiles)
    return EscenarioOut(
        id=fila.id,
        nombre=nombre,
        revision=fila.revision,
        estado=calculos.estado,
        iluminacion=datos.preferencias.iluminacion,
        zona_climatica=datos.preferencias.zona_climatica,
        luminarias=sum(1 for p in datos.puntos if p.tipo == "punto_luz"),
        tomacorrientes=sum(1 for p in datos.puntos if p.tipo == "tomacorriente"),
        aires=sum(1 for c in datos.cargas_especiales if c.tipo == "aire_acondicionado"),
        circuitos=len(datos.circuitos),
        resumen=calculos.resumen,
    )


@rutas.get("/proyectos/{id}/escenarios")
def listar_escenarios(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> list[EscenarioOut]:
    """Escenarios del mismo proyecto, con sus resultados para compararlos."""
    fila = _buscar(sesion, id)
    propio = _escenario(sesion, id)
    if propio is None:
        return [_resumen_escenario(fila, "Base", perfiles)]
    hermanos = sesion.scalars(select(EscenarioBD).where(EscenarioBD.grupo == propio.grupo)).all()
    salida = []
    for escenario in hermanos:
        otro = sesion.get(ProyectoBD, escenario.proyecto_id)
        if otro is not None:
            salida.append(_resumen_escenario(otro, escenario.nombre, perfiles))
    return sorted(salida, key=lambda e: (e.nombre != "Base", e.nombre))


def _grupo(sesion: Session, id: str, nombre_si_falta: str) -> EscenarioBD:
    propio = _escenario(sesion, id)
    if propio is None:
        propio = EscenarioBD(proyecto_id=id, grupo=id, nombre=nombre_si_falta)
        sesion.add(propio)
        sesion.flush()
    return propio


def _nombres(sesion: Session, grupo: str) -> set[str]:
    return {e.nombre for e in sesion.scalars(select(EscenarioBD).where(EscenarioBD.grupo == grupo))}


def _copiar(
    sesion: Session, fila: ProyectoBD, datos: Borrador, grupo: str, nombre: str, resumen: str
) -> ProyectoBD:
    """Crea un proyecto hermano con `datos` y el mismo plano, como escenario del grupo."""
    base = datos.nombre.split(" — ")[0]
    datos = datos.model_copy(update={"nombre": f"{base} — {nombre}"[:200]})
    momento = ahora()
    nueva = ProyectoBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        revision=1,
        datos=a_json_canonico(datos),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(nueva)
    sesion.flush()
    archivo = sesion.get(ArchivoBD, fila.id)
    if archivo is not None:
        sesion.add(
            ArchivoBD(
                proyecto_id=nueva.id,
                nombre=archivo.nombre,
                sha256=archivo.sha256,
                contenido=archivo.contenido,
            )
        )
    sesion.add(EscenarioBD(proyecto_id=nueva.id, grupo=grupo, nombre=nombre))
    _anotar(sesion, nueva, "crear escenario", datos, resumen=resumen)
    return nueva


@rutas.post("/proyectos/{id}/escenarios", status_code=201)
def crear_escenario(id: str, cuerpo: NuevoEscenario, sesion: SesionDep) -> ProyectoDetalle:
    """Copia el proyecto, con su plano, como un escenario nuevo para probar otros criterios."""
    fila = _buscar(sesion, id)
    propio = _grupo(sesion, id, "Base")
    if cuerpo.nombre in _nombres(sesion, propio.grupo):
        raise Problema(409, "escenario_repetido", "Ya hay un escenario con ese nombre")
    nueva = _copiar(
        sesion,
        fila,
        Borrador.model_validate_json(fila.datos),
        propio.grupo,
        cuerpo.nombre,
        f"copia de {fila.nombre} (rev. {fila.revision})",
    )
    sesion.commit()
    return _detalle(nueva)


@rutas.post("/proyectos/{id}/opciones")
def generar_opciones(
    id: str, cuerpo: Asistente, sesion: SesionDep, perfiles: PerfilesDep
) -> list[EscenarioOut]:
    """Diseña las opciones Básica, Recomendada y Confort a partir del asistente.

    La Recomendada queda en este proyecto; Básica y Confort se crean como
    escenarios hermanos con el mismo plano. Las tres llevan los equipos que
    declaró el usuario y se devuelven listas para comparar.
    """
    fila = _buscar(sesion, id)
    _exigir_revision(fila, cuerpo.revision)
    datos = Borrador.model_validate_json(fila.datos)
    if datos.plano is None:
        raise Problema(409, "sin_plano", "Cargue el plano antes de generar las opciones")
    perfil = _perfil_de(datos, perfiles)
    r = cuerpo.respuestas
    equipos = tuple(
        CargaEspecial(id=f"declarada-{n}", tipo=t, circuito="-")
        for n, t in enumerate(r.equipos, start=1)
    )
    limpio = datos.plano.model_copy(
        update={"ubicaciones": (), "interruptores": (), "recorridos": ()}
    )
    disenados: dict[str, Borrador] = {}
    avisos: dict[str, tuple[str, ...]] = {}
    try:
        for opcion in OPCIONES:
            preferencias = preferencias_para(opcion, r, limpio, perfil)
            diseno = disenar(limpio, equipos, perfil, preferencias)
            avisos[opcion] = diseno.avisos
            disenados[opcion] = datos.model_copy(
                update={
                    "puntos": list(diseno.puntos),
                    "cargas_especiales": list(diseno.cargas_especiales),
                    "circuitos": list(diseno.circuitos),
                    "plano": diseno.plano,
                    "preferencias": preferencias,
                }
            )
    except ErrorElectric as error:
        raise Problema(
            422, error.codigo, "No se pudieron generar las opciones", str(error)
        ) from error

    propio = _grupo(sesion, id, NOMBRES["recomendada"])
    tomados = _nombres(sesion, propio.grupo) - {propio.nombre}
    propio.nombre = _libre(NOMBRES["recomendada"], tomados)
    _actualizar(
        sesion,
        fila,
        disenados["recomendada"],
        "asistente",
        resumen="opción Recomendada con las respuestas del asistente",
    )
    for opcion in ("basica", "confort"):
        nombre = _libre(NOMBRES[opcion], _nombres(sesion, propio.grupo))
        _copiar(
            sesion,
            fila,
            disenados[opcion],
            propio.grupo,
            nombre,
            f"opción {NOMBRES[opcion]} del asistente sobre {fila.nombre}",
        )
    sesion.commit()
    return listar_escenarios(id, sesion, perfiles)


def _libre(nombre: str, tomados: set[str]) -> str:
    if nombre not in tomados:
        return nombre
    n = 2
    while f"{nombre} {n}" in tomados:
        n += 1
    return f"{nombre} {n}"


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
    app.include_router(industrial.rutas)
    app.include_router(pisos.rutas)
    app.include_router(redes_mt.rutas)
    app.include_router(edificios.rutas)
    app.include_router(urbanizaciones.rutas)
    app.include_router(subestaciones.rutas)
    if config.web.is_dir():
        app.mount("/", StaticFiles(directory=config.web, html=True), name="web")
    return app
