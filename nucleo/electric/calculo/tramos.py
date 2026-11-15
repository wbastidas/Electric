"""Tramos eléctricos y selección de conductor.

Un tramo es un circuito ramal o el alimentador. Aquí viven las fórmulas
compartidas por RC-06 a RC-09 y la única iteración del motor: si la caída de
tensión supera el límite, se sube un calibre, con un tope fijo de pasos.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from electric.calculo.contexto import Contexto
from electric.calculo.resultado import ALIMENTADOR, PROYECTO, Rastro
from electric.errores import DatoInvalido, SinSolucion
from electric.perfiles.esquema import FilaConductor, FilaSistema

UNO = Decimal(1)
CIEN = Decimal(100)
MIL = Decimal(1000)


@dataclass(frozen=True)
class Tramo:
    sujeto: str
    #: iluminacion, tomacorrientes, especial o alimentador.
    uso: str
    potencia_w: Decimal
    tension_v: Decimal
    polos: int
    trifasico: bool
    longitud_m: Decimal
    #: Conductores portadores de corriente, para la corrección por agrupamiento.
    portadores: int
    #: Conductores aislados de fase y neutro, para el relleno de ducto.
    conductores: int
    zona_humeda: bool = False

    @property
    def k(self) -> Decimal:
        """Factor de la caída de tensión: ida y vuelta, o √3 en trifásico."""
        return Decimal(3).sqrt() if self.trifasico else Decimal(2)


@dataclass(frozen=True)
class Seleccion:
    fila: FilaConductor
    breaker: Decimal
    corriente_diseno: Decimal
    ampacidad_corregida: Decimal
    factor_temperatura: Decimal
    factor_agrupamiento: Decimal
    caida_pct: Decimal
    limite_caida_pct: Decimal
    #: Veces que se subió el calibre porque la caída superaba el límite.
    pasos_por_caida: int


def sistema(ctx: Contexto, rastro: Rastro) -> FilaSistema:
    return rastro.usar(ctx.perfil.sistema(ctx.proyecto.sistema))


def conexion_carga(ctx: Contexto, id_circuito: str, rastro: Rastro) -> str:
    """Conexión de la carga de un circuito especial: fase-neutro o entre líneas."""
    carga = next(c for c in ctx.proyecto.cargas_especiales if c.circuito == id_circuito)
    if carga.conexion is not None:
        return carga.conexion
    return rastro.usar(ctx.perfil.carga(carga.tipo)).conexion


def tramos(ctx: Contexto, rastro: Rastro) -> list[Tramo]:
    """Todos los tramos del proyecto: cada circuito y, al final, el alimentador."""
    sis = sistema(ctx, rastro)
    lista: list[Tramo] = []
    for circuito in ctx.proyecto.circuitos:
        entre_lineas = (
            circuito.tipo == "especial" and conexion_carga(ctx, circuito.id, rastro) == "linea"
        )
        if entre_lineas and sis.fases == 1:
            raise DatoInvalido(
                f"el circuito {circuito.id} necesita tensión entre líneas "
                f"y el sistema '{sis.id}' no la tiene"
            )
        lista.append(
            Tramo(
                sujeto=circuito.id,
                uso=circuito.tipo,
                potencia_w=ctx.res("RC-01", circuito.id).decimal,
                tension_v=sis.v_linea if entre_lineas else sis.v_fase_neutro,
                polos=2 if entre_lineas else 1,
                trifasico=False,
                longitud_m=circuito.longitud_m,
                portadores=circuito.portadores_en_ducto or 2,
                conductores=2,
                zona_humeda=circuito.zona_humeda,
            )
        )
    lista.append(
        Tramo(
            sujeto=ALIMENTADOR,
            uso="alimentador",
            potencia_w=ctx.res("RC-03", PROYECTO).decimal,
            tension_v=sis.v_linea,
            polos=sis.fases,
            trifasico=sis.fases == 3,
            longitud_m=ctx.proyecto.tablero.alimentador_longitud_m,
            portadores=max(sis.fases, 2),
            conductores=sis.fases + 1,
        )
    )
    return lista


def corriente(potencia_w: Decimal, tension_v: Decimal, fp: Decimal, trifasico: bool) -> Decimal:
    """I = P / (V × FP), o I = P / (√3 × V × FP) en trifásico."""
    divisor = tension_v * fp
    if trifasico:
        divisor *= Decimal(3).sqrt()
    return potencia_w / divisor


def caida_pct(
    corriente_a: Decimal,
    longitud_m: Decimal,
    tension_v: Decimal,
    fp: Decimal,
    r_ohm_km: Decimal,
    x_ohm_km: Decimal,
    k: Decimal,
) -> Decimal:
    """ΔV % = k × I × L × (R cos φ + X sen φ) / 1000 / V × 100."""
    seno = (UNO - fp * fp).sqrt()
    caida_v = k * corriente_a * longitud_m * (r_ohm_km * fp + x_ohm_km * seno) / MIL
    return caida_v / tension_v * CIEN


def limite_caida(ctx: Contexto, tramo: Tramo, rastro: Rastro) -> Decimal:
    """Límite de caída del tramo: el del ramal, o total menos ramal para el alimentador."""
    ramal = rastro.usar(ctx.perfil.parametro("caida_ramal_max_pct"))
    if tramo.uso != "alimentador":
        return ramal
    return rastro.usar(ctx.perfil.parametro("caida_total_max_pct")) - ramal


def breaker_requerido(ctx: Contexto, tramo: Tramo, corriente_diseno: Decimal, r: Rastro) -> Decimal:
    """Primer breaker normalizado que cubre la corriente de diseño y el mínimo del uso."""
    minimo = r.usar(ctx.perfil.minimo_calibre(tramo.uso)).breaker_min or Decimal(0)
    if tramo.uso == "alimentador":
        minimo = max(minimo, r.usar(ctx.perfil.parametro("principal_min_a")))
    return r.usar(ctx.perfil.normalizado("breakers", max(corriente_diseno, minimo)))


def seleccionar(ctx: Contexto, tramo: Tramo, rastro: Rastro) -> Seleccion:
    """Primer calibre normalizado que cumple ampacidad, protección y caída de tensión."""
    perfil = ctx.perfil
    fp = ctx.parametro("factor_potencia", rastro)
    temperatura = ctx.parametro("temperatura_ambiente_c", rastro)
    factor_diseno = rastro.usar(perfil.parametro("factor_diseno_conductor"))
    pasos_max = int(rastro.usar(perfil.parametro("pasos_max_calibre")))
    f_temp = rastro.usar(perfil.factor_temperatura(temperatura))
    f_agr = rastro.usar(perfil.factor_agrupamiento(tramo.portadores))
    limite = limite_caida(ctx, tramo, rastro)

    i = corriente(tramo.potencia_w, tramo.tension_v, fp, tramo.trifasico)
    i_diseno = i * factor_diseno
    breaker = breaker_requerido(ctx, tramo, i_diseno, rastro)

    filas, tabla = perfil.conductores()
    minimo = rastro.usar(perfil.minimo_calibre(tramo.uso)).calibre
    inicio = next(n for n, f in enumerate(filas) if f.calibre == minimo)

    pasos = 0
    for fila in filas[inicio:]:
        ampacidad = fila.ampacidad * f_temp * f_agr
        if ampacidad < i_diseno:
            continue
        breaker_max = fila.breaker_max or perfil.normalizado_hasta("breakers", fila.ampacidad)
        if breaker_max is None or breaker_max < breaker:
            continue
        caida = caida_pct(
            i, tramo.longitud_m, tramo.tension_v, fp, fila.r_ohm_km, fila.x_ohm_km, tramo.k
        )
        if caida > limite:
            pasos += 1
            if pasos > pasos_max:
                raise SinSolucion(
                    tramo.sujeto,
                    f"la caída de tensión sigue sobre {limite} % tras subir {pasos_max} calibres",
                )
            continue
        rastro.anotar(perfil._ref(tabla, fila.calibre))
        return Seleccion(
            fila=fila,
            breaker=breaker,
            corriente_diseno=i_diseno,
            ampacidad_corregida=ampacidad,
            factor_temperatura=f_temp,
            factor_agrupamiento=f_agr,
            caida_pct=caida,
            limite_caida_pct=limite,
            pasos_por_caida=pasos,
        )
    raise SinSolucion(tramo.sujeto, "ningún calibre del perfil cumple ampacidad, breaker y caída")
