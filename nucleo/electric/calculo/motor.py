"""Motor de cálculo: ejecuta el grafo de cálculos sobre un proyecto y un perfil."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Context, localcontext

from electric.calculo import rc  # noqa: F401  (registra los cálculos)
from electric.calculo.contexto import Contexto
from electric.calculo.registro import orden_topologico, registrados
from electric.calculo.resultado import Resultado
from electric.errores import DatoInvalido
from electric.modelo.entidades import Proyecto
from electric.modelo.serializacion import hash_canonico
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import peor_estado

#: Precisión fija de toda la aritmética; el redondeo se aplica solo al presentar.
PRECISION = 28


@dataclass(frozen=True)
class Calculado:
    proyecto: Proyecto
    perfil_id: str
    perfil_version: str
    resultados: tuple[Resultado, ...]

    def res(self, id: str, sujeto: str) -> Resultado:
        for resultado in self.resultados:
            if resultado.id == id and resultado.sujeto == sujeto:
                return resultado
        raise KeyError((id, sujeto))

    def de(self, id: str) -> tuple[Resultado, ...]:
        return tuple(r for r in self.resultados if r.id == id)

    @property
    def hash(self) -> str:
        """Huella del modelo y de sus resultados; igual entrada, igual huella (RNF-01)."""
        return hash_canonico(
            {
                "proyecto": self.proyecto,
                "perfil": {"id": self.perfil_id, "version": self.perfil_version},
                "resultados": list(self.resultados),
            }
        )


def calcular(proyecto: Proyecto, perfil: Perfil) -> Calculado:
    """Ejecuta todos los cálculos en orden de dependencias.

    Es una función pura: no usa reloj, red, archivos ni aleatoriedad.
    """
    if (proyecto.perfil.id, proyecto.perfil.version) != (perfil.meta.id, perfil.meta.version):
        raise DatoInvalido(
            f"el proyecto pide el perfil {proyecto.perfil.id} {proyecto.perfil.version} "
            f"y se cargó {perfil.meta.id} {perfil.meta.version}"
        )
    ctx = Contexto(proyecto, perfil)
    with localcontext(Context(prec=PRECISION, rounding=ROUND_HALF_EVEN)):
        for calculo in orden_topologico(registrados()):
            previos = [r.estado for dep in calculo.depende for r in ctx.de(dep)]
            for resultado in calculo.funcion(ctx):
                estado = peor_estado([resultado.estado, *previos])
                ctx.guardar(replace(resultado, estado=estado))
    return Calculado(
        proyecto=proyecto,
        perfil_id=perfil.meta.id,
        perfil_version=perfil.meta.version,
        resultados=ctx.todos(),
    )
