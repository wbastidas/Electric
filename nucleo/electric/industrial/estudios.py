"""Alimentadores, circuitos de máquinas y cortocircuito de una industria.

Parte del análisis (demanda, transformador y decisión) y agrega:

1. El alimentador de cada tablero de distribución desde el tablero principal:
   breaker, conductor (con paralelos) y caída de tensión.
2. El circuito de cada máquina: breaker y conductor. En motores el conductor
   va al 125 % de la corriente y el breaker puede llegar al factor del perfil
   (NEC 430.52); en las demás cargas el conductor cubre el breaker.
3. Cortocircuito trifásico en el tablero principal y en cada tablero, por el
   método de impedancias (IEC 60909 simplificado): red de CNEL, transformador
   (particular o existente), acometida y alimentador, más el aporte de los
   motores. Con la corriente se elige la capacidad de interrupción de los
   breakers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from electric.calculo.resultado import Rastro, Resultado, redondear
from electric.errores import FilaNoEncontrada
from electric.industrial.analisis import (
    INDUSTRIA,
    AnalisisIndustrial,
    FilaCuadro,
    TotalTablero,
    _t,
)
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import Estado, FilaConductor, peor_estado

CERO = Decimal(0)
UNO = Decimal(1)
CIEN = Decimal(100)
MIL = Decimal(1000)
RAIZ3 = Decimal(3).sqrt()

#: Sujeto del tablero principal.
PRINCIPAL = "TP"


@dataclass(frozen=True)
class Conductor:
    calibre: str
    paralelos: int
    caida_pct: Decimal
    longitud_m: Decimal
    r_ohm: Decimal
    x_ohm: Decimal

    @property
    def texto(self) -> str:
        return f"{self.paralelos} × {self.calibre}" if self.paralelos > 1 else self.calibre


@dataclass(frozen=True)
class Alimentador:
    tablero: str
    corriente_a: Decimal
    breaker_a: Decimal | None
    conductor: Conductor | None
    distancia_supuesta: bool


@dataclass(frozen=True)
class CircuitoMaquina:
    maquina: str
    tablero: str
    descripcion: str
    corriente_a: Decimal
    breaker_a: Decimal | None
    conductor: Conductor | None
    polos: int


@dataclass(frozen=True)
class PuntoCortocircuito:
    punto: str
    ik_ka: Decimal
    ip_ka: Decimal
    xr: Decimal
    capacidad_ka: Decimal | None


@dataclass(frozen=True)
class Estudios:
    alimentadores: tuple[Alimentador, ...]
    circuitos: tuple[CircuitoMaquina, ...]
    cortocircuito: tuple[PuntoCortocircuito, ...]
    #: Descripción de la fuente usada en el cortocircuito.
    fuente: str
    tension_media_kv: Decimal
    scc_red_mva: Decimal
    resultados: tuple[Resultado, ...]
    avisos: tuple[str, ...]
    estado: Estado

    def punto(self, nombre: str) -> PuntoCortocircuito:
        return next(p for p in self.cortocircuito if p.punto == nombre)


def elegir_conductor(
    perfil: Perfil,
    corriente: Decimal,
    ampacidad_min: Decimal,
    longitud: Decimal,
    fp: Decimal,
    limite: Decimal,
    uso: str,
    trifasico: bool,
    tension: Decimal,
    rastro: Rastro,
    k: Decimal | None = None,
) -> Conductor | None:
    """Menor conductor, con paralelos, que cumple ampacidad y caída de tensión.

    `k` es el factor de la caída (√3 trifásico, 2 monofásico) si no sale de `trifasico`.
    """
    filas, tabla = perfil.conductores()
    paralelos = int(rastro.usar(perfil.parametro("conductores_paralelo_max")))
    minimo = rastro.usar(perfil.minimo_calibre(uso)).calibre
    desde = next(n for n, f in enumerate(filas) if f.calibre == minimo)
    seno = (UNO - fp * fp).sqrt()
    k = k if k is not None else (RAIZ3 if trifasico else Decimal(2))
    for n in range(1, paralelos + 1):
        # Los paralelos solo desde 1/0 AWG, como pide la práctica habitual.
        candidatas: list[FilaConductor] = [
            f for f in filas[desde:] if n == 1 or f.seccion_mm2 >= Decimal("53.5")
        ]
        for fila in candidatas:
            if fila.ampacidad * n < ampacidad_min:
                continue
            z = fila.r_ohm_km * fp + fila.x_ohm_km * seno
            caida = k * corriente * longitud / MIL * z / n / tension * CIEN
            if caida <= limite:
                rastro.anotar(perfil._ref(tabla, fila.calibre))
                return Conductor(
                    calibre=fila.calibre,
                    paralelos=n,
                    caida_pct=caida,
                    longitud_m=longitud,
                    r_ohm=fila.r_ohm_km * longitud / MIL / n,
                    x_ohm=fila.x_ohm_km * longitud / MIL / n,
                )
    return None


class _Estudio:
    def __init__(self, analisis: AnalisisIndustrial, perfil: Perfil) -> None:
        self.analisis = analisis
        self.perfil = perfil
        self.sistema = analisis.sistema
        self.trifasico = self.sistema.fases == 3
        self.v = self.sistema.v_linea
        self.resultados: list[Resultado] = []
        self.avisos: list[str] = []

    def p(self, clave: str, rastro: Rastro) -> Decimal:
        return rastro.usar(self.perfil.parametro(clave))

    def breaker(self, minimo: Decimal, rastro: Rastro) -> Decimal | None:
        try:
            return rastro.usar(self.perfil.normalizado("breakers", minimo))
        except FilaNoEncontrada:
            return None

    def conductor(
        self,
        corriente: Decimal,
        ampacidad_min: Decimal,
        longitud: Decimal,
        fp: Decimal,
        limite: Decimal,
        uso: str,
        trifasico: bool,
        tension: Decimal,
        rastro: Rastro,
    ) -> Conductor | None:
        return elegir_conductor(
            self.perfil, corriente, ampacidad_min, longitud, fp, limite, uso, trifasico,
            tension, rastro,
        )  # fmt: skip

    def agregar(self, resultado: Resultado) -> None:
        self.resultados.append(resultado)


def _resultado(
    id: str,
    sujeto: str,
    nombre: str,
    valor: Decimal | str,
    unidad: str,
    formula: str,
    rastro: Rastro,
    entradas: dict[str, Decimal | str] | None = None,
    detalle: dict[str, Decimal | str] | None = None,
    avisos: tuple[str, ...] = (),
) -> Resultado:
    return Resultado(
        id=id,
        sujeto=sujeto,
        nombre=nombre,
        valor=valor,
        unidad=unidad,
        formula=formula,
        entradas=entradas or {},
        detalle=detalle or {},
        tablas=rastro.tablas,
        supuestos=rastro.supuestos,
        avisos=avisos,
        estado=rastro.estado,
    )


# --- 1. Alimentadores ------------------------------------------------------------


def _alimentadores(e: _Estudio) -> list[Alimentador]:
    industria = e.analisis.industria
    salida = []
    for tablero in e.analisis.tableros:
        rastro = Rastro()
        supuesta = tablero.tablero not in industria.distancias_m
        if supuesta:
            longitud = e.p("distancia_tablero_defecto_m", rastro)
            rastro.supuesto(f"distancia de {tablero.tablero} al tablero principal: {longitud} m")
        else:
            longitud = industria.distancias_m[tablero.tablero]
        limite = e.p("caida_total_max_pct", rastro) - e.p("caida_ramal_max_pct", rastro)
        factor = e.p("factor_diseno_conductor", rastro)
        breaker = e.breaker(tablero.corriente_a * factor, rastro)
        minimo = max(tablero.corriente_a * factor, breaker or CERO)
        conductor = e.conductor(
            tablero.corriente_a,
            minimo,
            longitud,
            tablero.fp,
            limite,
            "alimentador",
            e.trifasico,
            e.v,
            rastro,
        )
        avisos: tuple[str, ...] = ()
        if conductor is None:
            avisos = (
                f"Ningún conductor de la tabla lleva {_t(tablero.corriente_a, 0)} A a "
                f"{longitud} m con caída menor a {limite} %.",
            )
            e.avisos.extend(avisos)
        e.agregar(
            _resultado(
                "alimentador",
                tablero.tablero,
                f"Alimentador de {tablero.tablero}",
                conductor.texto if conductor else "sin solución",
                "",
                "Conductor con ampacidad ≥ breaker y ΔV % = k × I × L × (R cos φ + X sen φ) ÷ "
                "(n × V) × 100 bajo el límite del alimentador",
                rastro,
                entradas={"corriente_a": tablero.corriente_a, "longitud_m": longitud},
                detalle=(
                    {
                        "breaker_a": breaker if breaker is not None else "fuera de serie",
                        "caida_pct": conductor.caida_pct,
                        "limite_pct": limite,
                    }
                    if conductor
                    else {"limite_pct": limite}
                ),
                avisos=avisos,
            )
        )
        salida.append(
            Alimentador(
                tablero=tablero.tablero,
                corriente_a=tablero.corriente_a,
                breaker_a=breaker,
                conductor=conductor,
                distancia_supuesta=supuesta,
            )
        )
    return salida


# --- 2. Circuitos de máquinas -------------------------------------------------------


def _circuitos(e: _Estudio) -> list[CircuitoMaquina]:
    salida = []
    rastro = Rastro()
    longitud = e.p("longitud_circuito_maquina_m", rastro)
    rastro.supuesto(f"circuitos de máquinas de {longitud} m desde su tablero")
    rastro.supuesto("breaker de motor de al menos un tercio de su corriente de arranque")
    limite = e.p("caida_ramal_max_pct", rastro)
    factor = e.p("factor_diseno_conductor", rastro)
    factor_motor = e.p("factor_breaker_motor", rastro)
    for fila in e.analisis.filas:
        corriente = fila.corriente_a
        trifasica = fila.maquina.fases == 3
        if fila.maquina.tipo == "motor":
            # Que no dispare al arrancar: al menos un tercio de la corriente de
            # arranque, sin pasar el máximo del perfil.
            deseado = corriente * factor
            if fila.corriente_arranque_a is not None:
                deseado = max(deseado, min(fila.corriente_arranque_a / 3, corriente * factor_motor))
            breaker = e.breaker(deseado, rastro)
            ampacidad = corriente * factor
        else:
            breaker = e.breaker(corriente * factor, rastro)
            ampacidad = max(corriente * factor, breaker or CERO)
        conductor = e.conductor(
            corriente,
            ampacidad,
            longitud,
            fila.fp,
            limite,
            "especial",
            trifasica,
            fila.tension_v,
            rastro,
        )
        if conductor is None:
            e.avisos.append(f"{fila.maquina.id}: ningún conductor cumple ampacidad y caída.")
        salida.append(
            CircuitoMaquina(
                maquina=fila.maquina.id,
                tablero=fila.maquina.tablero,
                descripcion=fila.maquina.descripcion,
                corriente_a=corriente,
                breaker_a=breaker,
                conductor=conductor,
                polos=3 if trifasica else (2 if fila.tension_v == e.sistema.v_linea else 1),
            )
        )
    e.agregar(
        _resultado(
            "circuitos_maquinas",
            INDUSTRIA,
            "Circuitos de máquinas",
            Decimal(len(salida)),
            "",
            "Motores: conductor al 125 % de In y breaker hasta el factor del perfil; demás "
            "cargas: breaker al 125 % de In y conductor que lo cubre",
            rastro,
        )
    )
    return salida


# --- 3. Cortocircuito ----------------------------------------------------------------


def _kappa(r: Decimal, x: Decimal) -> Decimal:
    if x <= 0:
        return Decimal("1.02")
    return Decimal("1.02") + Decimal("0.98") * Decimal(math.exp(-3 * float(r / x)))


def _cortocircuito(
    e: _Estudio, alimentadores: list[Alimentador]
) -> tuple[list[PuntoCortocircuito], str, Decimal, Decimal]:
    industria = e.analisis.industria
    decision = e.analisis.decision
    rastro = Rastro()
    kv = e.p("tension_media_kv", rastro)
    if industria.scc_red_mva is not None:
        scc = industria.scc_red_mva
        rastro.supuesto(f"potencia de cortocircuito de la red {scc} MVA indicada")
    else:
        scc = e.p("potencia_cc_red_mva", rastro)
        rastro.supuesto(f"potencia de cortocircuito de la red {scc} MVA del perfil")
    if not e.trifasico:
        e.avisos.append("El cortocircuito se calcula solo para sistemas trifásicos.")
        return [], "", kv, scc

    c = e.p("factor_c_cortocircuito", rastro)
    xr_t = e.p("relacion_xr_transformador", rastro)
    v = e.v

    # Red referida a baja tensión (IEC 60909: X = 0,995 Z, R = 0,1 X).
    zq = c * v * v / (scc * Decimal(10) ** 6)
    xq = Decimal("0.995") * zq
    rq = Decimal("0.1") * xq

    acometida_r = acometida_x = CERO
    if decision.opcion == "existente" and industria.existente is not None:
        existente = industria.existente
        kva = existente.kva
        z_pct = existente.impedancia_pct or rastro.usar(
            e.perfil.impedancia_transformador(existente.kva, existente.fases)
        )
        fuente = f"Transformador existente {existente.codigo or ''} de {kva} kVA".replace("  ", " ")
        if decision.acometida is not None:
            fila, n = decision.acometida
            acometida_r = fila.r_ohm_km * existente.distancia_m / MIL / n
            acometida_x = fila.x_ohm_km * existente.distancia_m / MIL / n
            fuente += f" y acometida de {existente.distancia_m} m"
    elif decision.transformador is not None:
        kva = decision.transformador.kva
        z_pct = decision.transformador.z_pct
        fuente = f"Transformador particular de {kva} kVA"
        rastro.supuesto("tablero principal junto a los bornes del transformador")
    else:
        e.avisos.append("Sin transformador definido no se calcula el cortocircuito.")
        return [], "", kv, scc

    zt = z_pct / CIEN * v * v / (kva * MIL)
    rt = zt / (UNO + xr_t * xr_t).sqrt()
    xt = rt * xr_t

    motores = sum(
        (f.corriente_a * f.maquina.cantidad for f in e.analisis.filas if f.maquina.tipo == "motor"),
        CERO,
    )
    aporte = motores * e.p("contribucion_motores", rastro) / MIL

    puntos: list[PuntoCortocircuito] = []

    def punto(nombre: str, r: Decimal, x: Decimal, sujeto: str) -> PuntoCortocircuito:
        z = (r * r + x * x).sqrt()
        ik = c * v / (RAIZ3 * z) / MIL + aporte
        ip = _kappa(r, x) * Decimal(2).sqrt() * ik
        try:
            capacidad: Decimal | None = rastro.usar(
                e.perfil.normalizado("capacidad_interruptiva_ka", ik)
            )
        except FilaNoEncontrada:
            capacidad = None
        avisos: tuple[str, ...] = ()
        if capacidad is None:
            avisos = (
                f"{_t(ik, 1)} kA en {nombre} supera la serie de capacidades de interrupción.",
            )
            e.avisos.extend(avisos)
        e.agregar(
            _resultado(
                "cortocircuito",
                sujeto,
                f"Cortocircuito en {nombre}",
                redondear(ik, 2),
                "kA",
                "Ik = c × V ÷ (√3 × |Zred + Ztransformador + Zcables|) + aporte de motores; "
                "ip = κ × √2 × Ik",
                rastro,
                entradas={"r_ohm": r, "x_ohm": x, "aporte_motores_ka": aporte},
                detalle={
                    "ip_ka": redondear(ip, 2),
                    "capacidad_ka": capacidad if capacidad is not None else "fuera de serie",
                },
                avisos=avisos,
            )
        )
        resultado = PuntoCortocircuito(
            punto=nombre, ik_ka=ik, ip_ka=ip, xr=x / r if r > 0 else CERO, capacidad_ka=capacidad
        )
        puntos.append(resultado)
        return resultado

    r0 = rq + rt + acometida_r
    x0 = xq + xt + acometida_x
    punto(PRINCIPAL, r0, x0, PRINCIPAL)
    for alimentador in alimentadores:
        if alimentador.conductor is None:
            continue
        punto(
            alimentador.tablero,
            r0 + alimentador.conductor.r_ohm,
            x0 + alimentador.conductor.x_ohm,
            alimentador.tablero,
        )
    return puntos, fuente, kv, scc


def estudiar(analisis: AnalisisIndustrial, perfil: Perfil) -> Estudios:
    """Alimentadores, circuitos y cortocircuito a partir del análisis."""
    e = _Estudio(analisis, perfil)
    alimentadores = _alimentadores(e)
    circuitos = _circuitos(e)
    puntos, fuente, kv, scc = _cortocircuito(e, alimentadores)
    return Estudios(
        alimentadores=tuple(alimentadores),
        circuitos=tuple(circuitos),
        cortocircuito=tuple(puntos),
        fuente=fuente,
        tension_media_kv=kv,
        scc_red_mva=scc,
        resultados=tuple(e.resultados),
        avisos=tuple(e.avisos),
        estado=peor_estado([r.estado for r in e.resultados]),
    )


__all__ = [
    "PRINCIPAL",
    "Alimentador",
    "CircuitoMaquina",
    "Conductor",
    "Estudios",
    "FilaCuadro",
    "PuntoCortocircuito",
    "TotalTablero",
    "estudiar",
]
