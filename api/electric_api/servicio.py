"""Lógica de la API: del borrador guardado a los resultados del núcleo."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from electric.calculo import Calculado, Resultado, calcular, presentar
from electric.calculo.cuadro import cuadro_de_cargas, resumen, tablas_sin_verificar
from electric.cli import AVISO_BORRADOR
from electric.errores import ErrorElectric, ErrorPerfil
from electric.modelo import Proyecto
from electric.perfiles import Perfil, cargar_perfil
from electric.perfiles.esquema import TablaCargas, TablaSistemas
from pydantic import ValidationError

from electric_api.esquemas import (
    Borrador,
    Calculos,
    CargaOut,
    DatoResumenOut,
    FilaCuadroOut,
    Pendiente,
    PerfilOut,
    ResultadoOut,
    SistemaOut,
    TablaOut,
    TablaPendiente,
    ValorOut,
)


class Perfiles:
    """Perfiles disponibles, cargados y validados una sola vez al arrancar."""

    def __init__(self, carpeta: Path) -> None:
        self._perfiles: dict[str, Perfil] = {}
        for ruta in sorted(carpeta.iterdir()):
            if (ruta / "perfil.yaml").is_file():
                perfil = cargar_perfil(ruta)
                self._perfiles[perfil.meta.id] = perfil
        if not self._perfiles:
            raise ErrorPerfil(f"no hay perfiles en {carpeta}")

    def todos(self) -> list[Perfil]:
        return list(self._perfiles.values())

    def buscar(self, id: str, version: str) -> Perfil | None:
        perfil = self._perfiles.get(id)
        return perfil if perfil is not None and perfil.meta.version == version else None


def perfil_a_salida(perfil: Perfil) -> PerfilOut:
    sistemas = perfil.tablas["sistemas_tension"]
    cargas = perfil.tablas["cargas"]
    assert isinstance(sistemas, TablaSistemas) and isinstance(cargas, TablaCargas)
    return PerfilOut(
        id=perfil.meta.id,
        version=perfil.meta.version,
        nombre=perfil.meta.nombre,
        distribuidora=perfil.meta.distribuidora,
        nota=perfil.meta.nota,
        sistema_defecto=perfil.meta.sistema_defecto,
        sistemas=[SistemaOut(id=s.id, descripcion=s.descripcion) for s in sistemas.filas],
        cargas=[
            CargaOut(tipo=c.tipo, potencia=c.potencia, especial=c.especial, conexion=c.conexion)
            for c in cargas.filas
        ],
        tablas=[
            TablaOut(
                id=t.id, version=t.version, estado=t.estado, fuente=t.fuente.norma, nota=t.nota
            )
            for t in sorted(perfil.tablas.values(), key=lambda t: t.id)
        ],
    )


def _pendientes_del_borrador(borrador: Borrador) -> list[Pendiente]:
    pendientes = []
    if borrador.area_construida_m2 is None:
        pendientes.append(Pendiente(codigo="falta_area", mensaje="Falta el área construida."))
    if borrador.tablero is None:
        pendientes.append(
            Pendiente(
                codigo="falta_tablero", mensaje="Falta la longitud del alimentador al tablero."
            )
        )
    if not borrador.circuitos:
        pendientes.append(
            Pendiente(codigo="sin_circuitos", mensaje="El proyecto no tiene circuitos.")
        )
    return pendientes


def _mensajes(error: ValidationError) -> list[Pendiente]:
    pendientes = []
    for e in error.errors():
        mensaje = str(e["msg"]).removeprefix("Value error, ")
        campo = ".".join(str(p) for p in e["loc"])
        texto = f"{campo}: {mensaje}" if campo else mensaje
        pendientes.append(Pendiente(codigo="proyecto_incoherente", mensaje=texto))
    return pendientes


def _valores(datos: dict[str, Decimal | str], perfil: Perfil) -> list[ValorOut]:
    return [ValorOut(clave=k, texto=presentar(v, "", perfil)) for k, v in datos.items()]


def _resultado(r: Resultado, perfil: Perfil) -> ResultadoOut:
    return ResultadoOut(
        id=r.id,
        sujeto=r.sujeto,
        nombre=r.nombre,
        texto=presentar(r.valor, r.unidad, perfil),
        unidad=r.unidad,
        formula=r.formula,
        entradas=_valores(dict(r.entradas), perfil),
        detalle=_valores(dict(r.detalle), perfil),
        tablas=list(r.tablas),
        supuestos=list(r.supuestos),
        avisos=list(r.avisos),
        estado=r.estado,
    )


def _listo(calculado: Calculado, perfil: Perfil, revision: int) -> Calculos:
    return Calculos(
        estado="listo",
        revision=revision,
        aviso=AVISO_BORRADOR,
        huella=calculado.hash,
        resumen=[
            DatoResumenOut(**asdict(d), estado=calculado.res(d.id, d.sujeto).estado)
            for d in resumen(calculado, perfil)
        ],
        cuadro=[FilaCuadroOut(**asdict(f)) for f in cuadro_de_cargas(calculado, perfil)],
        resultados=[_resultado(r, perfil) for r in calculado.resultados],
        avisos=[f"{r.id} {r.sujeto}: {a}" for r in calculado.resultados for a in r.avisos],
        supuestos=sorted({s for r in calculado.resultados for s in r.supuestos}),
        tablas_sin_verificar=[
            TablaPendiente(id=i, version=v, estado=e) for i, v, e in tablas_sin_verificar(calculado)
        ],
    )


def calcular_borrador(id: str, revision: int, borrador: Borrador, perfiles: Perfiles) -> Calculos:
    """Calcula el borrador, o dice qué falta para poder calcularlo.

    Un borrador incompleto no es un error: es el estado normal mientras se
    edita. La plataforma pregunta; nunca completa en silencio (RNF-13).
    """

    def incompleto(pendientes: list[Pendiente]) -> Calculos:
        return Calculos(
            estado="incompleto", revision=revision, aviso=AVISO_BORRADOR, pendientes=pendientes
        )

    perfil = perfiles.buscar(borrador.perfil.id, borrador.perfil.version)
    if perfil is None:
        return incompleto(
            [
                Pendiente(
                    codigo="perfil_no_disponible",
                    mensaje=f"El perfil {borrador.perfil.id} {borrador.perfil.version} "
                    "no está disponible.",
                )
            ]
        )
    pendientes = _pendientes_del_borrador(borrador)
    if pendientes:
        return incompleto(pendientes)
    try:
        proyecto = Proyecto.model_validate({"id": id, **borrador.model_dump()})
    except ValidationError as error:
        return incompleto(_mensajes(error))
    try:
        calculado = calcular(proyecto, perfil)
    except ErrorElectric as error:
        return incompleto([Pendiente(codigo=error.codigo, mensaje=str(error))])
    return _listo(calculado, perfil, revision)
