"""Análisis de una carga industrial y factibilidad del servicio.

Del cuadro de cargas a la decisión que pide CNEL:

1. Cada máquina: potencia de entrada, corriente, demanda (factores de
   utilización y simultaneidad) y, en motores, la corriente de arranque.
2. Por tablero y total: demanda en kW, kVAr y kVA, y factor de potencia.
3. Corrección del factor de potencia con un banco de capacitores normalizado.
4. Transformador particular normalizado, con reserva, y la caída momentánea
   al arrancar el motor mayor.
5. Nivel de servicio por norma (red existente, transformador particular,
   cuarto de transformación en media tensión, subestación) y, si la norma
   admite la red existente, si el transformador de CNEL más cercano tiene
   capacidad libre, fases y una acometida con caída de tensión admisible.

Todos los valores que salen del perfil quedan en el rastro de cada resultado.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from electric.calculo.resultado import Rastro, Resultado, redondear
from electric.errores import DatoInvalido, FilaNoEncontrada
from electric.industrial.modelo import KW_POR_HP, Industria, Maquina, TransformadorExistente
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import (
    Estado,
    FilaConductor,
    FilaNivelServicio,
    FilaSistema,
    FilaTransformador,
    peor_estado,
)

CERO = Decimal(0)
UNO = Decimal(1)
CIEN = Decimal(100)
MIL = Decimal(1000)
RAIZ3 = Decimal(3).sqrt()

#: Sujeto de los resultados de toda la industria.
INDUSTRIA = "industria"
#: Sujeto de los resultados del transformador existente.
EXISTENTE = "existente"

Opcion = Literal["existente", "particular", "pendiente"]


def _t(valor: Decimal, decimales: int) -> str:
    """Número para un texto: decimales fijos y coma decimal."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def _tan(fp: Decimal) -> Decimal:
    return (UNO - fp * fp).sqrt() / fp


def _fp(kw: Decimal, kvar: Decimal) -> Decimal:
    kva = (kw * kw + kvar * kvar).sqrt()
    return kw / kva if kva > 0 else UNO


def _corriente(kva: Decimal, tension: Decimal, trifasico: bool) -> Decimal:
    return kva * MIL / (RAIZ3 * tension if trifasico else tension)


# --- Resultados por fila ---------------------------------------------------


@dataclass(frozen=True)
class FilaCuadro:
    """Una fila del cuadro de cargas ya calculada."""

    maquina: Maquina
    tipo_nombre: str
    fp: Decimal
    eficiencia: Decimal
    factor_utilizacion: Decimal
    factor_simultaneidad: Decimal
    tension_v: Decimal
    #: Potencia eléctrica de entrada de todas las unidades.
    instalada_kw: Decimal
    instalada_kva: Decimal
    #: Corriente nominal de una unidad.
    corriente_a: Decimal
    demanda_kw: Decimal
    demanda_kvar: Decimal
    arranque: str | None = None
    corriente_arranque_a: Decimal | None = None
    kva_arranque: Decimal | None = None
    #: Valores tomados del perfil porque el cuadro los dejó vacíos.
    supuestos: tuple[str, ...] = ()


@dataclass(frozen=True)
class TotalTablero:
    tablero: str
    maquinas: int
    instalada_kw: Decimal
    demanda_kw: Decimal
    demanda_kvar: Decimal
    demanda_kva: Decimal
    fp: Decimal
    corriente_a: Decimal
    #: None si la corriente supera la serie de breakers del perfil.
    breaker_a: Decimal | None


@dataclass(frozen=True)
class Comprobacion:
    """Una condición para usar el transformador existente."""

    nombre: str
    cumple: bool
    detalle: str


@dataclass(frozen=True)
class Decision:
    nivel: FilaNivelServicio
    opcion: Opcion
    titulo: str
    motivos: tuple[str, ...]
    comprobaciones: tuple[Comprobacion, ...]
    #: El transformador que se propone si la industria necesita uno particular.
    transformador: FilaTransformador | None


