"""Contexto de un cálculo: el proyecto, el perfil y los resultados previos."""

from __future__ import annotations

from decimal import Decimal

from electric.calculo.resultado import Rastro, Resultado
from electric.modelo.entidades import Proyecto, Supuesto
from electric.perfiles.carga import Perfil


class Contexto:
    def __init__(self, proyecto: Proyecto, perfil: Perfil) -> None:
        self.proyecto = proyecto
        self.perfil = perfil
        self._resultados: dict[tuple[str, str], Resultado] = {}

    def guardar(self, resultado: Resultado) -> None:
        clave = (resultado.id, resultado.sujeto)
        if clave in self._resultados:
            raise ValueError(f"resultado repetido: {clave}")
        self._resultados[clave] = resultado

    def res(self, id: str, sujeto: str) -> Resultado:
        return self._resultados[(id, sujeto)]

    def de(self, id: str) -> list[Resultado]:
        return [r for (i, _), r in self._resultados.items() if i == id]

    def todos(self) -> tuple[Resultado, ...]:
        return tuple(self._resultados.values())

    def supuesto(self, parametro: str) -> Supuesto | None:
        for supuesto in self.proyecto.supuestos:
            if supuesto.parametro == parametro:
                return supuesto
        return None

    def parametro(self, clave: str, rastro: Rastro) -> Decimal:
        """Parámetro del perfil, o su sobrescritura si el proyecto la declara."""
        supuesto = self.supuesto(clave)
        if supuesto is not None:
            rastro.supuesto(texto_supuesto(supuesto))
            return supuesto.valor
        return rastro.usar(self.perfil.parametro(clave))


def texto_supuesto(supuesto: Supuesto) -> str:
    return (
        f"{supuesto.parametro} = {supuesto.valor} "
        f"({supuesto.justificacion}; {supuesto.autor}, {supuesto.fecha})"
    )
