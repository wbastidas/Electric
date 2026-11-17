"""Rutas de proyectos industriales: cuadro de cargas, transformador y factibilidad."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Literal

from electric.cli import AVISO_BORRADOR
from electric.errores import ErrorElectric
from electric.industrial import (
    AnalisisIndustrial,
    Coordenadas,
    Industria,
    Maquina,
    TransformadorExistente,
    analizar,
    leer_cuadro,
    plantilla,
)
from electric.industrial.coordinacion import Coordinacion, coordinar, grafico
from electric.industrial.estudios import Estudios, estudiar
from electric.industrial.unifilar import generar_unifilar
from electric.perfiles import Perfil
from electric.perfiles.esquema import Estado, TablaSistemas, peor_estado
from electric.salida_cad import renderizar
from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from electric_api.db import IndustriaBD, ahora
from electric_api.esquemas import Esquema, ResultadoOut
from electric_api.problemas import Problema
from electric_api.servicio import Perfiles, resultado_a_salida

rutas = APIRouter(prefix="/api/v1", tags=["industrial"])


def _sesion(request: Request) -> Iterator[Session]:
    with request.app.state.sesiones() as sesion:
        yield sesion


def _perfiles(request: Request) -> Perfiles:
    perfiles: Perfiles = request.app.state.perfiles
    return perfiles


SesionDep = Annotated[Session, Depends(_sesion)]
PerfilesDep = Annotated[Perfiles, Depends(_perfiles)]


# --- Esquemas ------------------------------------------------------------------


class BorradorIndustria(Esquema):
    """Industria en edición; puede no tener máquinas todavía."""

    nombre: str = Field(min_length=1, max_length=200)
    perfil: str = "cnel-ep"
    propietario: str = Field(default="", max_length=200)
    direccion: str = Field(default="", max_length=300)
    sistema: str = "trifasico_127_220"
    fp_objetivo: Decimal | None = Field(default=None, gt=0, le=1)
    ubicacion: Coordenadas | None = None
    existente: TransformadorExistente | None = None
    maquinas: list[Maquina] = Field(default=[], max_length=2000)
    #: Metros del tablero principal a cada tablero de distribución.
    distancias_m: dict[str, Decimal] = {}
    #: Potencia de cortocircuito de la red de CNEL; si falta, la del perfil.
    scc_red_mva: Decimal | None = Field(default=None, gt=0)
    #: Nombre del último cuadro de cargas cargado.
    cuadro: str | None = None


class GuardarIndustria(Esquema):
    revision: int
    datos: BorradorIndustria


class IndustriaResumen(Esquema):
    id: str
    nombre: str
    revision: int
    propietario: str
    maquinas: int
    actualizado: str


class IndustriaDetalle(Esquema):
    id: str
    revision: int
    creado: str
    actualizado: str
    datos: BorradorIndustria


class FilaCuadroIndustrial(Esquema):
    id: str
    descripcion: str
    tablero: str
    tipo: str
    tipo_nombre: str
    cantidad: int
    placa: str
    fases: int
    tension_v: float
    fp: float
    eficiencia: float
    factor_utilizacion: float
    factor_simultaneidad: float
    instalada_kw: float
    corriente_a: float
    demanda_kw: float
    arranque: str | None
    corriente_arranque_a: float | None
    supuestos: list[str]


class TableroIndustrial(Esquema):
    tablero: str
    maquinas: int
    instalada_kw: float
    demanda_kw: float
    demanda_kva: float
    fp: float
    corriente_a: float
    breaker_a: float | None


class ComprobacionOut(Esquema):
    nombre: str
    cumple: bool
    detalle: str


class TransformadorOut(Esquema):
    kva: float
    fases: int
    montaje: str
    z_pct: float


class DecisionOut(Esquema):
    nivel: str
    nivel_nombre: str
    medicion: str
    opcion: Literal["existente", "particular", "pendiente"]
    titulo: str
    motivos: list[str]
    comprobaciones: list[ComprobacionOut]
    transformador: TransformadorOut | None


class AnalisisOut(Esquema):
    estado: Literal["listo", "incompleto"]
    revision: int
    aviso: str
    pendientes: list[str] = []
    sistema: str = ""
    filas: list[FilaCuadroIndustrial] = []
    tableros: list[TableroIndustrial] = []
    resultados: list[ResultadoOut] = []
    decision: DecisionOut | None = None
    alimentadores: list[AlimentadorOut] = []
    circuitos: list[CircuitoOut] = []
    cortocircuito: list[CortocircuitoOut] = []
    #: Fuente usada en el cortocircuito: transformador particular o existente.
    fuente_cortocircuito: str = ""
    coordinacion: CoordinacionOut | None = None
    avisos: list[str] = []
    estado_tablas: Estado | None = None


class AlimentadorOut(Esquema):
    tablero: str
    corriente_a: float
    breaker_a: float | None
    conductor: str | None
    longitud_m: float | None
    caida_pct: float | None
    distancia_supuesta: bool


class CircuitoOut(Esquema):
    maquina: str
    tablero: str
    polos: int
    corriente_a: float
    breaker_a: float | None
    conductor: str | None
    caida_pct: float | None


class CortocircuitoOut(Esquema):
    punto: str
    ik_ka: float
    ip_ka: float
    capacidad_ka: float | None


class ParOut(Esquema):
    aguas_arriba: str
    aguas_abajo: str
    punto: str
    ik_ka: float
    hasta_ka: float
    selectivo: bool
    detalle: str


class CoordinacionOut(Esquema):
    fusible: str | None
    transformador: list[ComprobacionOut]
    pares: list[ParOut]


class OpcionTexto(Esquema):
    id: str
    nombre: str


class OpcionesIndustriales(Esquema):
    tipos: list[OpcionTexto]
    arranques: list[OpcionTexto]
    sistemas: list[OpcionTexto]
    estratos: list[OpcionTexto]
    niveles: list[OpcionTexto]


# --- Utilidades ----------------------------------------------------------------


def _perfil(perfiles: Perfiles, id: str) -> Perfil:
    perfil = next((p for p in perfiles.todos() if p.meta.id == id), None)
    if perfil is None or not perfil.es_industrial():
        raise Problema(
            422,
            "perfil_no_disponible",
            "El perfil no admite proyectos industriales",
            f"El perfil {id} no tiene las tablas industriales.",
        )
    return perfil


def _buscar(sesion: Session, id: str) -> IndustriaBD:
    fila = sesion.get(IndustriaBD, id)
    if fila is None:
        raise Problema(404, "industria_no_encontrada", "La industria no existe")
    return fila


def _detalle(fila: IndustriaBD) -> IndustriaDetalle:
    return IndustriaDetalle(
        id=fila.id,
        revision=fila.revision,
        creado=fila.creado,
        actualizado=fila.actualizado,
        datos=BorradorIndustria.model_validate_json(fila.datos),
    )


def _exigir_revision(fila: IndustriaBD, revision: int) -> None:
    if revision != fila.revision:
        raise Problema(
            409,
            "revision_desactualizada",
            "La industria cambió desde que la abrió",
            f"Usted editaba la revisión {revision} y la actual es {fila.revision}. "
            "Recargue y repita el cambio.",
        )


def _guardar(sesion: Session, fila: IndustriaBD, datos: BorradorIndustria) -> IndustriaDetalle:
    fila.nombre = datos.nombre
    fila.datos = datos.model_dump_json()
    fila.revision += 1
    fila.actualizado = ahora()
    sesion.commit()
    return _detalle(fila)


def _f(valor: Decimal) -> float:
    return float(round(valor, 4))


def _opt(valor: Decimal | None) -> float | None:
    return _f(valor) if valor is not None else None


def analisis_a_salida(
    analisis: AnalisisIndustrial,
    estudios: Estudios,
    coordinacion: Coordinacion,
    perfil: Perfil,
    revision: int,
) -> AnalisisOut:
    d = analisis.decision
    t = d.transformador
    return AnalisisOut(
        estado="listo",
        revision=revision,
        aviso=AVISO_BORRADOR,
        sistema=analisis.sistema.descripcion,
        filas=[
            FilaCuadroIndustrial(
                id=f.maquina.id,
                descripcion=f.maquina.descripcion,
                tablero=f.maquina.tablero,
                tipo=f.maquina.tipo,
                tipo_nombre=f.tipo_nombre,
                cantidad=f.maquina.cantidad,
                placa=f"{f.maquina.potencia} {f.maquina.unidad}",
                fases=f.maquina.fases,
                tension_v=_f(f.tension_v),
                fp=_f(f.fp),
                eficiencia=_f(f.eficiencia),
                factor_utilizacion=_f(f.factor_utilizacion),
                factor_simultaneidad=_f(f.factor_simultaneidad),
                instalada_kw=_f(f.instalada_kw),
                corriente_a=_f(f.corriente_a),
                demanda_kw=_f(f.demanda_kw),
                arranque=f.arranque,
                corriente_arranque_a=(
                    _f(f.corriente_arranque_a) if f.corriente_arranque_a is not None else None
                ),
                supuestos=list(f.supuestos),
            )
            for f in analisis.filas
        ],
        tableros=[
            TableroIndustrial(
                tablero=x.tablero,
                maquinas=x.maquinas,
                instalada_kw=_f(x.instalada_kw),
                demanda_kw=_f(x.demanda_kw),
                demanda_kva=_f(x.demanda_kva),
                fp=_f(x.fp),
                corriente_a=_f(x.corriente_a),
                breaker_a=_f(x.breaker_a) if x.breaker_a is not None else None,
            )
            for x in analisis.tableros
        ],
        resultados=[
            resultado_a_salida(r, perfil)
            for r in (*analisis.resultados, *estudios.resultados, *coordinacion.resultados)
        ],
        alimentadores=[
            AlimentadorOut(
                tablero=x.tablero,
                corriente_a=_f(x.corriente_a),
                breaker_a=_opt(x.breaker_a),
                conductor=x.conductor.texto if x.conductor else None,
                longitud_m=_opt(x.conductor.longitud_m) if x.conductor else None,
                caida_pct=_opt(x.conductor.caida_pct) if x.conductor else None,
                distancia_supuesta=x.distancia_supuesta,
            )
            for x in estudios.alimentadores
        ],
        circuitos=[
            CircuitoOut(
                maquina=c.maquina,
                tablero=c.tablero,
                polos=c.polos,
                corriente_a=_f(c.corriente_a),
                breaker_a=_opt(c.breaker_a),
                conductor=c.conductor.texto if c.conductor else None,
                caida_pct=_opt(c.conductor.caida_pct) if c.conductor else None,
            )
            for c in estudios.circuitos
        ],
        cortocircuito=[
            CortocircuitoOut(
                punto=c.punto,
                ik_ka=_f(c.ik_ka),
                ip_ka=_f(c.ip_ka),
                capacidad_ka=_opt(c.capacidad_ka),
            )
            for c in estudios.cortocircuito
        ],
        fuente_cortocircuito=estudios.fuente,
        coordinacion=CoordinacionOut(
            fusible=f"{coordinacion.fusible_a}K" if coordinacion.fusible_a is not None else None,
            transformador=[
                ComprobacionOut(nombre=c.nombre, cumple=c.cumple, detalle=c.detalle)
                for c in coordinacion.transformador
            ],
            pares=[
                ParOut(
                    aguas_arriba=x.aguas_arriba,
                    aguas_abajo=x.aguas_abajo,
                    punto=x.punto,
                    ik_ka=_f(x.ik_ka),
                    hasta_ka=_f(x.hasta_ka),
                    selectivo=x.selectivo,
                    detalle=x.detalle,
                )
                for x in coordinacion.pares
            ],
        ),
        decision=DecisionOut(
            nivel=d.nivel.id,
            nivel_nombre=d.nivel.nombre,
            medicion=d.nivel.medicion.upper(),
            opcion=d.opcion,
            titulo=d.titulo,
            motivos=list(d.motivos),
            comprobaciones=[
                ComprobacionOut(nombre=c.nombre, cumple=c.cumple, detalle=c.detalle)
                for c in d.comprobaciones
            ],
            transformador=(
                TransformadorOut(kva=_f(t.kva), fases=t.fases, montaje=t.montaje, z_pct=_f(t.z_pct))
                if t is not None
                else None
            ),
        ),
        avisos=[*analisis.avisos, *estudios.avisos, *coordinacion.avisos],
        estado_tablas=peor_estado([analisis.estado, estudios.estado, coordinacion.estado]),
    )


# --- Rutas ---------------------------------------------------------------------


@rutas.get("/industrial/opciones")
def opciones_industriales(
    perfiles: PerfilesDep, perfil: Annotated[str, Query()] = "cnel-ep"
) -> OpcionesIndustriales:
    p = _perfil(perfiles, perfil)
    sistemas = p.tablas["sistemas_tension"]
    assert isinstance(sistemas, TablaSistemas)
    return OpcionesIndustriales(
        tipos=[OpcionTexto(id=t.tipo, nombre=t.nombre) for t in p.tipos_industriales()],
        arranques=[OpcionTexto(id=a.id, nombre=a.nombre) for a in p.arranques()],
        sistemas=[OpcionTexto(id=s.id, nombre=s.descripcion) for s in sistemas.filas],
        estratos=[
            OpcionTexto(id=e.estrato, nombre=e.descripcion or e.estrato) for e in p.estratos()
        ],
        niveles=[OpcionTexto(id=n.id, nombre=n.nombre) for n in p.niveles_servicio()],
    )


@rutas.get(
    "/industrial/plantilla",
    response_class=Response,
    responses={200: {"content": {"application/vnd.ms-excel": {}}}},
)
def descargar_plantilla(
    perfiles: PerfilesDep, perfil: Annotated[str, Query()] = "cnel-ep"
) -> Response:
    p = _perfil(perfiles, perfil)
    datos = plantilla(
        [(t.tipo, t.nombre) for t in p.tipos_industriales()],
        [(a.id, a.nombre) for a in p.arranques()],
    )
    return Response(
        datos,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="cuadro-de-cargas.xlsx"'},
    )


@rutas.get("/industrias")
def listar_industrias(sesion: SesionDep) -> list[IndustriaResumen]:
    filas = sesion.scalars(select(IndustriaBD).order_by(IndustriaBD.actualizado.desc())).all()
    salida = []
    for f in filas:
        datos = BorradorIndustria.model_validate_json(f.datos)
        salida.append(
            IndustriaResumen(
                id=f.id,
                nombre=f.nombre,
                revision=f.revision,
                propietario=datos.propietario,
                maquinas=len(datos.maquinas),
                actualizado=f.actualizado,
            )
        )
    return salida


@rutas.post("/industrias", status_code=201)
def crear_industria(
    datos: BorradorIndustria, sesion: SesionDep, perfiles: PerfilesDep
) -> IndustriaDetalle:
    _perfil(perfiles, datos.perfil)
    momento = ahora()
    fila = IndustriaBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        revision=1,
        datos=datos.model_dump_json(),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    sesion.commit()
    return _detalle(fila)


@rutas.get("/industrias/{id}")
def leer_industria(id: str, sesion: SesionDep) -> IndustriaDetalle:
    return _detalle(_buscar(sesion, id))


@rutas.put("/industrias/{id}")
def guardar_industria(
    id: str, cuerpo: GuardarIndustria, sesion: SesionDep, perfiles: PerfilesDep
) -> IndustriaDetalle:
    fila = _buscar(sesion, id)
    _exigir_revision(fila, cuerpo.revision)
    _perfil(perfiles, cuerpo.datos.perfil)
    return _guardar(sesion, fila, cuerpo.datos)


@rutas.delete("/industrias/{id}", status_code=204)
def borrar_industria(id: str, sesion: SesionDep) -> Response:
    sesion.delete(_buscar(sesion, id))
    sesion.commit()
    return Response(status_code=204)


@rutas.post("/industrias/{id}/cuadro")
def subir_cuadro(
    id: str,
    sesion: SesionDep,
    contenido: Annotated[bytes, Body(media_type="application/octet-stream")],
    revision: Annotated[int, Query()],
    nombre: Annotated[str, Query(max_length=200)] = "cuadro.xlsx",
) -> IndustriaDetalle:
    """Reemplaza las máquinas por las del cuadro de cargas (.xlsx o .csv)."""
    fila = _buscar(sesion, id)
    _exigir_revision(fila, revision)
    try:
        maquinas = leer_cuadro(contenido, nombre)
    except ErrorElectric as error:
        raise Problema(422, error.codigo, "No se pudo leer el cuadro de cargas", str(error)) from (
            error
        )
    datos = BorradorIndustria.model_validate_json(fila.datos).model_copy(
        update={"maquinas": list(maquinas), "cuadro": nombre}
    )
    return _guardar(sesion, fila, datos)


def _estudiar(
    datos: BorradorIndustria, perfil: Perfil
) -> tuple[AnalisisIndustrial, Estudios, Coordinacion] | str:
    """Análisis y estudios, o el motivo por el que todavía no se puede."""
    if not datos.maquinas:
        return "Cargue el cuadro de cargas o agregue al menos una máquina."
    try:
        industria = Industria(
            nombre=datos.nombre,
            sistema=datos.sistema,
            maquinas=tuple(datos.maquinas),
            fp_objetivo=datos.fp_objetivo,
            ubicacion=datos.ubicacion,
            existente=datos.existente,
            distancias_m=datos.distancias_m,
            scc_red_mva=datos.scc_red_mva,
        )
        analisis = analizar(industria, perfil)
        estudios = estudiar(analisis, perfil)
        return analisis, estudios, coordinar(analisis, estudios, perfil)
    except (ErrorElectric, ValueError) as error:
        return str(error)


@rutas.get("/industrias/{id}/analisis")
def analizar_industria(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> AnalisisOut:
    fila = _buscar(sesion, id)
    datos = BorradorIndustria.model_validate_json(fila.datos)
    perfil = _perfil(perfiles, datos.perfil)
    resultado = _estudiar(datos, perfil)
    if isinstance(resultado, str):
        return AnalisisOut(
            estado="incompleto",
            revision=fila.revision,
            aviso=AVISO_BORRADOR,
            pendientes=[resultado],
        )
    analisis, estudios, coordinacion = resultado
    return analisis_a_salida(analisis, estudios, coordinacion, perfil, fila.revision)


TIPOS = {
    "dxf": "application/dxf",
    "png": "image/png",
    "pdf": "application/pdf",
}


@rutas.get(
    "/industrias/{id}/unifilar.{formato}",
    response_class=Response,
    responses={200: {"content": {t: {} for t in TIPOS.values()}}},
)
def descargar_unifilar(
    id: str, formato: Literal["dxf", "png", "pdf"], sesion: SesionDep, perfiles: PerfilesDep
) -> Response:
    fila = _buscar(sesion, id)
    datos = BorradorIndustria.model_validate_json(fila.datos)
    resultado = _estudiar(datos, _perfil(perfiles, datos.perfil))
    if isinstance(resultado, str):
        raise Problema(
            422, "industria_incompleta", "Todavía no se puede dibujar el unifilar", resultado
        )
    analisis, estudios, coordinacion = resultado
    dxf = generar_unifilar(analisis, estudios, coordinacion.fusible_a)
    contenido = dxf if formato == "dxf" else renderizar(dxf, formato)
    disposicion = "attachment" if formato == "dxf" else "inline"
    return Response(
        contenido,
        media_type=TIPOS[formato],
        headers={"Content-Disposition": f'{disposicion}; filename="unifilar.{formato}"'},
    )


@rutas.get(
    "/industrias/{id}/curvas.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def descargar_curvas(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> Response:
    """Curvas tiempo-corriente de las protecciones en serie."""
    fila = _buscar(sesion, id)
    datos = BorradorIndustria.model_validate_json(fila.datos)
    resultado = _estudiar(datos, _perfil(perfiles, datos.perfil))
    if isinstance(resultado, str):
        raise Problema(422, "industria_incompleta", "Todavía no hay curvas", resultado)
    return Response(
        grafico(resultado[2], f"Coordinación · {datos.nombre}"),
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="curvas.png"'},
    )
