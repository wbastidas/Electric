"""Vistas de presentación de un cálculo: resumen y cuadro de cargas.

Las usan la línea de comandos y la API, para que ambas muestren lo mismo.
"""

from __future__ import annotations

from dataclasses import dataclass

from electric.calculo.motor import Calculado
from electric.calculo.resultado import ALIMENTADOR, PROYECTO, presentar
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import Estado


@dataclass(frozen=True)
class DatoResumen:
    etiqueta: str
    texto: str
    #: Resultado del que sale el dato, para abrir su detalle.
    id: str
    sujeto: str


@dataclass(frozen=True)
class FilaCuadro:
    circuito: str
    tipo: str
    fase: str
    carga: str
    corriente: str
    breaker: str
    conductor: str
    tierra: str
    ducto: str
    longitud: str
    caida: str


def _texto(calculado: Calculado, perfil: Perfil, id: str, sujeto: str) -> str:
    resultado = calculado.res(id, sujeto)
    return presentar(resultado.valor, resultado.unidad, perfil)


def texto_breaker(calculado: Calculado, sujeto: str) -> str:
    resultado = calculado.res("RC-09", sujeto)
    return f"{resultado.det('polos'):f}P {resultado.decimal.normalize():f} A"


def resumen(calculado: Calculado, perfil: Perfil) -> list[DatoResumen]:
    tablero = calculado.proyecto.tablero.id

    def dato(etiqueta: str, id: str, sujeto: str, texto: str | None = None) -> DatoResumen:
        return DatoResumen(etiqueta, texto or _texto(calculado, perfil, id, sujeto), id, sujeto)

    return [
        dato("Carga instalada", "RC-01", PROYECTO),
        dato("Demanda máxima", "RC-03", PROYECTO),
        dato("Clasificación CNEL", "RC-05", PROYECTO),
        dato("Circuitos mínimos", "RC-02", PROYECTO),
        dato("Desbalance de fases", "RC-10", PROYECTO),
        dato(
            "Tablero", "RC-11", tablero, f"{tablero}, {_texto(calculado, perfil, 'RC-11', tablero)}"
        ),
        dato("Breaker principal", "RC-09", ALIMENTADOR, texto_breaker(calculado, ALIMENTADOR)),
        dato("Medidor", "RC-12", PROYECTO),
        dato(
            "Puesta a tierra",
            "RC-14",
            PROYECTO,
            f"resistencia menor que {_texto(calculado, perfil, 'RC-14', PROYECTO)}",
        ),
    ]


def cuadro_de_cargas(calculado: Calculado, perfil: Perfil) -> list[FilaCuadro]:
    """Una fila por circuito y, al final, la del alimentador."""
    proyecto = calculado.proyecto

    def v(id: str, sujeto: str) -> str:
        return _texto(calculado, perfil, id, sujeto)

    filas = []
    for circuito in proyecto.circuitos:
        filas.append(
            FilaCuadro(
                circuito=circuito.id,
                tipo=circuito.tipo,
                fase=v("RC-10", circuito.id),
                carga=v("RC-01", circuito.id),
                corriente=v("RC-06", circuito.id),
                breaker=texto_breaker(calculado, circuito.id),
                conductor=v("RC-07", circuito.id),
                tierra=v("RC-14", circuito.id),
                ducto=v("RC-13", circuito.id),
                longitud=presentar(circuito.longitud_m, "m", perfil),
                caida=v("RC-08", circuito.id),
            )
        )
    filas.append(
        FilaCuadro(
            circuito=ALIMENTADOR,
            tipo="alimentador",
            fase="",
            carga=v("RC-03", PROYECTO),
            corriente=v("RC-06", ALIMENTADOR),
            breaker=texto_breaker(calculado, ALIMENTADOR),
            conductor=v("RC-07", ALIMENTADOR),
            tierra=v("RC-14", ALIMENTADOR),
            ducto=v("RC-13", ALIMENTADOR),
            longitud=presentar(proyecto.tablero.alimentador_longitud_m, "m", perfil),
            caida=v("RC-08", ALIMENTADOR),
        )
    )
    return filas


def tablas_sin_verificar(calculado: Calculado) -> list[tuple[str, str, Estado]]:
    """Tablas usadas que no están verificadas: (id, versión, estado)."""
    return sorted(
        {
            (t.id, t.version, t.estado)
            for r in calculado.resultados
            for t in r.tablas
            if t.estado != "verificado"
        }
    )
