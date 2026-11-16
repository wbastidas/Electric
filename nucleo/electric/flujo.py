"""Flujo de punta a punta: del plano del arquitecto al proyecto diseñado y calculado."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from electric.calculo import Calculado, calcular
from electric.diseno import disenar
from electric.ingesta import leer_dxf
from electric.interpretacion import interpretar
from electric.modelo.entidades import CargaEspecial, Preferencias, Proyecto, RefPerfil, Tablero
from electric.perfiles.carga import Perfil


@dataclass(frozen=True)
class Resultado:
    proyecto: Proyecto
    calculado: Calculado
    #: Dudas de la lectura del plano y decisiones del diseño que conviene revisar.
    avisos: tuple[str, ...]


def proyecto_desde_plano(
    contenido: bytes,
    archivo: str,
    perfil: Perfil,
    *,
    id: str,
    nombre: str,
    equipos: tuple[str, ...] = (),
    alimentador_m: Decimal,
    factor_a_metros: float | None = None,
    preferencias: Preferencias | None = None,
) -> Resultado:
    """Lee el plano, detecta ambientes, diseña la instalación y la calcula.

    `equipos` son las cargas especiales declaradas (ducha, cocina…) y
    `alimentador_m` la longitud del medidor al tablero: ninguna de las dos se
    puede deducir del plano.
    """
    plano = interpretar(leer_dxf(contenido, archivo, factor_a_metros=factor_a_metros), perfil)
    cargas = tuple(
        CargaEspecial(id=f"declarada-{n}", tipo=tipo, circuito="-")
        for n, tipo in enumerate(equipos, start=1)
    )
    preferencias = preferencias or Preferencias()
    diseno = disenar(plano, cargas, perfil, preferencias)
    proyecto = Proyecto(
        id=id,
        nombre=nombre,
        area_construida_m2=plano.area_construida_m2,
        perfil=RefPerfil(id=perfil.meta.id, version=perfil.meta.version),
        puntos=diseno.puntos,
        cargas_especiales=diseno.cargas_especiales,
        circuitos=diseno.circuitos,
        tablero=Tablero(id="TD-1", alimentador_longitud_m=alimentador_m),
        plano=diseno.plano,
        preferencias=preferencias,
    )
    dudas = [f"{a.id} {a.nombre}: {b}" for a in plano.ambientes for b in a.banderas]
    return Resultado(
        proyecto=proyecto,
        calculado=calcular(proyecto, perfil),
        avisos=(*plano.banderas, *dudas, *diseno.avisos),
    )
