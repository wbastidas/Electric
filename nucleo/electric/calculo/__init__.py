"""Motor de cálculo determinista (sección 5 del documento de requerimientos)."""

from electric.calculo.motor import Calculado, calcular
from electric.calculo.resultado import ALIMENTADOR, PROYECTO, Resultado, presentar

__all__ = ["ALIMENTADOR", "PROYECTO", "Calculado", "Resultado", "calcular", "presentar"]
