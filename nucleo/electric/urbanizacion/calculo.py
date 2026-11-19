"""Cálculo de una urbanización: sectores de transformación por calle, red de baja
tensión con caída de tensión, alumbrado público y demanda en media tensión."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from electric.calculo.resultado import Rastro, Resultado
from electric.errores import DatoInvalido, FilaNoEncontrada
from electric.industrial.analisis import _t
from electric.industrial.estudios import Conductor, _resultado, elegir_conductor
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import Estado, FilaSistema, peor_estado
from electric.urbanizacion.modelo import Urbanizacion

RAIZ3 = Decimal(3).sqrt()
MIL = Decimal(1000)
CIEN = Decimal(100)
PROYECTO = "urbanizacion"


@dataclass(frozen=True)
class Lote:
    id: str
    manzana: str
    calle: int
    x: float
    lado: str  # "norte" o "sur" de la calle


@dataclass(frozen=True)
class Circuito:
    lado: str  # izquierda o derecha del transformador
    lotes: int
    longitud_m: Decimal
    corriente_a: Decimal
    conductor: Conductor | None


@dataclass(frozen=True)
class Sector:
    id: str
    calle: int
    x: float
    lotes: tuple[str, ...]
    luminarias: int
    comunal_kva: Decimal
    demanda_kva: Decimal
    kva: Decimal | None
    circuitos: tuple[Circuito, ...]


@dataclass(frozen=True)
class Calle:
    numero: int
    longitud_m: Decimal
    lotes: int
    luminarias: tuple[float, ...]


@dataclass(frozen=True)
class UrbanizacionCalculada:
    urbanizacion: Urbanizacion
    sistema: FilaSistema
    lotes: tuple[Lote, ...]
    calles: tuple[Calle, ...]
    sectores: tuple[Sector, ...]
    dmu_kva: Decimal
    demanda_kva: Decimal
    alumbrado_kva: Decimal
    kva_instalados: Decimal
    corriente_mt_a: Decimal
    tension_mt_kv: Decimal
    resultados: tuple[Resultado, ...]
    avisos: tuple[str, ...]

    @property
    def estado(self) -> Estado:
        return peor_estado([r.estado for r in self.resultados])


def _filas(lotes: int) -> tuple[int, int]:
    return math.ceil(lotes / 2), lotes // 2


class _Calculo:
    def __init__(self, u: Urbanizacion, perfil: Perfil) -> None:
        self.u = u
        self.perfil = perfil
        self.sistema, _ = perfil.sistema(u.sistema)
        self.resultados: list[Resultado] = []
        self.avisos: list[str] = []

    def p(self, clave: str, rastro: Rastro) -> Decimal:
        return rastro.usar(self.perfil.parametro(clave))

    def lotes(self) -> list[Lote]:
        salida: list[Lote] = []
        for m, manzana in enumerate(self.u.manzanas):
            norte, sur = _filas(manzana.lotes)
            f = float(manzana.frente_m)
            n = 1
            # Fila norte: da a la calle m (lado sur de esa calle).
            for col in range(norte):
                salida.append(Lote(f"{manzana.id}-{n}", manzana.id, m, (col + 0.5) * f, "sur"))
                n += 1
            for col in range(sur):
                salida.append(
                    Lote(f"{manzana.id}-{n}", manzana.id, m + 1, (col + 0.5) * f, "norte")
                )
                n += 1
        return salida

    def demanda(self, lotes: int, dmu: Decimal, rastro: Rastro) -> Decimal:
        if lotes == 0:
            return Decimal(0)
        return lotes * dmu * rastro.usar(self.perfil.coincidencia(lotes))

    def calcular(self) -> UrbanizacionCalculada:
        u = self.u
        rastro = Rastro()
        fila = rastro.usar(self.perfil.demanda_usuario(u.estrato))
        if fila.kva is None:
            raise DatoInvalido(f"el tipo de usuario {u.estrato} no tiene DMU en kVA")
        dmu = fila.kva
        lotes = self.lotes()
        total_lotes = len(lotes)

        # Alumbrado público por calle.
        rastro_ap = Rastro()
        separacion = u.separacion_luminarias_m or self.p("separacion_luminarias_ap_m", rastro_ap)
        potencia = u.potencia_luminaria_w or self.p("potencia_luminaria_ap_w", rastro_ap)
        fp = self.p("factor_potencia", rastro_ap)
        calles: list[Calle] = []
        for k in range(len(u.manzanas) + 1):
            # La calle k tiene al sur la fila norte de la manzana k y al norte la
            # fila sur de la manzana k − 1.
            largos = []
            if k < len(u.manzanas):
                m = u.manzanas[k]
                largos.append(float(m.frente_m) * _filas(m.lotes)[0])
            if k > 0:
                m = u.manzanas[k - 1]
                largos.append(float(m.frente_m) * _filas(m.lotes)[1])
            largo = max(largos, default=0.0)
            puntos: list[float] = []
            x = float(separacion) / 2
            while largo > 0 and x <= largo:
                puntos.append(x)
                x += float(separacion)
            if largo > 0 and not puntos:
                puntos = [largo / 2]
            calles.append(
                Calle(
                    k,
                    Decimal(str(round(largo, 2))),
                    sum(1 for lt in lotes if lt.calle == k),
                    tuple(puntos),
                )  # fmt: skip
            )
        luminarias = sum(len(c.luminarias) for c in calles)
        kva_luminaria = potencia / fp / MIL
        alumbrado = luminarias * kva_luminaria
        self.resultados.append(
            _resultado(
                "alumbrado",
                PROYECTO,
                "Alumbrado público",
                Decimal(luminarias),
                "luminarias",
                "Una luminaria cada separación a lo largo de cada calle",
                rastro_ap,
                entradas={"separacion_m": separacion, "potencia_w": potencia},
                detalle={"carga_kva": alumbrado},
            )
        )

        # Sectores de transformación por calle.
        rastro_t = Rastro()
        reserva = self.p("reserva_transformador_pct", rastro_t)
        maximo = u.kva_max_transformador or self.p(
            f"kva_max_transformador_urbanizacion_{u.fases_transformador}f", rastro_t
        )
        sectores: list[Sector] = []
        for calle in calles:
            de_calle = sorted((lt for lt in lotes if lt.calle == calle.numero), key=lambda lt: lt.x)
            comunal = sum((c.kva for c in u.comunales if c.calle == calle.numero), Decimal(0))
            if not de_calle and not comunal:
                continue
            partes = 1
            while True:
                grupos = _partir(de_calle, partes)
                propuestos = []
                for g, grupo in enumerate(grupos):
                    lums = _luminarias_de(calle, grupo, grupos, g)
                    extra = comunal if g == len(grupos) // 2 else Decimal(0)
                    demanda = self.demanda(len(grupo), dmu, rastro_t) + lums * kva_luminaria + extra
                    propuestos.append((grupo, lums, extra, demanda))
                if all(d * (1 + reserva / CIEN) <= maximo for *_, d in propuestos) or partes >= max(
                    1, len(de_calle)
                ):
                    break
                partes += 1
            for grupo, lums, extra, demanda in propuestos:
                n = len(sectores) + 1
                requerida = demanda * (1 + reserva / CIEN)
                try:
                    kva: Decimal | None = rastro_t.usar(
                        self.perfil.transformador_para(requerida, u.fases_transformador)
                    ).kva
                except FilaNoEncontrada:
                    kva = None
                    self.avisos.append(f"T-{n}: ningún transformador cubre {_t(requerida, 1)} kVA.")
                x = grupo[len(grupo) // 2].x if grupo else float(calle.longitud_m) / 2
                sectores.append(
                    Sector(
                        id=f"T-{n}",
                        calle=calle.numero,
                        x=x,
                        lotes=tuple(lt.id for lt in grupo),
                        luminarias=lums,
                        comunal_kva=extra,
                        demanda_kva=demanda,
                        kva=kva,
                        circuitos=self.circuitos(f"T-{n}", grupo, x, dmu),
                    )
                )
        kva_instalados = sum((s.kva or Decimal(0) for s in sectores), Decimal(0))
        comunales = sum((c.kva for c in u.comunales), Decimal(0))
        demanda_total = self.demanda(total_lotes, dmu, rastro) + alumbrado + comunales
        kv = self.p("tension_media_kv", rastro)
        corriente_mt = demanda_total / (RAIZ3 * kv)
        self.resultados.append(
            _resultado(
                "transformadores",
                PROYECTO,
                "Transformadores de la urbanización",
                Decimal(len(sectores)),
                "",
                "Sectores contiguos por calle tales que la demanda coincidente de sus lotes, "
                "su alumbrado y las cargas comunales, con reserva, quepa en el mayor "
                "transformador admitido",
                rastro_t,
                entradas={"kva_max": maximo, "reserva_pct": reserva},
                detalle={"kva_instalados": kva_instalados},
            )
        )
        self.resultados.append(
            _resultado(
                "demanda_total",
                PROYECTO,
                "Demanda de la urbanización en media tensión",
                demanda_total,
                "kVA",
                "D = N × DMU × FC(N) + alumbrado público + cargas comunales; I = D ÷ (√3 × kV)",
                rastro,
                entradas={
                    "lotes": Decimal(total_lotes),
                    "dmu_kva": dmu,
                    "estrato": u.estrato,
                },  # fmt: skip
                detalle={"corriente_mt_a": corriente_mt, "tension_kv": kv},
            )
        )
        return UrbanizacionCalculada(
            urbanizacion=u,
            sistema=self.sistema,
            lotes=tuple(lotes),
            calles=tuple(calles),
            sectores=tuple(sectores),
            dmu_kva=dmu,
            demanda_kva=demanda_total,
            alumbrado_kva=alumbrado,
            kva_instalados=kva_instalados,
            corriente_mt_a=corriente_mt,
            tension_mt_kv=kv,
            resultados=tuple(self.resultados),
            avisos=tuple(self.avisos),
        )

    def circuitos(
        self, sector: str, grupo: list[Lote], x: float, dmu: Decimal
    ) -> tuple[Circuito, ...]:
        salida: list[Circuito] = []
        rastro = Rastro()
        limite = self.p("caida_red_bt_max_pct", rastro)
        maxima = self.p("distancia_max_secundaria_m", rastro)
        fp = self.p("factor_potencia", rastro)
        trifasico = self.sistema.fases == 3
        v = self.sistema.v_linea
        for lado, de_lado in (
            ("izquierda", [lt for lt in grupo if lt.x < x]),
            ("derecha", [lt for lt in grupo if lt.x >= x]),
        ):
            if not de_lado:
                continue
            longitud = Decimal(str(round(max(abs(lt.x - x) for lt in de_lado) + 1, 1)))
            demanda = self.demanda(len(de_lado), dmu, rastro)
            corriente = demanda * MIL / (RAIZ3 * v if trifasico else v)
            # Carga repartida a lo largo del circuito: equivale a toda la carga a la mitad.
            conductor = elegir_conductor(
                self.perfil, corriente, corriente, longitud / 2, fp, limite, "alimentador",
                trifasico, v, rastro,
            )  # fmt: skip
            if conductor is not None:
                conductor = Conductor(
                    conductor.calibre, conductor.paralelos, conductor.caida_pct, longitud,
                    conductor.r_ohm * 2, conductor.x_ohm * 2,
                )  # fmt: skip
            avisos: tuple[str, ...] = ()
            if longitud > maxima:
                avisos = (f"{sector} {lado}: circuito de {longitud} m, más que {maxima} m.",)
            if conductor is None:
                avisos += (f"{sector} {lado}: ningún conductor cumple la caída de {limite} %.",)
            self.avisos.extend(avisos)
            self.resultados.append(
                _resultado(
                    "circuito_bt",
                    f"{sector} {lado}",
                    f"Circuito de BT de {sector} hacia la {lado}",
                    conductor.texto if conductor else "sin solución",
                    "",
                    "Carga repartida: ΔV % = k × I × (L ÷ 2) × (R cos φ + X sen φ) ÷ V × 100",
                    rastro,
                    entradas={
                        "lotes": Decimal(len(de_lado)),
                        "longitud_m": longitud,
                        "corriente_a": corriente,
                    },  # fmt: skip
                    detalle={"caida_pct": conductor.caida_pct, "limite_pct": limite}
                    if conductor
                    else {"limite_pct": limite},
                    avisos=avisos,
                )
            )
            salida.append(Circuito(lado, len(de_lado), longitud, corriente, conductor))
        return tuple(salida)


def _partir(lotes: list[Lote], partes: int) -> list[list[Lote]]:
    """Grupos contiguos por x lo más parejos posible; siempre al menos un grupo."""
    if not lotes:
        return [[]]
    # Los lotes de los dos lados en el mismo tramo van juntos.
    tamano = math.ceil(len(lotes) / partes)
    return [lotes[i : i + tamano] for i in range(0, len(lotes), tamano)]


def _luminarias_de(calle: Calle, grupo: list[Lote], grupos: list[list[Lote]], g: int) -> int:
    """Luminarias de la calle en el tramo del sector (entre los cortes con los vecinos)."""
    if not grupo:
        return len(calle.luminarias)
    desde = -math.inf if g == 0 else (grupos[g - 1][-1].x + grupo[0].x) / 2
    hasta = math.inf if g == len(grupos) - 1 else (grupo[-1].x + grupos[g + 1][0].x) / 2
    return sum(1 for x in calle.luminarias if desde <= x < hasta)


def calcular_urbanizacion(u: Urbanizacion, perfil: Perfil) -> UrbanizacionCalculada:
    return _Calculo(u, perfil).calcular()
