"""Coordinación de protecciones de una industria.

Compara las curvas tiempo-corriente de las protecciones en serie, todas
referidas a la baja tensión:

- Fusible tipo K del primario del transformador particular.
- Breaker principal.
- Breaker de cada alimentador.
- El mayor breaker de máquina de cada tablero.

Las curvas son genéricas y están en el perfil como por verificar: breaker
termomagnético con banda térmica t = A ÷ ((I/In)² − 1) y disparo instantáneo
a k × In; fusible K como recta en escala logarítmica entre 2 × In a 300 s y
14 × In a 0,1 s (relación de velocidad 7). Sirven para detectar problemas de
selectividad, no para sustituir las curvas del fabricante.

Para cada par se busca hasta qué corriente la protección de arriba no actúa
antes que la de abajo. Si eso cubre el cortocircuito del punto, el par es
selectivo; si no, la selectividad es parcial. También se comprueba que el
fusible soporte la energización del transformador y lo proteja de una falla
en sus bornes de baja tensión (curva de daño ANSI C57.109 simplificada).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from electric.calculo.resultado import Rastro, Resultado
from electric.errores import FilaNoEncontrada
from electric.industrial.analisis import AnalisisIndustrial, Comprobacion, _t
from electric.industrial.estudios import PRINCIPAL, Estudios
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import Estado, peor_estado

RAIZ3 = math.sqrt(3)


def _f(valor: float, decimales: int) -> str:
    return f"{valor:.{decimales}f}".replace(".", ",")


T_MAX = 1000.0
T_INSTANTANEO = (0.01, 0.025)


@dataclass(frozen=True)
class Curva:
    """Banda tiempo-corriente de una protección, con corrientes en baja tensión."""

    nombre: str
    tipo: Literal["breaker", "fusible"]
    #: Corriente nominal en baja tensión (la del fusible, referida).
    nominal_a: float
    #: Disparo instantáneo del breaker, en A.
    instantaneo_a: float = 0.0
    termico_min: float = 150.0
    termico_max: float = 525.0

    def tiempos(self, corriente: float) -> tuple[float, float] | None:
        """Tiempo mínimo y máximo de actuación, o None si no actúa."""
        m = corriente / self.nominal_a
        if self.tipo == "fusible":
            if m <= 2.0:
                return None
            exponente = math.log(3000.0) / math.log(7.0)
            fusion = max(300.0 * (m / 2.0) ** (-exponente), 0.008)
            if fusion > T_MAX:
                return None
            return fusion, fusion * 1.2 + 0.01
        if corriente >= self.instantaneo_a:
            return T_INSTANTANEO
        if m <= 1.05:
            return None
        minimo = self.termico_min / (m * m - 1)
        maximo = self.termico_max / (m * m - 1)
        if minimo > T_MAX:
            return None
        return minimo, min(maximo, T_MAX)


@dataclass(frozen=True)
class Par:
    aguas_arriba: str
    aguas_abajo: str
    punto: str
    ik_ka: Decimal
    #: Corriente hasta la que hay selectividad, en kA.
    hasta_ka: Decimal
    selectivo: bool
    relacion: Decimal
    detalle: str


@dataclass(frozen=True)
class Coordinacion:
    fusible_a: Decimal | None
    curvas: tuple[Curva, ...]
    pares: tuple[Par, ...]
    transformador: tuple[Comprobacion, ...]
    #: Puntos de la curva de daño del transformador (A, s), en baja tensión.
    dano: tuple[tuple[float, float], ...]
    energizacion: tuple[float, float] | None
    corrientes_falla: dict[str, float]
    resultados: tuple[Resultado, ...]
    avisos: tuple[str, ...]
    estado: Estado


def _sin_selectividad(
    arriba: Curva, abajo: Curva, desde: float, hasta: float, margen: float
) -> tuple[float, float] | None:
    """Primer tramo de corrientes en que la protección de arriba puede actuar antes."""
    pasos = 300
    inicio: float | None = None
    anterior = desde
    for n in range(pasos + 1):
        corriente = desde * (hasta / desde) ** (n / pasos)
        t_abajo = abajo.tiempos(corriente)
        t_arriba = arriba.tiempos(corriente)
        choca = (
            t_abajo is not None
            and t_arriba is not None
            and (
                t_arriba[0] * margen < t_abajo[1]
                or (arriba.tipo == "breaker" and t_arriba == T_INSTANTANEO)
            )
        )
        if choca and inicio is None:
            inicio = anterior
        elif not choca and inicio is not None:
            return inicio, corriente
        anterior = corriente
    return (inicio, hasta) if inicio is not None else None


def _selectivo_hasta(
    arriba: Curva, abajo: Curva, desde: float, hasta: float, margen: float
) -> float:
    """Mayor corriente (desde la nominal de abajo) en que arriba actúa después de abajo."""
    tramo = _sin_selectividad(arriba, abajo, desde, hasta, margen)
    return hasta if tramo is None else tramo[0]


def coordinar(analisis: AnalisisIndustrial, estudios: Estudios, perfil: Perfil) -> Coordinacion:
    rastro = Rastro()
    avisos: list[str] = []
    resultados: list[Resultado] = []

    def p(clave: str) -> float:
        return float(rastro.usar(perfil.parametro(clave)))

    k_inst = p("disparo_magnetico_veces")
    a_min = p("termico_constante_min")
    a_max = p("termico_constante_max")
    margen_fusible = p("margen_fusible_breaker")
    relacion_min = p("relacion_selectividad_termica")

    def breaker(nombre: str, nominal: Decimal) -> Curva:
        n = float(nominal)
        return Curva(nombre, "breaker", n, n * k_inst, a_min, a_max)

    falla = {c.punto: float(c.ik_ka) * 1000 for c in estudios.cortocircuito}
    v_bt = float(analisis.sistema.v_linea)
    decision = analisis.decision
    curvas: list[Curva] = []
    pares: list[Par] = []
    comprobaciones: list[Comprobacion] = []
    dano: tuple[tuple[float, float], ...] = ()
    energizacion: tuple[float, float] | None = None
    fusible_a: Decimal | None = None

    principal_valor = analisis.resultado("breaker_principal").valor
    principal = (
        breaker("Breaker principal", principal_valor)
        if isinstance(principal_valor, Decimal)
        else None
    )

    # Fusible del transformador particular y su relación con el transformador.
    fusible: Curva | None = None
    trafo = decision.transformador if decision.opcion != "existente" else None
    if trafo is not None and analisis.sistema.fases == 3:
        kv = float(estudios.tension_media_kv)
        kva = float(trafo.kva)
        i_primaria = kva / (RAIZ3 * kv)
        i_secundaria = kva * 1000 / (RAIZ3 * v_bt)
        relacion = kv * 1000 / v_bt
        try:
            fusible_a = rastro.usar(
                perfil.normalizado("fusibles_mt", Decimal(str(i_primaria * p("factor_fusible_mt"))))
            )
        except FilaNoEncontrada:
            avisos.append("La corriente primaria supera la serie de fusibles; use un reconectador.")
        if fusible_a is not None:
            fusible = Curva(
                f"Fusible {fusible_a}K ({_t(trafo.kva, 1)} kVA)",
                "fusible",
                float(fusible_a) * relacion,
            )
            curvas.append(fusible)
            veces = p("corriente_magnetizacion_veces")
            energizacion = (veces * i_secundaria, 0.1)
            tiempos = fusible.tiempos(energizacion[0])
            soporta = tiempos is None or tiempos[0] > 0.1
            comprobaciones.append(
                Comprobacion(
                    "Energización",
                    soporta,
                    f"El fusible {fusible_a}K debe soportar {_t(Decimal(veces), 0)} × In del "
                    f"transformador durante 0,1 s"
                    + (
                        "."
                        if soporta
                        else f"; se fundiría en {_f(tiempos[0] if tiempos else 0, 3)} s."
                    ),
                )
            )
            z = float(trafo.z_pct) / 100
            falla_bornes = i_secundaria / z
            dano_bornes = 1250 * z * z
            puntos = []
            m = 2.0
            while m <= 1 / z:
                puntos.append((m * i_secundaria, 1250 / (m * m)))
                m *= 1.15
            puntos.append((falla_bornes, dano_bornes))
            dano = tuple(puntos)
            t_fusible = fusible.tiempos(falla_bornes)
            protege = t_fusible is not None and t_fusible[1] < dano_bornes
            comprobaciones.append(
                Comprobacion(
                    "Daño del transformador",
                    protege,
                    f"Con una falla en bornes de baja ({_f(falla_bornes / 1000, 2)} "
                    f"kA) el fusible debe despejar antes de "
                    f"{_f(dano_bornes, 2)} s"
                    + (
                        f"; despeja en {_f(t_fusible[1], 2)} s."
                        if t_fusible is not None
                        else "; no actúa."
                    ),
                )
            )
            resultados.append(
                Resultado(
                    id="fusible_mt",
                    sujeto="industria",
                    nombre="Fusible del transformador",
                    valor=f"{fusible_a}K",
                    unidad="",
                    formula="In primaria = kVA ÷ (√3 × kV) × factor; normalizado superior",
                    entradas={
                        "corriente_primaria_a": Decimal(str(round(i_primaria, 2))),
                        "tension_kv": estudios.tension_media_kv,
                    },
                    tablas=rastro.tablas,
                    avisos=tuple(c.detalle for c in comprobaciones if not c.cumple),
                    estado=rastro.estado,
                )
            )
    elif decision.opcion == "existente":
        avisos.append(
            "La protección de media tensión es la del transformador existente de CNEL; "
            "su coordinación la verifica la distribuidora."
        )

    def comparar(arriba: Curva, abajo: Curva, punto: str) -> None:
        ik = falla.get(punto)
        if ik is None:
            return
        margen = margen_fusible if arriba.tipo == "fusible" else 1.0
        tramo = _sin_selectividad(arriba, abajo, abajo.nominal_a * 1.06, ik, margen)
        hasta = ik if tramo is None else tramo[0]
        selectivo = tramo is None
        relacion = arriba.nominal_a / abajo.nominal_a
        if tramo is None:
            detalle = f"Selectivo hasta la falla máxima de {punto} ({_f(ik / 1000, 2)} kA)."
        elif tramo[1] >= ik * 0.999:
            detalle = (
                f"Selectivo solo hasta {_f(tramo[0] / 1000, 2)} kA de los {_f(ik / 1000, 2)} kA "
                f"de {punto}: sobre ese valor pueden actuar los dos."
            )
        else:
            detalle = (
                f"Las curvas se cruzan entre {_f(tramo[0] / 1000, 2)} y "
                f"{_f(tramo[1] / 1000, 2)} kA: en ese tramo pueden actuar los dos."
            )
        if not selectivo:
            detalle += (
                " Pruebe un fusible de mayor capacidad o uno más lento."
                if arriba.tipo == "fusible"
                else " Use breakers con disparo regulable o verifique la selectividad en las "
                "tablas del fabricante."
            )
        if arriba.tipo == "breaker" and relacion < relacion_min:
            detalle += (
                f" La relación de corrientes nominales es {_f(relacion, 2)}, menor "
                f"que {_f(relacion_min, 1)}."
            )
            selectivo = False
        pares.append(
            Par(
                aguas_arriba=arriba.nombre,
                aguas_abajo=abajo.nombre,
                punto=punto,
                ik_ka=Decimal(str(round(ik / 1000, 2))),
                hasta_ka=Decimal(str(round(hasta / 1000, 2))),
                selectivo=selectivo,
                relacion=Decimal(str(round(relacion, 2))),
                detalle=detalle,
            )
        )

    if principal is not None:
        curvas.append(principal)
        if fusible is not None:
            comparar(fusible, principal, PRINCIPAL)
        for alimentador in estudios.alimentadores:
            if alimentador.breaker_a is None:
                continue
            curva = breaker(f"Alimentador {alimentador.tablero}", alimentador.breaker_a)
            curvas.append(curva)
            comparar(principal, curva, alimentador.tablero)
            maquinas = [
                c
                for c in estudios.circuitos
                if c.tablero == alimentador.tablero and c.breaker_a is not None
            ]
            if maquinas:
                mayor = max(maquinas, key=lambda c: c.breaker_a or Decimal(0))
                assert mayor.breaker_a is not None
                curva_m = breaker(f"Máquina {mayor.maquina}", mayor.breaker_a)
                curvas.append(curva_m)
                comparar(curva, curva_m, alimentador.tablero)

    no_selectivos = [x for x in pares if not x.selectivo]
    for x in no_selectivos:
        avisos.append(f"{x.aguas_arriba} / {x.aguas_abajo}: {x.detalle}")
    for c in comprobaciones:
        if not c.cumple:
            avisos.append(f"{c.nombre}: {c.detalle}")
    resultados.append(
        Resultado(
            id="coordinacion",
            sujeto="industria",
            nombre="Coordinación de protecciones",
            valor=f"{len(pares) - len(no_selectivos)} de {len(pares)} pares selectivos",
            unidad="",
            formula="Arriba actúa después que abajo en toda la banda hasta la falla del punto; "
            "fusible con margen sobre el breaker",
            tablas=rastro.tablas,
            supuestos=("curvas genéricas de breakers y fusibles K; usar las del fabricante",),
            avisos=tuple(avisos),
            estado=rastro.estado,
        )
    )
    return Coordinacion(
        fusible_a=fusible_a,
        curvas=tuple(curvas),
        pares=tuple(pares),
        transformador=tuple(comprobaciones),
        dano=dano,
        energizacion=energizacion,
        corrientes_falla=falla,
        resultados=tuple(resultados),
        avisos=tuple(avisos),
        estado=peor_estado([r.estado for r in resultados]),
    )


def grafico(coordinacion: Coordinacion, titulo: str) -> bytes:
    """Curvas tiempo-corriente en escala logarítmica, en PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figura, ejes = plt.subplots(figsize=(9, 7.5))
    try:
        todas = [c.nominal_a for c in coordinacion.curvas] or [10.0]
        x_min = min(todas) * 0.8
        x_max = max([*coordinacion.corrientes_falla.values(), max(todas) * 30]) * 1.5
        colores = [
            "#6a3d9a", "#1f78b4", "#33a02c", "#ff7f00", "#e31a1c",
            "#b15928", "#a6cee3", "#fb9a99", "#cab2d6", "#b2df8a",
        ]  # fmt: skip
        for n, curva in enumerate(coordinacion.curvas):
            xs, mins, maxs = [], [], []
            pasos = 300
            for k in range(pasos + 1):
                corriente = x_min * (x_max / x_min) ** (k / pasos)
                t = curva.tiempos(corriente)
                if t is None:
                    continue
                xs.append(corriente)
                mins.append(t[0])
                maxs.append(t[1])
            color = colores[n % len(colores)]
            ejes.fill_between(xs, mins, maxs, color=color, alpha=0.25)
            ejes.plot(xs, maxs, color=color, linewidth=1.4, label=curva.nombre)
        if coordinacion.dano:
            xs = [d[0] for d in coordinacion.dano]
            ts = [d[1] for d in coordinacion.dano]
            ejes.plot(xs, ts, color="#b2182b", linestyle="--", label="Daño del transformador")
        if coordinacion.energizacion:
            xe, te = coordinacion.energizacion
            ejes.plot([xe], [te], marker="x", color="#b2182b", markersize=9, linestyle="none",
                      label="Energización")  # fmt: skip
        for punto, ik in coordinacion.corrientes_falla.items():
            ejes.axvline(ik, color="#555555", linewidth=0.8, linestyle=":")
            ejes.text(ik, 0.012, f" Ik {punto}", rotation=90, fontsize=7, color="#555555",
                      va="bottom")  # fmt: skip
        ejes.set_xscale("log")
        ejes.set_yscale("log")
        ejes.set_xlim(x_min, x_max)
        ejes.set_ylim(0.01, T_MAX)
        ejes.set_xlabel("Corriente en baja tensión (A)")
        ejes.set_ylabel("Tiempo (s)")
        ejes.set_title(titulo, fontsize=11)
        ejes.grid(True, which="both", linewidth=0.3, alpha=0.6)
        ejes.legend(fontsize=7, loc="upper right")
        figura.text(
            0.01,
            0.005,
            "Curvas genéricas por verificar; reemplazar por las del fabricante. BORRADOR.",
            fontsize=7,
            color="#555555",
        )
        salida = io.BytesIO()
        figura.savefig(salida, format="png", dpi=120, metadata={"Software": None})
        return salida.getvalue()
    finally:
        plt.close(figura)