@dataclass(frozen=True)
class AnalisisIndustrial:
    industria: Industria
    sistema: FilaSistema
    filas: tuple[FilaCuadro, ...]
    tableros: tuple[TotalTablero, ...]
    resultados: tuple[Resultado, ...]
    decision: Decision
    avisos: tuple[str, ...]
    estado: Estado

    def resultado(self, id: str, sujeto: str = INDUSTRIA) -> Resultado:
        for r in self.resultados:
            if r.id == id and r.sujeto == sujeto:
                return r
        raise KeyError(f"{id} de {sujeto}")


# --- Cálculo ---------------------------------------------------------------


class _Analisis:
    def __init__(self, industria: Industria, perfil: Perfil) -> None:
        if not perfil.es_industrial():
            raise DatoInvalido(f"el perfil {perfil.meta.id} no tiene las tablas industriales")
        self.industria = industria
        self.perfil = perfil
        self.resultados: list[Resultado] = []
        self.avisos: list[str] = []
        rastro = Rastro()
        self.sistema = rastro.usar(perfil.sistema(industria.sistema))
        self.ref_sistema = rastro.tablas
        self.trifasico = self.sistema.fases == 3

    # -- utilidades ------------------------------------------------------

    def _agregar(
        self,
        id: str,
        nombre: str,
        valor: Decimal | str,
        unidad: str,
        formula: str,
        rastro: Rastro,
        *,
        sujeto: str = INDUSTRIA,
        entradas: dict[str, Decimal | str] | None = None,
        detalle: dict[str, Decimal | str] | None = None,
        avisos: tuple[str, ...] = (),
        previos: tuple[Resultado, ...] = (),
    ) -> Resultado:
        estados = [rastro.estado, *(p.estado for p in previos)]
        resultado = Resultado(
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
            estado=peor_estado(estados),
        )
        self.resultados.append(resultado)
        return resultado

    def _parametro(self, clave: str, rastro: Rastro) -> Decimal:
        return rastro.usar(self.perfil.parametro(clave))

    # -- 1. cuadro de cargas --------------------------------------------

    def fila(self, maquina: Maquina, rastro: Rastro) -> FilaCuadro:
        tipo = rastro.usar(self.perfil.tipo_industrial(maquina.tipo))
        supuestos: list[str] = []

        def valor(dato: Decimal | None, defecto: Decimal, nombre: str) -> Decimal:
            if dato is not None:
                return dato
            supuestos.append(f"{nombre} {defecto} típico de {tipo.nombre.lower()}")
            return defecto

        fp = valor(maquina.fp, tipo.fp, "factor de potencia")
        fu = valor(maquina.factor_utilizacion, tipo.factor_utilizacion, "factor de utilización")
        fs = valor(
            maquina.factor_simultaneidad, tipo.factor_simultaneidad, "factor de simultaneidad"
        )
        if maquina.unidad == "kVA":
            eficiencia = UNO
            entrada_kw = maquina.potencia * fp
        else:
            eficiencia = valor(maquina.eficiencia, tipo.eficiencia, "eficiencia")
            salida = maquina.potencia * (KW_POR_HP if maquina.unidad == "HP" else UNO)
            entrada_kw = salida / eficiencia

        if maquina.fases == 3 and not self.trifasico:
            raise DatoInvalido(
                f"la máquina {maquina.id} es trifásica y el sistema {self.sistema.id} no lo es"
            )
        if maquina.tension_v is not None:
            tension = maquina.tension_v
            nominal = self.sistema.v_linea if maquina.fases == 3 else self.sistema.v_fase_neutro
            if maquina.fases == 3 and tension != self.sistema.v_linea:
                self.avisos.append(
                    f"{maquina.id}: tensión de placa {tension} V distinta de la del sistema "
                    f"({nominal} V); necesita un transformador de aislamiento o cambiar el sistema"
                )
        else:
            tension = self.sistema.v_linea if maquina.fases == 3 else self.sistema.v_fase_neutro

        kva_unidad = entrada_kw / fp
        corriente = _corriente(kva_unidad, tension, maquina.fases == 3)
        instalada_kw = entrada_kw * maquina.cantidad
        demanda_kw = instalada_kw * fu * fs

        arranque = None
        i_arr = None
        kva_arr = None
        if maquina.tipo == "motor":
            arranque = maquina.arranque or "directo"
            if maquina.arranque is None:
                supuestos.append("arranque directo")
            metodo = rastro.usar(self.perfil.arranque(arranque))
            i_arr = corriente * metodo.multiplicador
            kva_arr = kva_unidad * metodo.multiplicador
        elif maquina.arranque is not None:
            raise DatoInvalido(f"{maquina.id}: solo los motores llevan método de arranque")

        return FilaCuadro(
            maquina=maquina,
            tipo_nombre=tipo.nombre,
            fp=fp,
            eficiencia=eficiencia,
            factor_utilizacion=fu,
            factor_simultaneidad=fs,
            tension_v=tension,
            instalada_kw=instalada_kw,
            instalada_kva=kva_unidad * maquina.cantidad,
            corriente_a=corriente,
            demanda_kw=demanda_kw,
            demanda_kvar=demanda_kw * _tan(fp),
            arranque=arranque,
            corriente_arranque_a=i_arr,
            kva_arranque=kva_arr,
            supuestos=tuple(supuestos),
        )

    # -- 2. tableros y total --------------------------------------------

    def _breaker(self, corriente: Decimal, rastro: Rastro) -> Decimal | None:
        """Breaker normalizado, o None si la corriente supera la serie del perfil."""
        factor = self._parametro("factor_diseno_conductor", rastro)
        try:
            return rastro.usar(self.perfil.normalizado("breakers", corriente * factor))
        except FilaNoEncontrada:
            return None

    def tableros(self, filas: list[FilaCuadro], rastro: Rastro) -> list[TotalTablero]:
        grupos: dict[str, list[FilaCuadro]] = defaultdict(list)
        for fila in filas:
            grupos[fila.maquina.tablero].append(fila)
        salida = []
        for nombre, grupo in grupos.items():
            kw = sum((f.demanda_kw for f in grupo), CERO)
            kvar = sum((f.demanda_kvar for f in grupo), CERO)
            kva = (kw * kw + kvar * kvar).sqrt()
            corriente = _corriente(kva, self._tension_alimentacion(), self.trifasico)
            salida.append(
                TotalTablero(
                    tablero=nombre,
                    maquinas=sum(f.maquina.cantidad for f in grupo),
                    instalada_kw=sum((f.instalada_kw for f in grupo), CERO),
                    demanda_kw=kw,
                    demanda_kvar=kvar,
                    demanda_kva=kva,
                    fp=_fp(kw, kvar),
                    corriente_a=corriente,
                    breaker_a=self._breaker(corriente, rastro),
                )
            )
        return salida

    def _tension_alimentacion(self) -> Decimal:
        return self.sistema.v_linea

    # -- 5. acometida desde un transformador existente -------------------

    def acometida(
        self, corriente: Decimal, longitud_m: Decimal, fp: Decimal, rastro: Rastro
    ) -> tuple[FilaConductor, int, Decimal] | None:
        """Menor conductor (con paralelos) que lleva la corriente con caída admisible."""
        filas, tabla = self.perfil.conductores()
        factor = self._parametro("factor_diseno_conductor", rastro)
        limite = self._parametro("caida_total_max_pct", rastro)
        paralelos = int(self._parametro("conductores_paralelo_max", rastro))
        requerida = corriente * factor
        seno = (UNO - fp * fp).sqrt()
        k = RAIZ3 if self.trifasico else Decimal(2)
        tension = self._tension_alimentacion()
        minimo = rastro.usar(self.perfil.minimo_calibre("alimentador")).calibre
        desde = next(n for n, f in enumerate(filas) if f.calibre == minimo)
        for n in range(1, paralelos + 1):
            for fila in filas[desde:]:
                if fila.ampacidad * n < requerida:
                    continue
                impedancia = fila.r_ohm_km * fp + fila.x_ohm_km * seno
                caida = k * corriente * longitud_m / MIL * impedancia / n / tension * CIEN
                if caida <= limite:
                    rastro.anotar(self.perfil._ref(tabla, fila.calibre))
                    return fila, n, caida
        return None


