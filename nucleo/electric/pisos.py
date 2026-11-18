"""Viviendas de varios pisos: un plano por planta, tablero principal y subtableros.

Cada planta es un proyecto diseñado con su propio plano. Las plantas se dibujan
con las mismas coordenadas (como las entrega el arquitecto), así se puede medir
el recorrido entre tableros.

- El tablero principal (TP) está en la planta indicada, por defecto la más baja,
  y alimenta directamente los circuitos de esa planta.
- Cada otra planta tiene un subtablero. Su alimentador sale del TP: sube o baja
  la altura de piso por cada nivel y recorre en planta la distancia ortogonal
  entre los dos tableros. Con esa longitud se calcula la planta sola: su
  demanda, el breaker y el conductor del alimentador y la caída de tensión.
- La vivienda completa se calcula juntando todos los circuitos, porque la
  demanda de una vivienda se obtiene sobre su área y carga totales, no sumando
  la de cada piso. De ahí salen la clasificación CNEL, el breaker principal, el
  alimentador desde el medidor, el balanceo de fases y la acometida.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from electric.calculo import Calculado, calcular
from electric.calculo.resultado import ALIMENTADOR, PROYECTO
from electric.errores import DatoInvalido
from electric.flujo import proyecto_desde_plano
from electric.modelo.entidades import Preferencias, Proyecto, Tablero
from electric.perfiles.carga import Perfil

PRINCIPAL = "TP"


def codigo_piso(nivel: int) -> str:
    """PB para la planta baja, P1, P2… hacia arriba y S1, S2… hacia abajo."""
    if nivel == 0:
        return "PB"
    return f"P{nivel}" if nivel > 0 else f"S{-nivel}"


@dataclass(frozen=True)
class Piso:
    nombre: str
    #: 0 planta baja, 1 primer piso alto, -1 subsuelo…
    nivel: int
    proyecto: Proyecto


@dataclass(frozen=True)
class Subtablero:
    piso: Piso
    tablero: str
    #: Recorrido del alimentador desde el tablero principal.
    longitud_m: Decimal
    vertical_m: Decimal
    horizontal_m: Decimal
    #: La planta calculada con ese alimentador.
    calculado: Calculado

    @property
    def demanda_w(self) -> Decimal:
        return self.calculado.res("RC-03", PROYECTO).decimal

    @property
    def breaker_a(self) -> Decimal:
        return self.calculado.res("RC-09", ALIMENTADOR).decimal

    @property
    def conductor(self) -> str:
        return str(self.calculado.res("RC-07", ALIMENTADOR).valor)

    @property
    def caida_pct(self) -> Decimal:
        return self.calculado.res("RC-08", ALIMENTADOR).decimal


@dataclass(frozen=True)
class Edificacion:
    nombre: str
    pisos: tuple[Piso, ...]
    principal: Piso
    #: La planta del tablero principal, calculada con el alimentador desde el medidor.
    calculado_principal: Calculado
    subtableros: tuple[Subtablero, ...]
    #: Todos los circuitos juntos: demanda, clasificación, principal y acometida.
    conjunto: Proyecto
    calculado: Calculado
    avisos: tuple[str, ...]

    @property
    def area_m2(self) -> Decimal:
        return self.conjunto.area_construida_m2


def _posicion_tablero(proyecto: Proyecto) -> tuple[Decimal, Decimal] | None:
    if proyecto.plano is None:
        return None
    for ubicacion in proyecto.plano.ubicaciones:
        if ubicacion.id == proyecto.tablero.id:
            return ubicacion.x, ubicacion.y
    return None


def _con_tablero(proyecto: Proyecto, id: str, longitud: Decimal) -> Proyecto:
    """La planta con su tablero renombrado (también en el plano) y su alimentador."""
    anterior = proyecto.tablero.id
    plano = proyecto.plano
    if plano is not None:
        plano = plano.model_copy(
            update={
                "ubicaciones": tuple(
                    u.model_copy(update={"id": id}) if u.id == anterior else u
                    for u in plano.ubicaciones
                )
            }
        )
    return proyecto.model_copy(
        update={"tablero": Tablero(id=id, alimentador_longitud_m=longitud), "plano": plano}
    )


def _prefijar(proyecto: Proyecto, prefijo: str) -> Proyecto:
    """Copia de la planta con identificadores únicos en la vivienda: `PB-C1`, `P1-L-A2-1`…"""
    p = f"{prefijo}-"
    return proyecto.model_copy(
        update={
            "puntos": tuple(
                x.model_copy(update={"id": p + x.id, "circuito": p + x.circuito})
                for x in proyecto.puntos
            ),
            "cargas_especiales": tuple(
                x.model_copy(update={"id": p + x.id, "circuito": p + x.circuito})
                for x in proyecto.cargas_especiales
            ),
            "circuitos": tuple(x.model_copy(update={"id": p + x.id}) for x in proyecto.circuitos),
        }
    )


def calcular_pisos(
    nombre: str,
    pisos: Sequence[Piso],
    perfil: Perfil,
    *,
    medidor_m: Decimal,
    altura_piso_m: Decimal,
    nivel_principal: int | None = None,
) -> Edificacion:
    """Tablero principal, subtableros con su alimentador y la vivienda completa."""
    if len(pisos) < 2:
        raise DatoInvalido("una vivienda de varios pisos necesita al menos dos plantas")
    niveles = [p.nivel for p in pisos]
    if len(set(niveles)) != len(niveles):
        raise DatoInvalido("hay dos plantas en el mismo nivel")
    ordenados = sorted(pisos, key=lambda p: p.nivel)
    principal = (
        next((p for p in ordenados if p.nivel == nivel_principal), None)
        if nivel_principal is not None
        else ordenados[0]
    )
    if principal is None:
        raise DatoInvalido(f"no hay una planta en el nivel {nivel_principal}")

    avisos: list[str] = []
    origen = _posicion_tablero(principal.proyecto)
    if origen is None:
        avisos.append(
            f"{principal.nombre} no tiene el tablero ubicado en el plano; los alimentadores "
            "de los subtableros solo cuentan el tramo vertical."
        )

    proyecto_tp = _con_tablero(principal.proyecto, PRINCIPAL, medidor_m)
    calculado_tp = calcular(proyecto_tp, perfil)

    subtableros: list[Subtablero] = []
    for piso in ordenados:
        if piso is principal:
            continue
        vertical = abs(piso.nivel - principal.nivel) * altura_piso_m
        destino = _posicion_tablero(piso.proyecto)
        horizontal = Decimal(0)
        if origen is not None and destino is not None:
            horizontal = abs(destino[0] - origen[0]) + abs(destino[1] - origen[1])
        elif destino is None:
            avisos.append(f"{piso.nombre} no tiene el tablero ubicado en el plano.")
        longitud = max(vertical + horizontal, Decimal(1))
        tablero = f"TD-{codigo_piso(piso.nivel)}"
        proyecto = _con_tablero(piso.proyecto, tablero, longitud)
        subtableros.append(
            Subtablero(
                piso=piso,
                tablero=tablero,
                longitud_m=longitud,
                vertical_m=vertical,
                horizontal_m=horizontal,
                calculado=calcular(proyecto, perfil),
            )
        )

    partes = [_prefijar(p.proyecto, codigo_piso(p.nivel)) for p in ordenados]
    base = principal.proyecto
    conjunto = base.model_copy(
        update={
            "id": f"{base.id}-vivienda",
            "nombre": nombre,
            "area_construida_m2": sum((p.area_construida_m2 for p in partes), Decimal(0)),
            "puntos": tuple(x for p in partes for x in p.puntos),
            "cargas_especiales": tuple(x for p in partes for x in p.cargas_especiales),
            "circuitos": tuple(x for p in partes for x in p.circuitos),
            "tablero": Tablero(id=PRINCIPAL, alimentador_longitud_m=medidor_m),
            "plano": None,
            "supuestos": base.supuestos,
        }
    )
    # Valida identificadores y referencias del conjunto.
    conjunto = Proyecto.model_validate(conjunto.model_dump())
    calculado = calcular(conjunto, perfil)

    for sub in subtableros:
        if sub.breaker_a >= calculado.res("RC-09", ALIMENTADOR).decimal:
            avisos.append(
                f"El breaker del subtablero {sub.tablero} ({sub.breaker_a} A) no es menor que el "
                "principal; revise la selectividad."
            )
    return Edificacion(
        nombre=nombre,
        pisos=tuple(ordenados),
        principal=principal,
        calculado_principal=calculado_tp,
        subtableros=tuple(subtableros),
        conjunto=conjunto,
        calculado=calculado,
        avisos=tuple(avisos),
    )


@dataclass(frozen=True)
class PlanoPiso:
    """Plano de una planta y los equipos declarados en ella."""

    contenido: bytes
    archivo: str
    nombre: str
    nivel: int
    equipos: tuple[str, ...] = ()


@dataclass(frozen=True)
class DisenoPisos:
    edificacion: Edificacion
    #: Avisos de lectura y diseño de cada planta, por nivel.
    avisos: dict[int, tuple[str, ...]]


def disenar_pisos(
    nombre: str,
    planos: Sequence[PlanoPiso],
    perfil: Perfil,
    *,
    medidor_m: Decimal,
    altura_piso_m: Decimal,
    preferencias: Preferencias | None = None,
    factor_a_metros: float | None = None,
) -> DisenoPisos:
    """Diseña cada planta con su plano y calcula la vivienda completa.

    Las luces y tomas de fachada van solo en la planta baja (o la más baja);
    en las demás no hay puertas al exterior.
    """
    preferencias = preferencias or Preferencias()
    if not planos:
        raise DatoInvalido("faltan los planos de las plantas")
    mas_baja = min(p.nivel for p in planos)
    pisos: list[Piso] = []
    avisos: dict[int, tuple[str, ...]] = {}
    for plano in planos:
        prefs = preferencias
        if plano.nivel != mas_baja:
            prefs = preferencias.model_copy(update={"exteriores": False})
        resultado = proyecto_desde_plano(
            plano.contenido,
            plano.archivo,
            perfil,
            id=codigo_piso(plano.nivel).lower(),
            nombre=plano.nombre,
            equipos=plano.equipos,
            alimentador_m=medidor_m,
            factor_a_metros=factor_a_metros,
            preferencias=prefs,
        )
        pisos.append(Piso(plano.nombre, plano.nivel, resultado.proyecto))
        avisos[plano.nivel] = resultado.avisos
    edificacion = calcular_pisos(
        nombre, pisos, perfil, medidor_m=medidor_m, altura_piso_m=altura_piso_m
    )
    return DisenoPisos(edificacion=edificacion, avisos=avisos)
