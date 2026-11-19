"""Rutas de subestaciones de cliente 69/13,8 kV."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Literal

from electric.cli import AVISO_BORRADOR
from electric.errores import ErrorElectric
from electric.perfiles import Perfil
from electric.salida_cad import renderizar
from electric.subestacion import (
    Subestacion,
    SubestacionCalculada,
    calcular_subestacion,
    generar_plano_malla,
    generar_unifilar_subestacion,
)
from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from electric_api.db import SubestacionBD, ahora
from electric_api.esquemas import Esquema, ResultadoOut
from electric_api.problemas import Problema
from electric_api.servicio import Perfiles, resultado_a_salida

rutas = APIRouter(prefix="/api/v1", tags=["subestaciones"])


def _sesion(request: Request) -> Iterator[Session]:
    with request.app.state.sesiones() as sesion:
        yield sesion


def _perfiles(request: Request) -> Perfiles:
    perfiles: Perfiles = request.app.state.perfiles
    return perfiles


SesionDep = Annotated[Session, Depends(_sesion)]
PerfilesDep = Annotated[Perfiles, Depends(_perfiles)]


class BorradorSubestacion(Esquema):
    nombre: str = Field(min_length=1, max_length=200)
    perfil: str = "cnel-ep"
    propietario: str = Field(default="", max_length=200)
    demanda_mva: Decimal | None = Field(default=None, gt=0, le=200)
    fp: Decimal = Field(default=Decimal("0.92"), gt=0, le=1)
    tension_at_kv: Decimal | None = Field(default=None, gt=0)
    tension_mt_kv: Decimal | None = Field(default=None, gt=0)
    scc_at_mva: Decimal | None = Field(default=None, gt=0)
    alimentadores: int = Field(default=4, ge=1, le=16)
    largo_malla_m: Decimal = Field(default=Decimal(40), gt=0, le=500)
    ancho_malla_m: Decimal = Field(default=Decimal(30), gt=0, le=500)
    resistividad_ohm_m: Decimal | None = Field(default=None, gt=0)
    tiempo_falla_s: Decimal | None = Field(default=None, gt=0, le=3)


class GuardarSubestacion(Esquema):
    revision: int
    datos: BorradorSubestacion


class SubestacionResumen(Esquema):
    id: str
    nombre: str
    propietario: str
    demanda_mva: float | None
    actualizado: str


class SubestacionDetalle(Esquema):
    id: str
    revision: int
    creado: str
    actualizado: str
    datos: BorradorSubestacion


class EquipoOut(Esquema):
    nombre: str
    especificacion: str


class MallaOut(Esquema):
    largo_m: float
    ancho_m: float
    separacion_m: float
    conductores_x: int
    conductores_y: int
    varillas: int
    longitud_conductor_m: float
    calibre: str
    calibre_minimo_kcmil: float
    resistencia_ohm: float
    limite_resistencia_ohm: float
    resistencia_cumple: bool
    corriente_malla_a: float
    gpr_v: float
    tension_malla_v: float
    tension_paso_v: float
    contacto_tolerable_v: float
    paso_tolerable_v: float
    cumple: bool


class CalculoSubestacion(Esquema):
    estado: Literal["listo", "incompleto"]
    revision: int
    aviso: str
    pendientes: list[str] = []
    transformador: str | None = None
    z_pct: float | None = None
    tension_at_kv: float = 0
    tension_mt_kv: float = 0
    scc_at_mva: float = 0
    scc_supuesta: bool = True
    corriente_at_a: float = 0
    corriente_mt_a: float = 0
    icc_at_ka: float = 0
    icc_mt_ka: float = 0
    corriente_alimentador_a: float = 0
    equipos: list[EquipoOut] = []
    malla: MallaOut | None = None
    resultados: list[ResultadoOut] = []
    avisos: list[str] = []


def _perfil(perfiles: Perfiles, id: str) -> Perfil:
    perfil = next((p for p in perfiles.todos() if p.meta.id == id), None)
    if perfil is None or "transformadores_potencia" not in perfil.tablas:
        raise Problema(422, "perfil_no_disponible", "El perfil no admite subestaciones", id)
    return perfil


def _buscar(sesion: Session, id: str) -> SubestacionBD:
    fila = sesion.get(SubestacionBD, id)
    if fila is None:
        raise Problema(404, "subestacion_no_encontrada", "Subestación no encontrada")
    return fila


def _detalle(fila: SubestacionBD) -> SubestacionDetalle:
    return SubestacionDetalle(
        id=fila.id,
        revision=fila.revision,
        creado=fila.creado,
        actualizado=fila.actualizado,
        datos=BorradorSubestacion.model_validate_json(fila.datos),
    )


def _f(valor: Decimal | float) -> float:
    return round(float(valor), 4)


def _calcular(datos: BorradorSubestacion, perfil: Perfil) -> SubestacionCalculada | list[str]:
    if datos.demanda_mva is None:
        return ["Indique la demanda máxima de la subestación en MVA."]
    try:
        se = Subestacion.model_validate(datos.model_dump(exclude={"perfil", "propietario"}))
        return calcular_subestacion(se, perfil)
    except ValidationError as error:
        return [e["msg"] for e in error.errors()]
    except (ErrorElectric, ValueError) as error:
        return [str(error)]


def _nueva(sesion: Session, datos: BorradorSubestacion) -> SubestacionBD:
    momento = ahora()
    fila = SubestacionBD(
        id=str(uuid.uuid4()),
        nombre=datos.nombre,
        revision=1,
        datos=datos.model_dump_json(),
        creado=momento,
        actualizado=momento,
    )
    sesion.add(fila)
    return fila


@rutas.get("/subestaciones")
def listar(sesion: SesionDep) -> list[SubestacionResumen]:
    filas = sesion.scalars(select(SubestacionBD).order_by(SubestacionBD.actualizado.desc()))
    salida = []
    for f in filas.all():
        d = BorradorSubestacion.model_validate_json(f.datos)
        salida.append(
            SubestacionResumen(
                id=f.id,
                nombre=f.nombre,
                propietario=d.propietario,
                demanda_mva=_f(d.demanda_mva) if d.demanda_mva else None,
                actualizado=f.actualizado,
            )
        )
    return salida


@rutas.post("/subestaciones", status_code=201)
def crear(
    datos: BorradorSubestacion, sesion: SesionDep, perfiles: PerfilesDep
) -> SubestacionDetalle:
    _perfil(perfiles, datos.perfil)
    fila = _nueva(sesion, datos)
    sesion.commit()
    return _detalle(fila)


@rutas.get("/subestaciones/{id}")
def leer(id: str, sesion: SesionDep) -> SubestacionDetalle:
    return _detalle(_buscar(sesion, id))


@rutas.put("/subestaciones/{id}")
def guardar(
    id: str, cuerpo: GuardarSubestacion, sesion: SesionDep, perfiles: PerfilesDep
) -> SubestacionDetalle:
    fila = _buscar(sesion, id)
    if cuerpo.revision != fila.revision:
        raise Problema(
            409,
            "revision_desactualizada",
            "La subestación cambió desde que la abrió",
            f"Usted editaba la revisión {cuerpo.revision} y la actual es {fila.revision}.",
        )
    _perfil(perfiles, cuerpo.datos.perfil)
    fila.nombre = cuerpo.datos.nombre
    fila.datos = cuerpo.datos.model_dump_json()
    fila.revision += 1
    fila.actualizado = ahora()
    sesion.commit()
    return _detalle(fila)


@rutas.delete("/subestaciones/{id}", status_code=204)
def borrar(id: str, sesion: SesionDep) -> Response:
    sesion.delete(_buscar(sesion, id))
    sesion.commit()
    return Response(status_code=204)


@rutas.get("/subestaciones/{id}/calculo")
def calcular(id: str, sesion: SesionDep, perfiles: PerfilesDep) -> CalculoSubestacion:
    fila = _buscar(sesion, id)
    datos = BorradorSubestacion.model_validate_json(fila.datos)
    perfil = _perfil(perfiles, datos.perfil)
    c = _calcular(datos, perfil)
    if isinstance(c, list):
        return CalculoSubestacion(
            estado="incompleto", revision=fila.revision, aviso=AVISO_BORRADOR, pendientes=c
        )
    t = c.transformador
    m = c.malla
    return CalculoSubestacion(
        estado="listo",
        revision=fila.revision,
        aviso=AVISO_BORRADOR,
        transformador=f"{t.mva_onan}/{t.mva_onaf} MVA ONAN/ONAF".replace(".", ",") if t else None,
        z_pct=_f(t.z_pct) if t else None,
        tension_at_kv=_f(c.tension_at_kv),
        tension_mt_kv=_f(c.tension_mt_kv),
        scc_at_mva=_f(c.scc_at_mva),
        scc_supuesta=datos.scc_at_mva is None,
        corriente_at_a=_f(c.corriente_at_a),
        corriente_mt_a=_f(c.corriente_mt_a),
        icc_at_ka=_f(c.icc_at_ka),
        icc_mt_ka=_f(c.icc_mt_ka),
        corriente_alimentador_a=_f(c.corriente_alimentador_a),
        equipos=[EquipoOut(nombre=e.nombre, especificacion=e.especificacion) for e in c.equipos],
        malla=MallaOut(
            largo_m=m.largo_m,
            ancho_m=m.ancho_m,
            separacion_m=m.separacion_m,
            conductores_x=m.conductores_x,
            conductores_y=m.conductores_y,
            varillas=m.varillas,
            longitud_conductor_m=_f(m.longitud_conductor_m),
            calibre=m.calibre,
            calibre_minimo_kcmil=_f(m.calibre_minimo_kcmil),
            resistencia_ohm=_f(m.resistencia_ohm),
            limite_resistencia_ohm=m.limite_resistencia_ohm,
            resistencia_cumple=m.resistencia_cumple,
            corriente_malla_a=_f(m.corriente_malla_a),
            gpr_v=_f(m.gpr_v),
            tension_malla_v=_f(m.tension_malla_v),
            tension_paso_v=_f(m.tension_paso_v),
            contacto_tolerable_v=_f(m.contacto_tolerable_v),
            paso_tolerable_v=_f(m.paso_tolerable_v),
            cumple=m.cumple,
        ),
        resultados=[resultado_a_salida(r, perfil) for r in c.resultados],
        avisos=list(c.avisos),
    )


TIPOS = {"dxf": "application/dxf", "png": "image/png", "pdf": "application/pdf"}


@rutas.get(
    "/subestaciones/{id}/{plano}.{formato}",
    response_class=Response,
    responses={200: {"content": {t: {} for t in TIPOS.values()}}},
)
def descargar_plano(
    id: str,
    plano: Literal["unifilar", "malla"],
    formato: Literal["dxf", "png", "pdf"],
    sesion: SesionDep,
    perfiles: PerfilesDep,
) -> Response:
    fila = _buscar(sesion, id)
    datos = BorradorSubestacion.model_validate_json(fila.datos)
    c = _calcular(datos, _perfil(perfiles, datos.perfil))
    if isinstance(c, list):
        raise Problema(422, "subestacion_incompleta", "La subestación está incompleta", " ".join(c))
    dxf = generar_unifilar_subestacion(c) if plano == "unifilar" else generar_plano_malla(c)
    contenido = dxf if formato == "dxf" else renderizar(dxf, formato)
    disposicion = "attachment" if formato == "dxf" else "inline"
    return Response(
        contenido,
        media_type=TIPOS[formato],
        headers={"Content-Disposition": f'{disposicion}; filename="{plano}.{formato}"'},
    )


@rutas.post("/ejemplos/subestacion", status_code=201)
def crear_ejemplo(sesion: SesionDep, perfiles: PerfilesDep) -> SubestacionDetalle:
    """Crea una subestación de ejemplo de 8,5 MVA."""
    _perfil(perfiles, "cnel-ep")
    datos = BorradorSubestacion(
        nombre="Subestación Planta Norte (ejemplo)",
        propietario="Ejemplo",
        demanda_mva=Decimal("8.5"),
        alimentadores=4,
    )
    fila = _nueva(sesion, datos)
    sesion.commit()
    return _detalle(fila)