def analizar(industria: Industria, perfil: Perfil) -> AnalisisIndustrial:
    """Cuadro de cargas, transformador y factibilidad de servicio de una industria."""
    a = _Analisis(industria, perfil)

    # 1. Cuadro de cargas.
    r_cuadro = Rastro()
    r_cuadro.anotar(*a.ref_sistema)
    filas = [a.fila(m, r_cuadro) for m in industria.maquinas]
    for fila in filas:
        for supuesto in fila.supuestos:
            r_cuadro.supuesto(f"{fila.maquina.id}: {supuesto}")

    instalada = sum((f.instalada_kw for f in filas), CERO)
    kw = sum((f.demanda_kw for f in filas), CERO)
    kvar = sum((f.demanda_kvar for f in filas), CERO)
    kva = (kw * kw + kvar * kvar).sqrt()
    fp_actual = _fp(kw, kvar)

    a._agregar(
        "instalada",
        "Potencia instalada",
        instalada,
        "kW",
        "Σ cantidad × potencia de placa ÷ eficiencia",
        r_cuadro,
        detalle={"maquinas": Decimal(sum(f.maquina.cantidad for f in filas))},
    )
    r_demanda = Rastro()
    r_demanda.anotar(*r_cuadro.tablas)
    demanda = a._agregar(
        "demanda",
        "Demanda máxima",
        kw,
        "kW",
        "Σ potencia instalada × factor de utilización × factor de simultaneidad",
        r_demanda,
        detalle={
            "kvar": kvar,
            "kva": kva,
            "factor_demanda": kw / instalada if instalada > 0 else CERO,
        },
    )
    tableros = a.tableros(filas, r_demanda)

    # 3. Factor de potencia.
    r_fp = Rastro()
    objetivo = industria.fp_objetivo or a._parametro("fp_objetivo", r_fp)
    if industria.fp_objetivo is not None:
        r_fp.supuesto(f"factor de potencia objetivo {objetivo} indicado por el proyectista")
    banco = CERO
    requerido = CERO
    if fp_actual < objetivo:
        requerido = kw * (_tan(fp_actual) - _tan(objetivo))
        try:
            banco = r_fp.usar(perfil.normalizado("capacitores_kvar", requerido))
        except FilaNoEncontrada:
            banco = requerido
            a.avisos.append(
                f"El banco de capacitores ({_t(requerido, 0)} kVAr) supera la serie normalizada; "
                "se divide en varios bancos."
            )
    kvar_corr = max(kvar - banco, CERO)
    kva_corr = (kw * kw + kvar_corr * kvar_corr).sqrt()
    fp_corr = _fp(kw, kvar_corr)
    a._agregar(
        "factor_potencia",
        "Factor de potencia",
        redondear(fp_corr, 3),
        "",
        "Qc = P × (tan φ actual − tan φ objetivo); FP = P ÷ √(P² + (Q − Qc)²)",
        r_fp,
        entradas={"fp_sin_corregir": redondear(fp_actual, 3), "fp_objetivo": objetivo},
        detalle={"banco_kvar": banco, "requerido_kvar": requerido, "kva_corregida": kva_corr},
        previos=(demanda,),
        avisos=(
            (
                f"Banco de capacitores de {banco} kVAr para pasar de FP {_t(fp_actual, 2)} "
                f"a {_t(fp_corr, 2)}.",
            )
            if banco > 0
            else ()
        ),
    )

    # 4. Transformador particular.
    r_tr = Rastro()
    reserva = a._parametro("reserva_transformador_pct", r_tr)
    kva_req = kva_corr * (UNO + reserva / CIEN)
    fases = 3 if a.trifasico else 1
    propuesto: FilaTransformador | None
    try:
        propuesto = r_tr.usar(perfil.transformador_para(kva_req, fases))
    except FilaNoEncontrada:
        propuesto = None
        a.avisos.append(
            f"La demanda con reserva ({_t(kva_req, 0)} kVA) supera el mayor transformador de la "
            "tabla; se necesitan varios transformadores o una subestación."
        )
    transformador = a._agregar(
        "transformador",
        "Transformador particular",
        propuesto.kva if propuesto else "fuera de tabla",
        "kVA" if propuesto else "",
        "kVA requerido = kVA corregida × (1 + reserva); el normalizado inmediato superior",
        r_tr,
        entradas={"kva_corregida": kva_corr, "reserva_pct": reserva},
        detalle=(
            {"kva_requerido": kva_req, "montaje": propuesto.montaje, "z_pct": propuesto.z_pct}
            if propuesto
            else {"kva_requerido": kva_req}
        ),
        previos=(demanda,),
    )

    r_pr = Rastro()
    corriente_total = _corriente(kva_corr, a._tension_alimentacion(), a.trifasico)
    breaker = a._breaker(corriente_total, r_pr)
    if breaker is None:
        a.avisos.append(
            f"La corriente en baja tensión ({_t(corriente_total, 0)} A) supera la serie de "
            "breakers; la protección principal va en media tensión o se reparte en varios "
            "transformadores."
        )
    a._agregar(
        "breaker_principal",
        "Breaker principal",
        breaker if breaker is not None else "fuera de serie",
        "A" if breaker is not None else "",
        "I = kVA corregida ÷ (√3 × V) × factor de diseño; normalizado superior",
        r_pr,
        entradas={"corriente_a": corriente_total},
        detalle=(
            {"medidor": r_pr.usar(perfil.medidor(breaker)).clase} if breaker is not None else {}
        ),
        previos=(transformador,),
    )

    # Arranque del motor mayor.
    motores = [f for f in filas if f.kva_arranque is not None]
    mayor = max(motores, key=lambda f: f.kva_arranque or CERO, default=None)
    limite_arr = a._parametro("caida_arranque_max_pct", Rastro())
    if mayor is not None and mayor.kva_arranque is not None and propuesto is not None:
        r_arr = Rastro()
        limite_arr = a._parametro("caida_arranque_max_pct", r_arr)
        caida = _caida_arranque(mayor.kva_arranque, propuesto.kva, propuesto.z_pct)
        avisos: tuple[str, ...] = ()
        if caida > limite_arr:
            avisos = (
                f"Al arrancar {mayor.maquina.id} la tensión cae {_t(caida, 1)} % (límite "
                f"{limite_arr} %). Use arrancador suave o variador.",
            )
        a._agregar(
            "arranque",
            "Caída al arrancar el motor mayor",
            caida,
            "%",
            "ΔV = S arranque ÷ (S cortocircuito + S arranque); S cc = kVA ÷ Z",
            r_arr,
            entradas={
                "motor": mayor.maquina.id,
                "kva_arranque": mayor.kva_arranque,
                "metodo": mayor.arranque or "",
            },
            avisos=avisos,
            previos=(transformador,),
        )

    # 5. Nivel de servicio y transformador existente.
    r_niv = Rastro()
    nivel = r_niv.usar(perfil.nivel_servicio(kw))
    a._agregar(
        "nivel_servicio",
        "Nivel de servicio por norma",
        nivel.nombre,
        "",
        "Primer nivel cuya demanda máxima cubre la demanda de la industria",
        r_niv,
        entradas={"demanda_kw": kw},
        detalle={"medicion": nivel.medicion.upper()},
        previos=(demanda,),
    )
    decision = _decidir(a, nivel, kw, kva_corr, fp_corr, mayor, propuesto, limite_arr)

    estado = peor_estado([r.estado for r in a.resultados])
    return AnalisisIndustrial(
        industria=industria,
        sistema=a.sistema,
        filas=tuple(filas),
        tableros=tuple(tableros),
        resultados=tuple(a.resultados),
        decision=decision,
        avisos=tuple(a.avisos),
        estado=estado,
    )


