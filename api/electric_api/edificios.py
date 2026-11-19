"""Rutas de edificios: departamentos, locales y oficinas con centro de medición."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Literal

from electric.cli import AVISO_BORRADOR
from electric.edificio import (
    CargaGeneral,
    Edificio,
    EdificioCalculado,
    TipoUnidad,
    calcular_edificio,
    generar_unifilar_edificio,
)
from electric.edificio.modelo import Respaldo
from electric.errores import ErrorElectric
from electric.mt.camara import generar_plano_camara
from electric.perfiles import Perfil
from electric.perfiles.esquema import TablaSistemas
from electric.salida_cad import renderizar
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from electric_api.config import Config
from electric_api.db import EdificioBD, ahora
from electric_api.esquemas import Esquema, ResultadoOut
from electric_api.industrial import CamaraOut, camara_a_salida
from electric_api.problemas import Problema
from electric_api.servicio import Perfiles, resultado_a_salida

rutas = APIRouter(prefix="/api/v1", tags=["edificios"])


def _sesion(request: Request) -> Iterator[Session]:
    with request.app.state.sesiones() as sesion:
        yield sesion


def _perfiles(request: Request) -> Perfiles:
    perfiles: Perfiles = request.app.state.perfiles
    return perfiles


SesionDep = Annotated[Session, Depends(_sesion)]
PerfilesDep = Annotated[Perfiles, Depends(_perfiles)]


# --- Esquemas ----------------------------------------------------------------------


class BorradorEdificio(Esquema):
    """Edificio en edición; puede no tener unidades todavía."""

    nombre: str = Field(min_length=1, max_length=200)
    perfil: str = "cnel-ep"
    propietario: str = Field(default="", max_length=200)
    direccion: str = Field(default="", max_length=300)
    #: departamentos, locales_oficinas o comercial (solo cambia los valores iniciales en la web).
    tipo: Literal["departamentos", "locales_oficinas", "comercial"] = "departamentos"
    sistema: str = "trifasico_127_220"
    nivel_medidores: int = 0
    altura_piso_m: Decimal | None = Field(default=None, gt=0)
    recorrido_horizontal_m: Decimal | None = Field(default=None, ge=0)
    distancia_transformador_m: Decimal | None = Field(default=None, ge=0)
    unidades: list[TipoUnidad] = Field(default=[], max_length=200)
    servicios: list[CargaGeneral] = Field(default=[], max_length=200)
    respaldo: Respaldo = "ninguno"
    resistividad_ohm_m: Decimal | None = Field(default=None, gt=0)


class GuardarEdificio(Esquema):
    revision: int
    datos: BorradorEdificio


class EdificioResumen(Esquema):
    id: str
    nombre: str
    tipo: str
    propietario: str
    unidades: int
    actualizado: str


class EdificioDetalle(Esquema):
    id: str
    revision: int
    creado: str
    actualizado: str
    datos: BorradorEdificio


class UnidadOut(Esquema):
    id: str
    tipo: str
    uso: str
    piso: int
    fases: int
    demanda_kva: float
    corriente_a: float
    breaker_a: float | None
    medidor: str
    conductor: str | None
    longitud_m: float
    caida_pct: float | None


class GrupoOut(Esquema):
    nombre: str
    usuarios: int
    suma_kva: float
    factor: float
    demanda_kva: float


class ServiciosOut(Esquema):
    instalada_kva: float
    demanda_kva: float
    corriente_a: float
    breaker_a: float | None
    medidor: str
    conductor: str | None


class PrincipalOut(Esquema):
    corriente_a: float
    breaker_a: float | None
    conductor: str | None
    caida_pct: float | None
    longitud_m: float | None
    barra_a: float | None
    icc_ka: float | None


class TransformadorEdificioOut(Esquema):
    kva: float
    montaje: str
    z_pct: float


class GeneradorOut(Esquema):
    alcance: str
    carga_kva: float
    kva: float | None
    transferencia_a: float | None


class IluminacionOut(Esquema):
    tipo: str
    uso: str
    area_m2: float
    lux: float
    luminarias: int
    potencia_w: float
    w_m2: float
    lux_logrado: float
    circuitos_luz: int
    puestos: int
    tomas: int
    circuitos_tomas: int
    demanda_detallada_kva: float
    demanda_densidad_kva: float


class CalculoEdificio(Esquema):
    estado: Literal["listo", "incompleto"]
    revision: int
    aviso: str
    pendientes: list[str] = []
    demanda_kva: float = 0
    demanda_kw: float = 0
    nivel: str = ""
    nivel_id: str = ""
    medicion: str = ""
    medidores: int = 0
    modulos: int = 0
    grupos: list[GrupoOut] = []
    unidades: list[UnidadOut] = []
    servicios: ServiciosOut | None = None
    principal: PrincipalOut | None = None
    transformador: TransformadorEdificioOut | None = None
    camara: CamaraOut | None = None
    generador: GeneradorOut | None = None
    iluminacion: list[IluminacionOut] = []
    resultados: list[ResultadoOut] = []
    avisos: list[str] = []


class OpcionUsuario(Esquema):
    id: str
    nombre: str
    kva: float | None
    va_m2: float | None


class OpcionesEdificio(Esquema):
    usuarios: list[OpcionUsuario]
    sistemas: list[OpcionUsuario]


# --- Ayudas -----------------------------------------------------------------------


def _perfil(perfiles: Perfiles, id: str) -> Perfil:
    perfil = next((p for p in perfiles.todos() if p.meta.id == id), None)
    if perfil is None or not perfil.demandas_usuario():
        raise Problema(422, "perfil_no_disponible", "El perfil no admite edificios", id)
    return perfil


def _buscar(sesion: Session, id: str) -> EdificioBD:
    fila = sesion.get(EdificioBD, id)
    if fila is None:
        raise Problema(404, "edificio_no_encontrado", "Edificio no encontrado")
    return fila


def _detalle(fila: EdificioBD) -> EdificioDetalle:
    return EdificioDetalle(
        id=fila.id,
        revision=fila.revision,
        creado=fila.creado,
        actualizado=fila.actualizado,
        datos=BorradorEdificio.model_validate_json(fila.datos),
    )


def _f(valor: Decimal) -> float:
    return round(float(valor), 4)


def _opt(valor: Decimal | None) -> float | None:
    return None if valor is None else _f(valor)


def _calcular(datos: BorradorEdificio, perfil: Perfil) -> EdificioCalculado | list[str]:
    if not datos.unidades:
        return ["Agregue al menos un tipo de unidad (departamentos, locales u oficinas)."]
    try:
        propios = datos.model_dump(exclude={"perfil", "propietario", "direccion", "tipo"})
        edificio = Edificio.model_validate(propios)
        return calcular_edificio(edificio, perfil)
    except ValidationError as error:
        return [e["msg"] for e in error.errors()]
    except (ErrorElectric, ValueError) as error:
        return [str(error)]


def _calculado(sesion: Session, id: str, perfiles: Perfiles) -> EdificioCalculado:
    fila = _buscar(sesion, id)
    datos = BorradorEdificio.model_validate_json(fila.datos)
    calculo = _calcular(datos, _perfil(perfiles, datos.perfil))
    if isinstance(calculo, list):
        raise Problema(422, "edificio_incompleto", "El edificio está incompleto", " ".join(calculo))
    return calculo


# --- Rutas --------------------------------------------------------------------------


@rutas.get("/edificio/opciones")
def opciones_edificio(
    perfiles: PerfilesDep, perfil: Annotated[str, Query()] = "cnel-ep"
) -> OpcionesEdificio:
    p = _perfil(perfiles, perfil)
    sistemas = p._tabla("sistemas_tension", TablaSistemas).filas
    return OpcionesEdificio(
        usuarios=[
            OpcionUsuario(id=u.id, nombre=u.descripcion, kva=_opt(u.kva), va_m2=_opt(u.va_m2))
            for u in p.demandas_usuario()
        ],
        sistemas=[
            OpcionUsuario(id=s.id, nombre=s.descripcion, kva=None, va_m2=None)
            for s in sistemas
            if s.fases == 3
        ],
    )


@rutas.get("/edificios")
def listar_edificios(sesion: SesionDep) -> list[EdificioResumen]:
    filas = sesion.scalars(select(EdificioBD).order_by(EdificioBD.actualizado.desc())).all()
    salida = []
    for f in filas:
        datos = BorradorEdificio.model_validate_json(f.datos)
        salida.append(
            EdificioResumen(
                id=f.id,
                nombre=f.nombre,
                tipo=datos.tipo,
                propietario=datos.propietario,
                unidades=sum(u.cantidad for u in datos.unidades),
                actualizado=f.actualizado,
            )
        )
    return salida


def _nuevo(sesion: Session, datos: BorradorEdificio) -> EdificioBD:
    momento = ahora()
    fila = EdificioBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        revision=1,
        datos=datos.model_dump_json(),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    return fila


@rutas.post("/edificios", status_code=201)
def crear_edificio(
    datos: BorradorEdificio, sesion: SesionDep, perfiles: PerfilesDep
) -> EdificioDetalle:
    _perfil(perfiles, datos.perfil)
    fila = _nuevo(sesion, datos)
    sesion.commit()
    return _detalle(fila)


@rutas.get("/edificios/{id}")
def leer_edificio(id: str, sesion: SesionDep) -> EdificioDetalle:
    return _detalle(_buscar(sesion, id))


@rutas.put("/edificios/{id}")
def guardar_edificio(
    id: str, cuerpo: GuardarEdificio, sesion: SesionDep, perfiles: PerfilesDep
) -> EdificioDetalle:
    fila = _buscar(sesion, id)
    if cuerpo.revision != fila.revision:
        raise Problema(
            409,
            "revision_desactualizada",
            "El edificio cambió desde que lo abrió",
            f"Usted editaba la revisión {cuerpo.revision} y la actual es {fila.revision}.",
        )
    _perfil(perfiles, cuerpo.datos.perfil)
    fila.nombre = cuerpo.datos.nombre
    fila.datos = cuerpo.datos.model_dump_json()
    fila.revision += 1
    fila.actualizado = ahora()
    sesion.commit()
    return _detalle(fila)


@rutas.delete("/edificios/{id}", status_code=204)
def borrar_edificio(id: str, sesion: SesionDep) -> Response:
    sesion.delete(_buscar(sesion, id))
    sesion.commit()
    return Response(status_code=204)


@rutas.get("/edificios/{id}/calculo")
def calcular(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> CalculoEdificio:
    fila = _buscar(sesion, id)
    datos = BorradorEdificio.model_validate_json(fila.datos)
    perfil = _perfil(perfiles, datos.perfil)
    c = _calcular(datos, perfil)
    if isinstance(c, list):
        return CalculoEdificio(
            estado="incompleto", revision=fila.revision, aviso=AVISO_BORRADOR, pendientes=c
        )
    p = c.principal
    return CalculoEdificio(
        estado="listo",
        revision=fila.revision,
        aviso=AVISO_BORRADOR,
        demanda_kva=_f(c.demanda_kva),
        demanda_kw=_f(c.demanda_kw),
        nivel=c.nivel.nombre,
        nivel_id=c.nivel.id,
        medicion=c.nivel.medicion,
        medidores=c.medidores,
        modulos=c.modulos,
        grupos=[
            GrupoOut(
                nombre=g.nombre,
                usuarios=g.usuarios,
                suma_kva=_f(g.suma_kva),
                factor=_f(g.factor),
                demanda_kva=_f(g.demanda_kva),
            )
            for g in c.grupos
        ],
        unidades=[
            UnidadOut(
                id=u.id,
                tipo=u.tipo,
                uso=u.uso,
                piso=u.piso,
                fases=u.fases,
                demanda_kva=_f(u.demanda_kva),
                corriente_a=_f(u.corriente_a),
                breaker_a=_opt(u.breaker_a),
                medidor=u.medidor,
                conductor=u.conductor.texto if u.conductor else None,
                longitud_m=_f(u.longitud_m),
                caida_pct=_f(u.conductor.caida_pct) if u.conductor else None,
            )
            for u in c.unidades
        ],
        servicios=(
            ServiciosOut(
                instalada_kva=_f(c.servicios.instalada_kva),
                demanda_kva=_f(c.servicios.demanda_kva),
                corriente_a=_f(c.servicios.corriente_a),
                breaker_a=_opt(c.servicios.breaker_a),
                medidor=c.servicios.medidor,
                conductor=c.servicios.conductor.texto if c.servicios.conductor else None,
            )
            if c.servicios
            else None
        ),
        principal=PrincipalOut(
            corriente_a=_f(p.corriente_a),
            breaker_a=_opt(p.breaker_a),
            conductor=p.conductor.texto if p.conductor else None,
            caida_pct=_f(p.conductor.caida_pct) if p.conductor else None,
            longitud_m=_f(p.conductor.longitud_m) if p.conductor else None,
            barra_a=_opt(p.barra_a),
            icc_ka=_opt(p.icc_ka),
        ),
        transformador=(
            TransformadorEdificioOut(
                kva=_f(c.transformador.kva),
                montaje=c.transformador.montaje,
                z_pct=_f(c.transformador.z_pct),
            )
            if c.transformador
            else None
        ),
        camara=camara_a_salida(c.camara) if c.camara else None,
        generador=(
            GeneradorOut(
                alcance=c.generador.alcance,
                carga_kva=_f(c.generador.carga_kva),
                kva=_opt(c.generador.kva),
                transferencia_a=_opt(c.generador.transferencia_a),
            )
            if c.generador
            else None
        ),
        iluminacion=[
            IluminacionOut(
                tipo=i.tipo,
                uso=i.uso,
                area_m2=_f(i.area_m2),
                lux=_f(i.lux),
                luminarias=i.luminarias,
                potencia_w=_f(i.potencia_w),
                w_m2=_f(i.w_m2),
                lux_logrado=_f(i.lux_logrado),
                circuitos_luz=i.circuitos_luz,
                puestos=i.puestos,
                tomas=i.tomas,
                circuitos_tomas=i.circuitos_tomas,
                demanda_detallada_kva=_f(i.demanda_detallada_kva),
                demanda_densidad_kva=_f(i.demanda_densidad_kva),
            )
            for i in c.iluminacion
        ],
        resultados=[resultado_a_salida(r, perfil) for r in c.resultados],
        avisos=list(c.avisos),
    )


TIPOS = {"dxf": "application/dxf", "png": "image/png", "pdf": "application/pdf"}


@rutas.get(
    "/edificios/{id}/{plano}.{formato}",
    response_class=Response,
    responses={200: {"content": {t: {} for t in TIPOS.values()}}},
)
def descargar_plano(
    id: str,
    plano: Literal["unifilar", "camara"],
    formato: Literal["dxf", "png", "pdf"],
    sesion: SesionDep,
    perfiles: PerfilesDep,
) -> Response:
    c = _calculado(sesion, id, perfiles)
    if plano == "camara":
        if c.camara is None:
            raise Problema(404, "sin_camara", "Este edificio no lleva cámara de transformación")
        breaker = f"3P {c.principal.breaker_a} A" if c.principal.breaker_a else None
        dxf = generar_plano_camara(c.camara, c.edificio.nombre, breaker)
    else:
        dxf = generar_unifilar_edificio(c)
    contenido = dxf if formato == "dxf" else renderizar(dxf, formato)
    disposicion = "attachment" if formato == "dxf" else "inline"
    return Response(
        contenido,
        media_type=TIPOS[formato],
        headers={"Content-Disposition": f'{disposicion}; filename="{plano}.{formato}"'},
    )


@rutas.post("/ejemplos/edificio", status_code=201)
def crear_ejemplo_edificio(
    request: Request, sesion: SesionDep, perfiles: PerfilesDep
) -> EdificioDetalle:
    """Crea el edificio de departamentos de ejemplo del repositorio."""
    config: Config = request.app.state.config
    ruta = config.ejemplos / "edificio-departamentos" / "edificio.json"
    if not ruta.is_file():
        raise Problema(404, "ejemplo_no_disponible", "El ejemplo no está disponible")
    _perfil(perfiles, "cnel-ep")
    datos = BorradorEdificio.model_validate_json(ruta.read_text("utf-8"))
    fila = _nuevo(sesion, datos)
    sesion.commit()
    return _detalle(fila)
