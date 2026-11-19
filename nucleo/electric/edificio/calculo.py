"""Cálculo de un edificio: demanda con factor de coincidencia, nivel de servicio,
transformador, centro de medición, alimentadores de las unidades y respaldo."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from electric.calculo.resultado import Rastro, Resultado, redondear
from electric.edificio.modelo import Edificio, TipoUnidad
from electric.errores import DatoInvalido, FilaNoEncontrada
from electric.industrial.analisis import _t
from electric.industrial.estudios import Conductor, _resultado, elegir_conductor
from electric.mt.camara import Camara, disenar_camara
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import (
    Estado,
    FilaNivelServicio,
    FilaSistema,
    FilaTransformador,
    peor_estado,
)

RAIZ3 = Decimal(3).sqrt()
MIL = Decimal(1000)
CIEN = Decimal(100)
PROYECTO = "edificio"
#: Sujeto de los resultados de servicios generales.
SG = "SG"


@dataclass(frozen=True)
class UnidadCalculada:
    id: str
    tipo: str
    uso: str
    piso: int
    fases: int
    demanda_kva: Decimal
    corriente_a: Decimal
    breaker_a: Decimal | None
    medidor: str
    conductor: Conductor | None
    longitud_m: Decimal


@dataclass(frozen=True)
class GrupoDemanda:
    nombre: str
    usuarios: int
    suma_kva: Decimal
    factor: Decimal
    demanda_kva: Decimal


@dataclass(frozen=True)
class ServiciosGenerales:
    instalada_kva: Decimal
    demanda_kva: Decimal
    corriente_a: Decimal
    breaker_a: Decimal | None
    medidor: str
    conductor: Conductor | None


@dataclass(frozen=True)
class Principal:
    corriente_a: Decimal
    breaker_a: Decimal | None
    conductor: Conductor | None
    barra_a: Decimal | None
    icc_ka: Decimal | None


@dataclass(frozen=True)
class Generador:
    alcance: str
    carga_kva: Decimal
    kva: Decimal | None
    transferencia_a: Decimal | None


@dataclass(frozen=True)
class EdificioCalculado:
    edificio: Edificio
    sistema: FilaSistema
    unidades: tuple[UnidadCalculada, ...]
    grupos: tuple[GrupoDemanda, ...]
    servicios: ServiciosGenerales | None
    demanda_kva: Decimal
    demanda_kw: Decimal
    nivel: FilaNivelServicio
    transformador: FilaTransformador | None
    camara: Camara | None
    principal: Principal
    medidores: int
    modulos: int
    generador: Generador | None
    resultados: tuple[Resultado, ...]
    avisos: tuple[str, ...]

    @property
    def estado(self) -> Estado:
        return peor_estado([r.estado for r in self.resultados])

    def resultado(self, id: str, sujeto: str = PROYECTO) -> Resultado:
        return next(r for r in self.resultados if r.id == id and r.sujeto == sujeto)


def id_unidad(piso: int, n: int) -> str:
    """101, 102… por piso; PB-01 en planta baja y S1-01 en subsuelos."""
    if piso == 0:
        return f"PB-{n:02d}"
    if piso < 0:
        return f"S{-piso}-{n:02d}"
    return f"{piso}{n:02d}"


def _grupo(uso: str) -> str:
    return "Departamentos" if uso == "departamento" else "Locales y oficinas"


class _Calculo:
    def __init__(self, edificio: Edificio, perfil: Perfil) -> None:
        self.e = edificio
        self.perfil = perfil
        self.sistema, self.ref_sistema = perfil.sistema(edificio.sistema)
        if self.sistema.fases != 3:
            raise DatoInvalido("un edificio se diseña con un sistema trifásico")
        self.v = self.sistema.v_linea
        self.vf = self.sistema.v_fase_neutro
        self.resultados: list[Resultado] = []
        self.avisos: list[str] = []

    def p(self, clave: str, rastro: Rastro) -> Decimal:
        return rastro.usar(self.perfil.parametro(clave))

    def breaker(self, minimo: Decimal, rastro: Rastro) -> Decimal | None:
        try:
            return rastro.usar(self.perfil.normalizado("breakers", minimo))
        except FilaNoEncontrada:
            return None

    def dato(self, valor: Decimal | None, clave: str, texto: str, rastro: Rastro) -> Decimal:
        if valor is not None:
            return valor
        supuesto = self.p(clave, rastro)
        rastro.supuesto(f"{texto}: {_t(supuesto, 1)} m")
        return supuesto

    # -- demanda de cada tipo de unidad ------------------------------------

    def demanda_tipo(self, tipo: TipoUnidad) -> Decimal:
        rastro = Rastro()
        if tipo.demanda_kva is not None:
            formula = "Demanda de diseño indicada para la unidad"
            valor = tipo.demanda_kva
            entradas: dict[str, Decimal | str] = {}
        elif tipo.uso == "departamento":
            fila = rastro.usar(self.perfil.demanda_usuario(tipo.estrato))
            if fila.kva is None:
                raise DatoInvalido(f"el tipo de usuario {tipo.estrato} no tiene DMU en kVA")
            valor = fila.kva
            formula = f"DMU del usuario tipo {tipo.estrato}"
            entradas = {"estrato": tipo.estrato}
        else:
            fila = rastro.usar(self.perfil.demanda_usuario(tipo.uso))
            if tipo.area_m2 is None:
                raise DatoInvalido(f"{tipo.id}: indique el área útil o la demanda de la unidad")
            if fila.va_m2 is None:
                raise DatoInvalido(f"el uso {tipo.uso} no tiene densidad de carga en VA/m²")
            valor = tipo.area_m2 * fila.va_m2 * fila.factor_demanda / MIL
            formula = "Demanda = área × densidad de carga × factor de demanda"
            entradas = {
                "area_m2": tipo.area_m2,
                "va_m2": fila.va_m2,
                "factor_demanda": fila.factor_demanda,
            }
        self.resultados.append(
            _resultado(
                "demanda_unidad",
                tipo.id,
                f"Demanda de {tipo.id}",
                valor,
                "kVA",
                formula,
                rastro,
                entradas,
            )  # fmt: skip
        )
        return valor

    # -- alimentador de una unidad -----------------------------------------

    def unidad(self, tipo: TipoUnidad, piso: int, n: int, kva: Decimal) -> UnidadCalculada:
        rastro = Rastro()
        uid = id_unidad(piso, n)
        altura = self.dato(self.e.altura_piso_m, "altura_piso_m", "altura entre pisos", rastro)
        horizontal = self.dato(
            self.e.recorrido_horizontal_m,
            "recorrido_horizontal_m",
            "recorrido horizontal hasta el tablero de la unidad",
            rastro,
        )
        longitud = abs(piso - self.e.nivel_medidores) * altura + horizontal
        if tipo.fases == 3:
            corriente, tension, k = kva * MIL / (RAIZ3 * self.v), self.v, RAIZ3
        elif tipo.fases == 2:
            corriente, tension, k = kva * MIL / self.v, self.v, Decimal(2)
        else:
            corriente, tension, k = kva * MIL / self.vf, self.vf, Decimal(2)
        factor = self.p("factor_diseno_conductor", rastro)
        minimo = max(corriente * factor, self.p("principal_min_a", rastro))
        breaker = self.breaker(minimo, rastro)
        medidor = rastro.usar(self.perfil.medidor(breaker or minimo)).clase
        limite = (self.p("caida_total_max_pct", rastro) - self.p("caida_ramal_max_pct", rastro)) / 2
        fp = self.p("factor_potencia", rastro)
        conductor = elegir_conductor(
            self.perfil, corriente, max(minimo, breaker or minimo), longitud, fp, limite,
            "alimentador", tipo.fases == 3, tension, rastro, k,
        )  # fmt: skip
        avisos: tuple[str, ...] = ()
        if conductor is None:
            avisos = (f"{uid}: ningún conductor cumple la caída de {_t(limite, 1)} %.",)
            self.avisos.extend(avisos)
        self.resultados.append(
            _resultado(
                "alimentador_unidad",
                uid,
                f"Alimentador de la unidad {uid}",
                conductor.texto if conductor else "sin solución",
                "",
                "Breaker ≥ 125 % de I; conductor con ampacidad ≥ breaker y ΔV % = k × I × L × "
                "(R cos φ + X sen φ) ÷ V × 100 bajo la mitad del margen de alimentadores",
                rastro,
                entradas={"demanda_kva": kva, "corriente_a": corriente, "longitud_m": longitud},
                detalle=(
                    {
                        "breaker_a": breaker or "fuera de serie",
                        "caida_pct": conductor.caida_pct,
                        "limite_pct": limite,
                        "medidor": medidor,
                    }
                    if conductor
                    else {"limite_pct": limite}
                ),  # fmt: skip
                avisos=avisos,
            )
        )
        return UnidadCalculada(
            id=uid,
            tipo=tipo.id,
            uso=tipo.uso,
            piso=piso,
            fases=tipo.fases,
            demanda_kva=kva,
            corriente_a=corriente,
            breaker_a=breaker,
            medidor=medidor,
            conductor=conductor,
            longitud_m=longitud,
        )

    # -- servicios generales -------------------------------------------------

    def servicios(self) -> ServiciosGenerales | None:
        if not self.e.servicios:
            return None
        rastro = Rastro()
        instalada = sum((c.kw * c.cantidad / c.fp for c in self.e.servicios), Decimal(0))
        fd = self.p("factor_demanda_servicios_generales", rastro)
        motores = [c.kw / c.fp for c in self.e.servicios if c.motor]
        mayor = max(motores, default=Decimal(0))
        demanda = instalada * fd + mayor * Decimal("0.25")
        corriente = demanda * MIL / (RAIZ3 * self.v)
        factor = self.p("factor_diseno_conductor", rastro)
        breaker = self.breaker(corriente * factor, rastro)
        medidor = rastro.usar(self.perfil.medidor(breaker or corriente * factor)).clase
        longitud = self.dato(
            self.e.recorrido_horizontal_m,
            "recorrido_horizontal_m",
            "recorrido al tablero de servicios generales",
            rastro,
        )
        limite = (self.p("caida_total_max_pct", rastro) - self.p("caida_ramal_max_pct", rastro)) / 2
        conductor = elegir_conductor(
            self.perfil, corriente, max(corriente * factor, breaker or Decimal(0)), longitud,
            self.p("factor_potencia", rastro), limite, "alimentador", True, self.v, rastro,
        )  # fmt: skip
        self.resultados.append(
            _resultado(
                "demanda_servicios",
                SG,
                "Demanda de servicios generales",
                demanda,
                "kVA",
                "D = Σ (kW × n ÷ fp) × fd + 25 % del motor mayor",
                rastro,
                entradas={
                    "instalada_kva": instalada,
                    "factor_demanda": fd,
                    "motor_mayor_kva": mayor,
                },  # fmt: skip
                detalle={
                    "corriente_a": corriente,
                    "breaker_a": breaker or "fuera de serie",
                    "conductor": conductor.texto if conductor else "sin solución",
                    "medidor": medidor,
                },
            )
        )
        return ServiciosGenerales(instalada, demanda, corriente, breaker, medidor, conductor)

    # -- conjunto ---------------------------------------------------------------

    def calcular(self) -> EdificioCalculado:
        e = self.e
        unidades: list[UnidadCalculada] = []
        por_piso: dict[int, int] = {}
        demandas = {t.id: self.demanda_tipo(t) for t in e.unidades}
        for tipo in e.unidades:
            for piso in tipo.pisos:
                for _ in range(tipo.por_piso):
                    por_piso[piso] = por_piso.get(piso, 0) + 1
                    unidades.append(self.unidad(tipo, piso, por_piso[piso], demandas[tipo.id]))
        unidades.sort(key=lambda u: (u.piso, u.id))

        # Coincidencia por grupo de usuarios del mismo tipo de uso.
        grupos: list[GrupoDemanda] = []
        for nombre in ("Departamentos", "Locales y oficinas"):
            del_grupo = [u for u in unidades if _grupo(u.uso) == nombre]
            if not del_grupo:
                continue
            rastro = Rastro()
            suma = sum((u.demanda_kva for u in del_grupo), Decimal(0))
            factor = rastro.usar(self.perfil.coincidencia(len(del_grupo)))
            demanda = suma * factor
            grupos.append(GrupoDemanda(nombre, len(del_grupo), suma, factor, demanda))
            self.resultados.append(
                _resultado(
                    "demanda_grupo",
                    nombre,
                    f"Demanda coincidente de {nombre.lower()}",
                    demanda,
                    "kVA",
                    "D = Σ demandas × factor de coincidencia (N usuarios)",
                    rastro,
                    entradas={
                        "usuarios": Decimal(len(del_grupo)),
                        "suma_kva": suma,
                        "factor": factor,
                    },  # fmt: skip
                )
            )
        servicios = self.servicios()

        rastro = Rastro()
        total = sum((g.demanda_kva for g in grupos), Decimal(0)) + (
            servicios.demanda_kva if servicios else Decimal(0)
        )
        fp = self.p("factor_potencia", rastro)
        kw = total * fp
        nivel = rastro.usar(self.perfil.nivel_servicio(kw))
        self.resultados.append(
            _resultado(
                "demanda_total",
                PROYECTO,
                "Demanda del edificio",
                total,
                "kVA",
                "D = Σ demandas coincidentes de los grupos + servicios generales",
                rastro,
                entradas={"fp": fp},
                detalle={"demanda_kw": kw, "nivel": nivel.nombre},
            )
        )

        transformador: FilaTransformador | None = None
        camara: Camara | None = None
        if nivel.id != "red_existente":
            rastro = Rastro()
            reserva = self.p("reserva_transformador_pct", rastro)
            requerida = total * (1 + reserva / CIEN)
            try:
                transformador = rastro.usar(self.perfil.transformador_para(requerida, 3))
            except FilaNoEncontrada:
                self.avisos.append(
                    f"Ningún transformador normalizado cubre {_t(requerida, 0)} kVA; "
                    "el edificio necesita varios transformadores o una subestación."
                )
            if transformador is not None:
                self.resultados.append(
                    _resultado(
                        "transformador",
                        PROYECTO,
                        "Transformador del edificio",
                        transformador.kva,
                        "kVA",
                        "Menor transformador trifásico normalizado ≥ D × (1 + reserva)",
                        rastro,
                        entradas={"demanda_kva": total, "reserva_pct": reserva},
                        detalle={"requerida_kva": requerida, "montaje": transformador.montaje},
                    )
                )
                if transformador.montaje == "cuarto" or nivel.medicion == "mt":
                    camara = disenar_camara(
                        transformador.kva,
                        self.perfil,
                        v_bt=self.v,
                        resistividad_ohm_m=e.resistividad_ohm_m,
                    )
                    self.resultados.extend(camara.resultados)
                    self.avisos.extend(camara.avisos)
        else:
            self.avisos.append(
                "La demanda permite atender el edificio desde la red de CNEL en baja tensión, "
                "sujeto a la factibilidad del transformador existente."
            )

        principal = self.principal(total, transformador)
        medidores = len(unidades) + (1 if servicios else 0)
        rastro = Rastro()
        por_modulo = int(self.p("medidores_por_modulo", rastro))
        modulos = math.ceil(medidores / por_modulo)
        self.resultados.append(
            _resultado(
                "centro_medicion",
                PROYECTO,
                "Centro de medición",
                f"{medidores} medidores en {modulos} módulo{'s' if modulos > 1 else ''}",
                "",
                "Un medidor por unidad y uno de servicios generales; módulos de "
                f"{por_modulo} medidores",
                rastro,
                entradas={"medidores": Decimal(medidores)},
            )
        )
        generador = self.generador(total, servicios)
        return EdificioCalculado(
            edificio=e,
            sistema=self.sistema,
            unidades=tuple(unidades),
            grupos=tuple(grupos),
            servicios=servicios,
            demanda_kva=total,
            demanda_kw=kw,
            nivel=nivel,
            transformador=transformador,
            camara=camara,
            principal=principal,
            medidores=medidores,
            modulos=modulos,
            generador=generador,
            resultados=tuple(self.resultados),
            avisos=tuple(self.avisos),
        )

    def principal(self, total: Decimal, transformador: FilaTransformador | None) -> Principal:
        rastro = Rastro()
        corriente = total * MIL / (RAIZ3 * self.v)
        factor = self.p("factor_diseno_conductor", rastro)
        breaker = self.breaker(corriente * factor, rastro)
        try:
            barra = rastro.usar(self.perfil.normalizado("barras", breaker or corriente * factor))
        except FilaNoEncontrada:
            barra = None
        longitud = self.dato(
            self.e.distancia_transformador_m,
            "distancia_transformador_defecto_m",
            "distancia del transformador al centro de medición",
            rastro,
        )
        limite = (self.p("caida_total_max_pct", rastro) - self.p("caida_ramal_max_pct", rastro)) / 2
        conductor = elegir_conductor(
            self.perfil, corriente, max(corriente * factor, breaker or Decimal(0)), longitud,
            self.p("factor_potencia", rastro), limite, "alimentador", True, self.v, rastro,
        )  # fmt: skip
        icc = None
        if transformador is not None:
            # Barra infinita del lado de MT: Icc = In ÷ Z.
            icc = transformador.kva * MIL / (RAIZ3 * self.v) / (transformador.z_pct / CIEN) / MIL
        avisos: tuple[str, ...] = ()
        if breaker is None:
            avisos = (f"La corriente de {_t(corriente, 0)} A excede la serie de breakers.",)
            self.avisos.extend(avisos)
        self.resultados.append(
            _resultado(
                "principal",
                PROYECTO,
                "Acometida y breaker principal del centro de medición",
                conductor.texto if conductor else "sin solución",
                "",
                "I = D ÷ (√3 × V); breaker ≥ 125 % de I; conductor por ampacidad y caída "
                "(mitad del margen de alimentadores)",
                rastro,
                entradas={"demanda_kva": total, "longitud_m": longitud},
                detalle={
                    "corriente_a": corriente,
                    "breaker_a": breaker or "fuera de serie",
                    "barra_a": barra or "fuera de serie",
                    **({"icc_ka": redondear(icc, 2)} if icc is not None else {}),
                },
                avisos=avisos,
            )
        )
        return Principal(corriente, breaker, conductor, barra, icc)

    def generador(self, total: Decimal, servicios: ServiciosGenerales | None) -> Generador | None:
        e = self.e
        if e.respaldo == "ninguno":
            return None
        rastro = Rastro()
        if e.respaldo == "total":
            carga = total
            alcance = "todo el edificio"
        else:
            if servicios is None:
                self.avisos.append("El respaldo de servicios generales no tiene cargas.")
                return None
            fd = self.p("factor_demanda_servicios_generales", rastro)
            carga = (
                sum((c.kw * c.cantidad / c.fp for c in e.servicios if c.respaldo), Decimal(0)) * fd
            )
            alcance = "servicios generales"
        maximo = self.p("carga_generador_max", rastro)
        try:
            kva: Decimal | None = rastro.usar(
                self.perfil.normalizado("generadores_kva", carga / maximo)
            )
        except FilaNoEncontrada:
            kva = None
        transferencia = (
            self.breaker(kva * MIL / (RAIZ3 * self.v), rastro) if kva is not None else None
        )
        self.resultados.append(
            _resultado(
                "generador",
                PROYECTO,
                f"Generador de respaldo ({alcance})",
                kva if kva is not None else "fuera de serie",
                "kVA",
                "Menor generador normalizado ≥ carga respaldada ÷ carga máxima admisible; "
                "transferencia automática para su corriente nominal",
                rastro,
                entradas={"carga_kva": carga, "carga_max": maximo},
                detalle={"transferencia_a": transferencia or "fuera de serie"},
            )
        )
        return Generador(alcance, carga, kva, transferencia)


def calcular_edificio(edificio: Edificio, perfil: Perfil) -> EdificioCalculado:
    return _Calculo(edificio, perfil).calcular()