def _caida_arranque(kva_arranque: Decimal, kva_trafo: Decimal, z_pct: Decimal) -> Decimal:
    cortocircuito = kva_trafo * CIEN / z_pct
    return kva_arranque / (cortocircuito + kva_arranque) * CIEN


def _demanda_existente(
    a: _Analisis, existente: TransformadorExistente, rastro: Rastro
) -> tuple[Decimal, str]:
    if existente.demanda_kva is not None:
        rastro.supuesto("demanda actual medida entregada por CNEL")
        return existente.demanda_kva, "medida"
    if not existente.clientes:
        raise DatoInvalido(
            "falta la demanda actual del transformador existente o sus clientes por estrato"
        )
    total = CERO
    for estrato, n in existente.clientes.items():
        total += rastro.usar(a.perfil.estrato(estrato)).kva * n
    return total, "estimada por clientes"


def _limite_red(a: _Analisis) -> str:
    for nivel in a.perfil.niveles_servicio():
        if nivel.id == "red_existente" and nivel.demanda_max_kw is not None:
            return _t(nivel.demanda_max_kw, 0)
    return "?"


def _decidir(
    a: _Analisis,
    nivel: FilaNivelServicio,
    kw: Decimal,
    kva: Decimal,
    fp: Decimal,
    mayor: FilaCuadro | None,
    propuesto: FilaTransformador | None,
    limite_arranque: Decimal,
) -> Decision:
    existente = a.industria.existente
    if nivel.id in ("cuarto_mt", "subestacion"):
        motivo = (
            f"Con {_t(kw, 1)} kW de demanda corresponde: {nivel.nombre.lower()} "
            f"(medición en {nivel.medicion.upper()})."
        )
        return Decision(
            nivel=nivel,
            opcion="particular",
            titulo=nivel.nombre,
            motivos=(motivo, nivel.descripcion) if nivel.descripcion else (motivo,),
            comprobaciones=(),
            transformador=propuesto,
        )
    if existente is None:
        if nivel.id == "red_existente":
            return Decision(
                nivel=nivel,
                opcion="pendiente",
                titulo="Falta el transformador existente",
                motivos=(
                    "Hasta este nivel la distribuidora atiende en bajo voltaje desde su red. "
                    "Indique el transformador de CNEL más cercano para comprobar su capacidad.",
                ),
                comprobaciones=(),
                transformador=propuesto,
            )
        return Decision(
            nivel=nivel,
            opcion="particular",
            titulo="Transformador particular",
            motivos=(
                f"Con {_t(kw, 1)} kW la distribuidora decide el punto de entrega tras el "
                "análisis de factibilidad. Sin un transformador existente indicado se propone "
                "uno particular.",
            ),
            comprobaciones=(),
            transformador=propuesto,
        )

    rastro = Rastro()
    comprobaciones: list[Comprobacion] = []

    trifasica = any(m.fases == 3 for m in a.industria.maquinas)
    comprobaciones.append(
        Comprobacion(
            "Fases",
            not (trifasica and existente.fases == 1),
            f"La industria tiene cargas {'trifásicas' if trifasica else 'monofásicas'}; "
            f"el transformador es {'trifásico' if existente.fases == 3 else 'monofásico'}.",
        )
    )

    actual, origen = _demanda_existente(a, existente, rastro)
    cargabilidad = a._parametro("cargabilidad_max_existente_pct", rastro)
    libre = existente.kva * cargabilidad / CIEN - actual
    a._agregar(
        "capacidad_libre",
        "Capacidad libre del transformador existente",
        libre,
        "kVA",
        "kVA nominal × cargabilidad máxima − demanda actual",
        rastro,
        sujeto=EXISTENTE,
        entradas={
            "kva_nominal": existente.kva,
            "demanda_actual_kva": actual,
            "origen_demanda": origen,
            "cargabilidad_pct": cargabilidad,
        },
    )
    comprobaciones.append(
        Comprobacion(
            "Capacidad",
            libre >= kva,
            (
                f"Libre {_t(libre, 1)} kVA (demanda actual {origen} {_t(actual, 1)} kVA); "
                if libre > 0
                else f"Sin capacidad libre: la demanda actual {origen} es {_t(actual, 1)} kVA; "
            )
            + f"la industria necesita {_t(kva, 1)} kVA.",
        )
    )

    r_ac = Rastro()
    distancia_max = a._parametro("distancia_max_secundaria_m", r_ac)
    comprobaciones.append(
        Comprobacion(
            "Distancia",
            existente.distancia_m <= distancia_max,
            f"Acometida de {existente.distancia_m} m; máximo {distancia_max} m en baja tensión.",
        )
    )
    corriente = _corriente(kva, a._tension_alimentacion(), a.trifasico)
    acometida = a.acometida(corriente, existente.distancia_m, fp, r_ac)
    if acometida is None:
        detalle = "Ningún conductor de la tabla, aun en paralelo, deja la caída bajo el límite."
    else:
        fila, n, caida = acometida
        conductor = f"{n} × {fila.calibre}" if n > 1 else fila.calibre
        detalle = f"Acometida de {conductor} por fase, caída {_t(caida, 2)} %."
        a._agregar(
            "acometida",
            "Acometida desde el transformador existente",
            conductor,
            "",
            "ΔV % = k × I × L × (R cos φ + X sen φ) ÷ (n × V) × 100",
            r_ac,
            sujeto=EXISTENTE,
            entradas={"corriente_a": corriente, "longitud_m": existente.distancia_m},
            detalle={"caida_pct": caida},
        )
    comprobaciones.append(Comprobacion("Caída de tensión", acometida is not None, detalle))

    if mayor is not None and mayor.kva_arranque is not None:
        r_z = Rastro()
        z = existente.impedancia_pct or r_z.usar(
            a.perfil.impedancia_transformador(existente.kva, existente.fases)
        )
        caida = _caida_arranque(mayor.kva_arranque, existente.kva, z)
        comprobaciones.append(
            Comprobacion(
                "Arranque de motores",
                caida <= limite_arranque,
                f"Al arrancar {mayor.maquina.id} la tensión del transformador cae {_t(caida, 1)} % "
                f"(límite {limite_arranque} %)"
                + ("." if caida <= limite_arranque else "; afectaría a los demás clientes."),
            )
        )

    fallan = [c for c in comprobaciones if not c.cumple]
    if fallan:
        return Decision(
            nivel=nivel,
            opcion="particular",
            titulo="Transformador particular",
            motivos=tuple(f"{c.nombre}: {c.detalle}" for c in fallan),
            comprobaciones=tuple(comprobaciones),
            transformador=propuesto,
        )
    codigo = f" {existente.codigo}" if existente.codigo else ""
    return Decision(
        nivel=nivel,
        opcion="existente",
        titulo=f"Usar el transformador existente{codigo}",
        motivos=(
            ("Cumple fases, capacidad, distancia, caída de tensión y arranque.",)
            if nivel.id == "red_existente"
            else (
                "Cumple fases, capacidad, distancia, caída de tensión y arranque.",
                f"Con más de {_limite_red(a)} kW la conexión queda sujeta al análisis de "
                "factibilidad que emite la distribuidora.",
            )
        ),
        comprobaciones=tuple(comprobaciones),
        transformador=None,
    )
