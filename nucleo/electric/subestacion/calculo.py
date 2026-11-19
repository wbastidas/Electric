"""Cálculo de una subestación 69/13,8 kV.

1. Transformador de potencia: el menor cuya potencia ONAF cubre la demanda con
   reserva y cuya potencia ONAN cubre la demanda.
2. Corrientes nominales y cortocircuito trifásico en barras de 69 y 13,8 kV
   (red como impedancia equivalente de su Scc, en serie con el transformador).
3. Interruptores, transformadores de corriente, pararrayos y alimentadores.
4. Malla de puesta a tierra por IEEE 80: resistencia (Sverak), tensiones de
   malla y de paso frente a las tolerables (persona de 70 kg) y calibre del
   conductor (Onderdonk/Sverak simplificada).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from electric.calculo.resultado import Rastro, Resultado
from electric.errores import FilaNoEncontrada
from electric.industrial.analisis import _t
from electric.industrial.estudios import _resultado
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import Estado, FilaTransformadorPotencia, peor_estado
from electric.subestacion.modelo import Subestacion

RAIZ3 = Decimal(3).sqrt()
PROYECTO = "subestacion"
PROFUNDIDAD_M = 0.5
#: Diámetro del conductor de cobre 4/0 AWG desnudo.
DIAMETRO_4_0_M = 0.01341
#: Calibres de cobre para la malla: (nombre, kcmil, diámetro en m).
CALIBRES_MALLA = (
    ("2/0 AWG", 133.1, 0.01064),
    ("4/0 AWG", 211.6, 0.01341),
    ("250 kcmil", 250.0, 0.01459),
    ("350 kcmil", 350.0, 0.01727),
    ("500 kcmil", 500.0, 0.02063),
)
SEPARACIONES_M = (10.0, 8.0, 6.0, 5.0, 4.0, 3.0)


@dataclass(frozen=True)
class Equipo:
    nombre: str
    especificacion: str


@dataclass(frozen=True)
class MallaSE:
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
    corriente_malla_a: float
    gpr_v: float
    tension_malla_v: float
    tension_paso_v: float
    contacto_tolerable_v: float
    paso_tolerable_v: float
    limite_resistencia_ohm: float
    cumple: bool

    @property
    def resistencia_cumple(self) -> bool:
        return self.resistencia_ohm <= self.limite_resistencia_ohm


@dataclass(frozen=True)
class SubestacionCalculada:
    subestacion: Subestacion
    tension_at_kv: Decimal
    tension_mt_kv: Decimal
    scc_at_mva: Decimal
    transformador: FilaTransformadorPotencia | None
    corriente_at_a: Decimal
    corriente_mt_a: Decimal
    icc_at_ka: Decimal
    icc_mt_ka: Decimal
    corriente_alimentador_a: Decimal
    equipos: tuple[Equipo, ...]
    malla: MallaSE
    resultados: tuple[Resultado, ...]
    avisos: tuple[str, ...]

    @property
    def estado(self) -> Estado:
        return peor_estado([r.estado for r in self.resultados])


def _tc(perfil: Perfil, corriente: Decimal, rastro: Rastro) -> str:
    try:
        primario = rastro.usar(perfil.normalizado("relaciones_tc", corriente * Decimal("1.25")))
        return f"{_t(primario, 0)}/5 A"
    except FilaNoEncontrada:
        return "fuera de serie"


def _serie(perfil: Perfil, nombre: str, minimo: Decimal, rastro: Rastro) -> Decimal | None:
    try:
        return rastro.usar(perfil.normalizado(nombre, minimo))
    except FilaNoEncontrada:
        return None


def calcular_subestacion(se: Subestacion, perfil: Perfil) -> SubestacionCalculada:
    resultados: list[Resultado] = []
    avisos: list[str] = []

    # 1. Transformador.
    rastro = Rastro()
    kv_at = se.tension_at_kv or rastro.usar(perfil.parametro("tension_alta_kv"))
    kv_mt = se.tension_mt_kv or rastro.usar(perfil.parametro("tension_media_kv"))
    reserva = rastro.usar(perfil.parametro("reserva_transformador_pct"))
    requerida = se.demanda_mva * (1 + reserva / 100)
    filas, tabla = perfil.transformadores_potencia()
    trafo = next(
        (f for f in filas if f.mva_onaf >= requerida and f.mva_onan >= se.demanda_mva), None
    )
    if trafo is None:
        avisos.append(
            f"Ningún transformador de la tabla cubre {_t(requerida, 1)} MVA: se necesitan dos "
            "transformadores en paralelo o una subestación mayor."
        )
    else:
        rastro.anotar(perfil._ref(tabla, f"{trafo.mva_onan}/{trafo.mva_onaf} MVA"))
    resultados.append(
        _resultado(
            "transformador",
            PROYECTO,
            "Transformador de potencia",
            f"{_t(trafo.mva_onan, 1)}/{_t(trafo.mva_onaf, 2)} MVA ONAN/ONAF"
            if trafo
            else "sin solución",
            "",
            "Menor transformador con ONAF ≥ D × (1 + reserva) y ONAN ≥ D",
            rastro,
            entradas={"demanda_mva": se.demanda_mva, "reserva_pct": reserva},
            detalle={"requerida_mva": requerida, **({"z_pct": trafo.z_pct} if trafo else {})},
        )
    )
    s_base = trafo.mva_onaf if trafo else requerida
    i_at = s_base * 1000 / (RAIZ3 * kv_at)
    i_mt = s_base * 1000 / (RAIZ3 * kv_mt)

    # 2. Cortocircuito.
    rastro = Rastro()
    if se.scc_at_mva is not None:
        scc = se.scc_at_mva
    else:
        scc = rastro.usar(perfil.parametro("potencia_cc_at_mva"))
        rastro.supuesto(
            f"Scc en 69 kV de {_t(scc, 0)} MVA (por verificar con la factibilidad de CNEL)"
        )
    icc_at = scc / (RAIZ3 * kv_at)
    if trafo:
        # Impedancias en por unidad sobre la base ONAN del transformador.
        z_red = trafo.mva_onan / scc
        z_t = trafo.z_pct / 100
        icc_mt = trafo.mva_onan / (RAIZ3 * kv_mt) / (z_red + z_t)
    else:
        icc_mt = Decimal(0)
    resultados.append(
        _resultado(
            "cortocircuito",
            PROYECTO,
            "Cortocircuito trifásico en barras",
            icc_mt,
            "kA",
            "Icc AT = Scc ÷ (√3 × kV AT); Icc MT = In(ONAN) ÷ (Zred + Zt) en p.u. con "
            "Zred = S ÷ Scc",
            rastro,
            entradas={"scc_mva": scc},
            detalle={"icc_at_ka": icc_at, "icc_mt_ka": icc_mt},
        )
    )

    # 3. Equipos.
    rastro = Rastro()
    n = se.alimentadores
    i_alim = se.demanda_mva * 1000 / (RAIZ3 * kv_mt) / n
    maximo_alim = rastro.usar(perfil.parametro("corriente_max_alimentador_mt_a"))
    if i_alim > maximo_alim:
        sugeridos = math.ceil(float(se.demanda_mva * 1000 / (RAIZ3 * kv_mt) / maximo_alim))
        avisos.append(
            f"Cada alimentador llevaría {_t(i_alim, 0)} A, más que {_t(maximo_alim, 0)} A: "
            f"use al menos {sugeridos} alimentadores."
        )
    in_at = _serie(perfil, "interruptores_at_a", i_at * Decimal("1.25"), rastro)
    in_mt = _serie(perfil, "interruptores_mt_a", i_mt * Decimal("1.25"), rastro)
    in_alim = _serie(perfil, "interruptores_mt_a", i_alim * Decimal("1.25"), rastro)
    ka_at = _serie(perfil, "icc_interruptores_ka", icc_at, rastro)
    ka_mt = _serie(perfil, "icc_interruptores_ka", icc_mt, rastro)
    para_at = rastro.usar(perfil.parametro("pararrayos_at_kv"))
    para_mt = rastro.usar(perfil.parametro("pararrayos_mt_kv"))
    aux = rastro.usar(perfil.parametro("transformador_auxiliar_kva"))

    def a(v: Decimal | None, u: str) -> str:
        return f"{_t(v, 1 if u == 'kA' else 0)} {u}" if v is not None else "fuera de serie"

    equipos = [
        Equipo("Pararrayos de 69 kV", f"{_t(para_at, 0)} kV, clase estación, uno por fase"),
        Equipo(
            "Seccionador de 69 kV", f"tripolar con cuchilla de puesta a tierra, {a(in_at, 'A')}"
        ),
        Equipo("Interruptor de 69 kV", f"72,5 kV, {a(in_at, 'A')}, {a(ka_at, 'kA')}"),
        Equipo("TC de 69 kV", f"{_tc(perfil, i_at, rastro)}, protección y medición"),
        Equipo("TP de 69 kV", f"{_t(kv_at * 1000, 0)}/√3 : 120/√3 V"),
        Equipo(
            "Transformador de potencia",
            f"{_t(trafo.mva_onan, 1)}/{_t(trafo.mva_onaf, 2)} MVA, "
            f"{_t(kv_at, 1)}/{_t(kv_mt, 1)} kV, "
            f"{trafo.grupo}, Z {_t(trafo.z_pct, 1)} %, con cambiador de tomas"
            if trafo
            else "sin solución",
        ),
        Equipo("Pararrayos de 13,8 kV", f"{_t(para_mt, 0)} kV, en bornes del transformador"),
        Equipo("Interruptor principal de 13,8 kV", f"15 kV, {a(in_mt, 'A')}, {a(ka_mt, 'kA')}"),
        Equipo("TC principal de 13,8 kV", _tc(perfil, i_mt, rastro)),
        Equipo(
            f"Interruptores de alimentador ({n})",
            f"15 kV, {a(in_alim, 'A')}, {a(ka_mt, 'kA')}, TC {_tc(perfil, i_alim, rastro)}",
        ),
        Equipo(
            "Transformador de servicios auxiliares",
            f"{_t(aux, 0)} kVA, {_t(kv_mt, 1)} kV/220-127 V",
        ),
        Equipo("Relés de protección", "87T diferencial, 50/51 y 50N/51N en AT y MT, 63 Buchholz"),
    ]
    resultados.append(
        _resultado(
            "equipos",
            PROYECTO,
            "Equipos de patio y celdas",
            f"{len(equipos)} equipos",
            "",
            "Interruptores ≥ 125 % de In y capacidad ≥ Icc; TC con primario ≥ 125 % de In",
            rastro,
            entradas={"alimentadores": Decimal(n)},
            detalle={
                "corriente_at_a": i_at,
                "corriente_mt_a": i_mt,
                "corriente_alimentador_a": i_alim,
            },  # fmt: skip
        )
    )

    # 4. Malla de tierra.
    malla, rastro_m = _malla(se, perfil, icc_at)
    if not malla.cumple:
        avisos.append(
            "La malla no logra tensiones de malla y paso tolerables con 3 m de separación: "
            "amplíe el área, agregue varillas o mejore la capa superficial."
        )
    if not malla.resistencia_cumple:
        avisos.append(
            f"La resistencia de la malla ({malla.resistencia_ohm:.2f} Ω) supera "
            f"{malla.limite_resistencia_ohm:.0f} Ω: amplíe el área de la malla, use varillas "
            "más profundas o tratamiento del suelo."
        )
    resultados.append(
        _resultado(
            "malla",
            PROYECTO,
            "Malla de puesta a tierra (IEEE 80)",
            Decimal(str(round(malla.resistencia_ohm, 3))),
            "Ω",
            "Rg de Sverak; Em = ρ Km Ki IG ÷ LM ≤ E contacto; Es = ρ Ks Ki IG ÷ LS ≤ E paso "
            "(70 kg); A = I × Kf × √tc",
            rastro_m,
            entradas={"largo_m": se.largo_malla_m, "ancho_m": se.ancho_malla_m},
            detalle={
                "separacion_m": Decimal(str(malla.separacion_m)),
                "tension_malla_v": Decimal(str(round(malla.tension_malla_v))),
                "contacto_tolerable_v": Decimal(str(round(malla.contacto_tolerable_v))),
                "tension_paso_v": Decimal(str(round(malla.tension_paso_v))),
                "paso_tolerable_v": Decimal(str(round(malla.paso_tolerable_v))),
                "gpr_v": Decimal(str(round(malla.gpr_v))),
                "calibre": malla.calibre,
            },
        )
    )
    return SubestacionCalculada(
        subestacion=se,
        tension_at_kv=kv_at,
        tension_mt_kv=kv_mt,
        scc_at_mva=scc,
        transformador=trafo,
        corriente_at_a=i_at,
        corriente_mt_a=i_mt,
        icc_at_ka=icc_at,
        icc_mt_ka=icc_mt,
        corriente_alimentador_a=i_alim,
        equipos=tuple(equipos),
        malla=malla,
        resultados=tuple(resultados),
        avisos=tuple(avisos),
    )


def _malla(se: Subestacion, perfil: Perfil, icc_at_ka: Decimal) -> tuple[MallaSE, Rastro]:
    rastro = Rastro()

    def p(clave: str) -> float:
        return float(rastro.usar(perfil.parametro(clave)))

    if se.resistividad_ohm_m is not None:
        rho = float(se.resistividad_ohm_m)
    else:
        rho = p("resistividad_suelo_ohm_m")
        rastro.supuesto(f"resistividad del suelo de {rho:.0f} Ω·m; debe medirse en sitio")
    ts = float(se.tiempo_falla_s) if se.tiempo_falla_s is not None else p("tiempo_despeje_falla_s")
    sf = p("factor_division_corriente")
    rho_s = p("resistividad_superficial_ohm_m")
    hs = p("espesor_capa_superficial_m")
    varilla = p("varilla_tierra_m")
    limite_r = p("resistencia_tierra_subestacion_max_ohm")
    h = PROFUNDIDAD_M
    lx, ly = float(se.largo_malla_m), float(se.ancho_malla_m)
    area = lx * ly
    i_falla = float(icc_at_ka) * 1000  # se toma la falla monofásica igual a la trifásica
    ig = i_falla * sf

    # Calibre mínimo: A[kcmil] = I[kA] × Kf × √tc, Kf = 7,06 (cobre recocido).
    minimo = float(icc_at_ka) * 7.06 * math.sqrt(ts)
    calibre, _, d = next(
        (c for c in CALIBRES_MALLA if c[1] >= max(minimo, 133.1)), CALIBRES_MALLA[-1]
    )
    rastro.supuesto("falla monofásica en 69 kV igual a la trifásica; malla a 0,5 m")

    # Tolerables para una persona de 70 kg (IEEE 80, ec. 30 y 33).
    cs = 1 - 0.09 * (1 - rho / rho_s) / (2 * hs + 0.09)
    e_contacto = (1000 + 1.5 * cs * rho_s) * 0.157 / math.sqrt(ts)
    e_paso = (1000 + 6 * cs * rho_s) * 0.157 / math.sqrt(ts)

    elegida: MallaSE | None = None
    for sep in SEPARACIONES_M:
        nx = max(2, math.ceil(ly / sep) + 1)  # conductores paralelos al largo
        ny = max(2, math.ceil(lx / sep) + 1)
        lc = nx * lx + ny * ly
        varillas = 4 + 2 * (nx + ny - 4)  # en el perímetro
        lr = varillas * varilla
        lt = lc + lr
        rg = rho * (1 / lt + 1 / math.sqrt(20 * area) * (1 + 1 / (1 + h * math.sqrt(20 / area))))
        dd = min(lx / (ny - 1), ly / (nx - 1))
        lp = 2 * (lx + ly)
        na = 2 * lc / lp
        nb = math.sqrt(lp / (4 * math.sqrt(area)))
        n = na * nb
        kh = math.sqrt(1 + h / 1.0)
        km = (1 / (2 * math.pi)) * (
            math.log(dd**2 / (16 * h * d) + (dd + 2 * h) ** 2 / (8 * dd * d) - h / (4 * d))
            + (1 / kh) * math.log(8 / (math.pi * (2 * n - 1)))
        )
        ki = 0.644 + 0.148 * n
        lm = lc + (1.55 + 1.22 * (varilla / math.sqrt(lx**2 + ly**2))) * lr
        em = rho * km * ki * ig / lm
        ks = (1 / math.pi) * (1 / (2 * h) + 1 / (dd + h) + (1 / dd) * (1 - 0.5 ** (n - 2)))
        ls = 0.75 * lc + 0.85 * lr
        es = rho * ks * ki * ig / ls
        cumple = em <= e_contacto and es <= e_paso
        elegida = MallaSE(
            largo_m=lx, ancho_m=ly, separacion_m=sep, conductores_x=nx, conductores_y=ny,
            varillas=varillas, longitud_conductor_m=lc, calibre=calibre,
            calibre_minimo_kcmil=minimo, resistencia_ohm=rg, corriente_malla_a=ig,
            gpr_v=ig * rg, tension_malla_v=em, tension_paso_v=es,
            contacto_tolerable_v=e_contacto, paso_tolerable_v=e_paso,
            limite_resistencia_ohm=limite_r, cumple=cumple,
        )  # fmt: skip
        if cumple:
            break
    assert elegida is not None
    return elegida, rastro
