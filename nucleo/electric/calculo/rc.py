"""Cálculos RC-01 a RC-14 para vivienda (sección 5 del documento de requerimientos).

Cada función devuelve sus resultados con fórmula, entradas, tablas usadas y
supuestos. Ningún valor se inventa: si falta un dato, se lanza un error tipado.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from electric.calculo.contexto import Contexto, texto_supuesto
from electric.calculo.registro import calculo
from electric.calculo.resultado import ALIMENTADOR, PROYECTO, Rastro, Resultado
from electric.calculo.tramos import (
    CIEN,
    MIL,
    Seleccion,
    Tramo,
    conexion_carga,
    corriente,
    seleccionar,
    sistema,
    tramos,
)
from electric.errores import DatoInvalido

CERO = Decimal(0)


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


# --- RC-01 ---------------------------------------------------------------


@calculo("RC-01", "Carga instalada")
def carga_instalada(ctx: Contexto) -> list[Resultado]:
    proyecto = ctx.proyecto
    resultados: list[Resultado] = []
    por_tipo: dict[str, Decimal] = {"iluminacion": CERO, "tomacorrientes": CERO, "especial": CERO}
    general = Rastro()

    for circuito in proyecto.circuitos:
        rastro = Rastro()
        total = CERO
        entradas: dict[str, Decimal | str] = {}
        for punto in (p for p in proyecto.puntos if p.circuito == circuito.id):
            if punto.potencia_w is not None:
                potencia = punto.potencia_w
            else:
                potencia = rastro.usar(ctx.perfil.carga(punto.tipo)).potencia
            total += potencia
            entradas[punto.id] = potencia
        for carga in (c for c in proyecto.cargas_especiales if c.circuito == circuito.id):
            if carga.potencia_w is not None:
                potencia = carga.potencia_w
                rastro.supuesto(f"{carga.id}: potencia de placa {potencia} W")
            else:
                fila = rastro.usar(ctx.perfil.carga(carga.tipo))
                if not fila.especial:
                    raise DatoInvalido(f"'{carga.tipo}' no es una carga especial en el perfil")
                potencia = fila.potencia
            total += potencia
            entradas[carga.id] = potencia
        por_tipo[circuito.tipo] += total
        general.anotar(*rastro.tablas)
        for texto in rastro.supuestos:
            general.supuesto(texto)
        resultados.append(
            _resultado(
                "RC-01",
                circuito.id,
                "Carga instalada del circuito",
                total,
                "W",
                "P = Σ potencia de cada punto o equipo",
                rastro,
                entradas=entradas,
            )
        )

    resultados.append(
        _resultado(
            "RC-01",
            PROYECTO,
            "Carga instalada total",
            sum(por_tipo.values(), CERO),
            "W",
            "P total = P iluminación + P tomacorrientes + P especiales",
            general,
            detalle={
                "iluminacion_w": por_tipo["iluminacion"],
                "tomacorrientes_w": por_tipo["tomacorrientes"],
                "especiales_w": por_tipo["especial"],
            },
        )
    )
    return resultados


# --- RC-02 ---------------------------------------------------------------


@calculo("RC-02", "Número mínimo de circuitos")
def circuitos_minimos(ctx: Contexto) -> list[Resultado]:
    rastro = Rastro()
    area = ctx.proyecto.area_construida_m2
    min_il, min_to = rastro.usar(ctx.perfil.circuitos_minimos(area))
    hay_il = sum(1 for c in ctx.proyecto.circuitos if c.tipo == "iluminacion")
    hay_to = sum(1 for c in ctx.proyecto.circuitos if c.tipo == "tomacorrientes")
    avisos = []
    if hay_il < min_il:
        avisos.append(f"circuitos de iluminación: hay {hay_il} y el mínimo es {min_il}")
    if hay_to < min_to:
        avisos.append(f"circuitos de tomacorrientes: hay {hay_to} y el mínimo es {min_to}")
    return [
        _resultado(
            "RC-02",
            PROYECTO,
            "Número mínimo de circuitos",
            f"{min_il} de iluminación + {min_to} de tomacorrientes",
            "",
            "Mínimo por área construida, según la tabla del perfil",
            rastro,
            entradas={"area_construida_m2": area},
            detalle={
                "minimo_iluminacion": Decimal(min_il),
                "minimo_tomacorrientes": Decimal(min_to),
                "existentes_iluminacion": Decimal(hay_il),
                "existentes_tomacorrientes": Decimal(hay_to),
            },
            avisos=tuple(avisos),
        )
    ]


# --- RC-03 ---------------------------------------------------------------


def _factor(ctx: Contexto, parametro: str, de_tabla: Decimal, rastro: Rastro) -> Decimal:
    supuesto = ctx.supuesto(parametro)
    if supuesto is None:
        return de_tabla
    rastro.supuesto(texto_supuesto(supuesto))
    return supuesto.valor


def _demanda_por_categoria(ctx: Contexto, rastro: Rastro) -> Resultado:
    total = ctx.res("RC-01", PROYECTO)
    p_il = total.det("iluminacion_w")
    p_to = total.det("tomacorrientes_w")
    p_es = total.det("especiales_w")

    area = ctx.proyecto.area_construida_m2
    fila = rastro.usar(ctx.perfil.factores_demanda(area))
    fd_il = _factor(ctx, "factor_demanda_iluminacion", fila.iluminacion, rastro)
    fd_to = _factor(ctx, "factor_demanda_tomacorrientes", fila.tomacorrientes, rastro)
    n_especiales = len(ctx.proyecto.cargas_especiales)
    entradas: dict[str, Decimal | str] = {
        "area_construida_m2": area,
        "categoria": fila.categoria,
        "p_iluminacion_w": p_il,
        "p_tomacorrientes_w": p_to,
        "p_especiales_w": p_es,
        "fd_iluminacion": fd_il,
        "fd_tomacorrientes": fd_to,
    }
    demanda = p_il * fd_il + p_to * fd_to
    if n_especiales:
        de_tabla = rastro.usar(ctx.perfil.factor_especiales(n_especiales))
        fd_es = _factor(ctx, "factor_demanda_especiales", de_tabla, rastro)
        entradas["fd_especiales"] = fd_es
        entradas["cargas_especiales"] = Decimal(n_especiales)
        demanda += p_es * fd_es
    return _resultado(
        "RC-03",
        PROYECTO,
        "Demanda máxima",
        demanda,
        "W",
        "D = P iluminación × FD + P tomacorrientes × FD + P especiales × FD",
        rastro,
        entradas=entradas,
    )


def _demanda_escalonada(ctx: Contexto, rastro: Rastro) -> Resultado:
    total = ctx.res("RC-01", PROYECTO).decimal
    filas = rastro.usar(ctx.perfil.tramos_demanda())
    demanda = CERO
    desde = CERO
    entradas: dict[str, Decimal | str] = {"carga_instalada_w": total}
    for n, fila in enumerate(filas, start=1):
        hasta = total if fila.hasta is None else min(total, fila.hasta)
        parte = max(hasta - desde, CERO)
        demanda += parte * fila.factor
        entradas[f"tramo_{n}_w"] = parte
        entradas[f"tramo_{n}_factor"] = fila.factor
        desde = max(desde, hasta)
    if desde < total:
        raise DatoInvalido("la tabla de tramos de demanda no cubre toda la carga instalada")
    return _resultado(
        "RC-03",
        PROYECTO,
        "Demanda máxima",
        demanda,
        "W",
        "D = Σ (carga de cada tramo × factor del tramo), sobre la carga instalada total",
        rastro,
        entradas=entradas,
    )


@calculo("RC-03", "Demanda máxima", depende=("RC-01",))
def demanda_maxima(ctx: Contexto) -> list[Resultado]:
    rastro = Rastro()
    if ctx.perfil.meta.demanda_metodo == "escalonado":
        return [_demanda_escalonada(ctx, rastro)]
    return [_demanda_por_categoria(ctx, rastro)]


# --- RC-05 ---------------------------------------------------------------


@calculo("RC-05", "Clasificación CNEL", depende=("RC-03",))
def clasificacion(ctx: Contexto) -> list[Resultado]:
    rastro = Rastro()
    demanda_kw = ctx.res("RC-03", PROYECTO).decimal / MIL
    umbral_i = rastro.usar(ctx.perfil.parametro("umbral_tipo_i_kw"))
    umbral_ii = rastro.usar(ctx.perfil.parametro("umbral_tipo_ii_kw"))
    if demanda_kw <= umbral_i:
        tipo = "Tipo I"
    elif demanda_kw <= umbral_ii:
        tipo = "Tipo II"
    else:
        tipo = "Tipo III"
    return [
        _resultado(
            "RC-05",
            PROYECTO,
            "Clasificación del proyecto",
            tipo,
            "",
            f"Tipo I si D ≤ {umbral_i} kW; Tipo II si D ≤ {umbral_ii} kW; Tipo III si es mayor",
            rastro,
            entradas={"demanda_kw": demanda_kw},
        )
    ]


# --- RC-06 a RC-09 -------------------------------------------------------


def _formula_corriente(tramo: Tramo) -> str:
    return "I = P / (√3 × V × FP)" if tramo.trifasico else "I = P / (V × FP)"


@calculo("RC-06", "Corriente de diseño", depende=("RC-01", "RC-03"))
def corriente_diseno(ctx: Contexto) -> list[Resultado]:
    resultados = []
    for tramo in tramos(ctx, Rastro()):
        rastro = Rastro()
        sistema(ctx, rastro)
        if tramo.uso == "especial":
            conexion_carga(ctx, tramo.sujeto, rastro)
        fp = ctx.parametro("factor_potencia", rastro)
        resultados.append(
            _resultado(
                "RC-06",
                tramo.sujeto,
                "Corriente",
                corriente(tramo.potencia_w, tramo.tension_v, fp, tramo.trifasico),
                "A",
                _formula_corriente(tramo),
                rastro,
                entradas={
                    "potencia_w": tramo.potencia_w,
                    "tension_v": tramo.tension_v,
                    "factor_potencia": fp,
                },
                detalle={"polos": Decimal(tramo.polos)},
            )
        )
    return resultados


def _selecciones(ctx: Contexto) -> list[tuple[Tramo, Seleccion, Rastro]]:
    lista = []
    for tramo in tramos(ctx, Rastro()):
        rastro = Rastro()
        lista.append((tramo, seleccionar(ctx, tramo, rastro), rastro))
    return lista


@calculo("RC-07", "Conductor", depende=("RC-06",))
def conductor(ctx: Contexto) -> list[Resultado]:
    resultados = []
    for tramo, sel, rastro in _selecciones(ctx):
        avisos: tuple[str, ...] = ()
        if sel.pasos_por_caida:
            avisos = (
                f"se subió {sel.pasos_por_caida} calibre(s) para cumplir la caída de tensión",
            )
        resultados.append(
            _resultado(
                "RC-07",
                tramo.sujeto,
                "Conductor",
                sel.fila.calibre,
                "",
                "Primer calibre con ampacidad × f.temperatura × f.agrupamiento ≥ 1,25 × I, "
                "que admite el breaker y cumple la caída de tensión",
                rastro,
                entradas={
                    "corriente_a": ctx.res("RC-06", tramo.sujeto).decimal,
                    "corriente_diseno_a": sel.corriente_diseno,
                    "factor_temperatura": sel.factor_temperatura,
                    "factor_agrupamiento": sel.factor_agrupamiento,
                    "limite_caida_pct": sel.limite_caida_pct,
                },
                detalle={
                    "seccion_mm2": sel.fila.seccion_mm2,
                    "ampacidad_corregida_a": sel.ampacidad_corregida,
                    "pasos_por_caida": Decimal(sel.pasos_por_caida),
                },
                avisos=avisos,
            )
        )
    return resultados


@calculo("RC-08", "Caída de tensión", depende=("RC-06", "RC-07"))
def caida_tension(ctx: Contexto) -> list[Resultado]:
    selecciones = _selecciones(ctx)
    del_alimentador = next(s.caida_pct for t, s, _ in selecciones if t.uso == "alimentador")
    limite_total = ctx.perfil.parametro("caida_total_max_pct")
    resultados = []
    for tramo, sel, rastro in selecciones:
        detalle: dict[str, Decimal | str] = {"limite_pct": sel.limite_caida_pct}
        avisos = []
        if tramo.uso != "alimentador":
            total = sel.caida_pct + del_alimentador
            rastro.anotar(limite_total[1])
            detalle["total_con_alimentador_pct"] = total
            detalle["limite_total_pct"] = limite_total[0]
            if total > limite_total[0]:
                avisos.append(f"la caída total supera {limite_total[0]} %")
        raiz = "√3" if tramo.trifasico else "2"
        resultados.append(
            _resultado(
                "RC-08",
                tramo.sujeto,
                "Caída de tensión",
                sel.caida_pct,
                "%",
                f"ΔV % = {raiz} × I × L × (R cos φ + X sen φ) / 1000 / V × 100",
                rastro,
                entradas={
                    "corriente_a": ctx.res("RC-06", tramo.sujeto).decimal,
                    "longitud_m": tramo.longitud_m,
                    "tension_v": tramo.tension_v,
                    "calibre": sel.fila.calibre,
                    "r_ohm_km": sel.fila.r_ohm_km,
                    "x_ohm_km": sel.fila.x_ohm_km,
                },
                detalle=detalle,
                avisos=tuple(avisos),
            )
        )
    return resultados


@calculo("RC-09", "Protección", depende=("RC-06", "RC-07"))
def proteccion(ctx: Contexto) -> list[Resultado]:
    exige_diferencial = ctx.perfil.parametro("diferencial_zonas_humedas")
    resultados = []
    for tramo, sel, rastro in _selecciones(ctx):
        diferencial = "no"
        if tramo.zona_humeda:
            rastro.anotar(exige_diferencial[1])
            diferencial = "sí" if exige_diferencial[0] == 1 else "no"
        resultados.append(
            _resultado(
                "RC-09",
                tramo.sujeto,
                "Protección",
                sel.breaker,
                "A",
                "Primer breaker normalizado ≥ I y ≥ mínimo del uso, admitido por el calibre",
                rastro,
                entradas={
                    "corriente_a": ctx.res("RC-06", tramo.sujeto).decimal,
                    "calibre": sel.fila.calibre,
                },
                detalle={"polos": Decimal(tramo.polos), "diferencial": diferencial},
            )
        )
    return resultados


# --- RC-10 ---------------------------------------------------------------

_LETRAS = ("A", "B", "C")


@calculo("RC-10", "Balanceo de fases", depende=("RC-01",))
def balanceo(ctx: Contexto) -> list[Resultado]:
    general = Rastro()
    sis = sistema(ctx, general)
    fases = _LETRAS[: sis.fases]
    carga = dict.fromkeys(fases, CERO)
    asignadas: dict[str, str] = {}
    rastros: dict[str, Rastro] = {}

    datos = []
    for circuito in ctx.proyecto.circuitos:
        rastro = Rastro()
        sistema(ctx, rastro)
        polos = 1
        if circuito.tipo == "especial" and conexion_carga(ctx, circuito.id, rastro) == "linea":
            polos = 2
        if polos > sis.fases:
            raise DatoInvalido(f"el circuito {circuito.id} necesita más fases que el sistema")
        rastros[circuito.id] = rastro
        datos.append((circuito, polos, ctx.res("RC-01", circuito.id).decimal))

    # Primero las fases fijadas por el usuario; el resto, de mayor a menor carga.
    for circuito, polos, potencia in datos:
        if circuito.fase is None:
            continue
        if len(circuito.fase) != polos or any(f not in fases for f in circuito.fase):
            raise DatoInvalido(
                f"la fase '{circuito.fase}' del circuito {circuito.id} "
                f"no corresponde a {polos} polo(s) del sistema '{sis.id}'"
            )
        asignadas[circuito.id] = circuito.fase
        for f in circuito.fase:
            carga[f] += potencia / polos
    libres = [d for d in datos if d[0].fase is None]
    for circuito, polos, potencia in sorted(libres, key=lambda d: (-d[2], d[0].id)):
        elegidas = sorted(sorted(fases, key=lambda f: (carga[f], f))[:polos])
        asignadas[circuito.id] = "".join(elegidas)
        for f in elegidas:
            carga[f] += potencia / polos

    resultados = [
        _resultado(
            "RC-10",
            circuito.id,
            "Fase",
            asignadas[circuito.id],
            "",
            "Fase fijada por el usuario, o la menos cargada al asignar de mayor a menor carga",
            rastros[circuito.id],
            entradas={"potencia_w": potencia, "polos": Decimal(polos)},
            detalle={"origen": "fijada" if circuito.fase else "automática"},
        )
        for circuito, polos, potencia in datos
    ]

    mayor, menor = max(carga.values()), min(carga.values())
    desbalance = (mayor - menor) / mayor * CIEN if mayor > 0 and sis.fases > 1 else CERO
    maximo = general.usar(ctx.perfil.parametro("desbalance_max_pct"))
    avisos = (f"el desbalance supera {maximo} %",) if desbalance > maximo else ()
    resultados.append(
        _resultado(
            "RC-10",
            PROYECTO,
            "Desbalance de fases",
            desbalance,
            "%",
            "Desbalance % = (fase mayor − fase menor) / fase mayor × 100",
            general,
            entradas={f"fase_{f}_w": carga[f] for f in fases},
            detalle={"maximo_pct": maximo},
            avisos=avisos,
        )
    )
    return resultados


# --- RC-11 a RC-14 -------------------------------------------------------


@calculo("RC-11", "Tablero", depende=("RC-09", "RC-10"))
def tablero(ctx: Contexto) -> list[Resultado]:
    rastro = Rastro()
    ramales = [r for r in ctx.de("RC-09") if r.sujeto != ALIMENTADOR]
    polos = sum((r.det("polos") for r in ramales), CERO)
    cada = rastro.usar(ctx.perfil.parametro("reserva_polos_cada"))
    reserva = (polos / cada).to_integral_value(rounding=ROUND_CEILING)
    espacios = rastro.usar(ctx.perfil.normalizado("espacios_tablero", polos + reserva))
    principal = ctx.res("RC-09", ALIMENTADOR).decimal
    barras = rastro.usar(ctx.perfil.normalizado("barras", principal))
    return [
        _resultado(
            "RC-11",
            ctx.proyecto.tablero.id,
            "Tablero de distribución",
            espacios,
            "espacios",
            f"Espacios = primer tamaño normalizado ≥ polos usados + 1 reserva por cada {cada}",
            rastro,
            entradas={"polos_usados": polos, "polos_reserva": reserva},
            detalle={"principal_a": principal, "barras_a": barras},
        )
    ]


@calculo("RC-12", "Acometida y medidor", depende=("RC-09", "RC-11"))
def acometida(ctx: Contexto) -> list[Resultado]:
    rastro = Rastro()
    principal = ctx.res("RC-09", ALIMENTADOR).decimal
    medidor = rastro.usar(ctx.perfil.medidor(principal))
    return [
        _resultado(
            "RC-12",
            PROYECTO,
            "Medidor",
            medidor.clase,
            "",
            "Clase de medidor según el breaker principal",
            rastro,
            entradas={"principal_a": principal},
            detalle={"conductor_acometida": ctx.res("RC-07", ALIMENTADOR).valor},
        )
    ]


def _tierra(ctx: Contexto, sujeto: str, rastro: Rastro) -> str:
    return rastro.usar(ctx.perfil.tierra_equipos(ctx.res("RC-09", sujeto).decimal))


@calculo("RC-13", "Ductería", depende=("RC-07", "RC-09"))
def ducteria(ctx: Contexto) -> list[Resultado]:
    resultados = []
    for tramo in tramos(ctx, Rastro()):
        rastro = Rastro()
        calibre = str(ctx.res("RC-07", tramo.sujeto).valor)
        fila = rastro.usar(ctx.perfil.conductor(calibre))
        tierra = rastro.usar(ctx.perfil.conductor(_tierra(ctx, tramo.sujeto, rastro)))
        relleno = rastro.usar(ctx.perfil.parametro("relleno_ducto_max_pct"))
        ocupada = tramo.conductores * fila.area_aislado_mm2 + tierra.area_aislado_mm2
        ducto = rastro.usar(ctx.perfil.ducto(ocupada * CIEN / relleno))
        resultados.append(
            _resultado(
                "RC-13",
                tramo.sujeto,
                "Ducto",
                ducto.designacion,
                "",
                f"Menor ducto con área interior ≥ área de conductores / {relleno} %",
                rastro,
                entradas={
                    "conductores": f"{tramo.conductores} × {calibre} + tierra {tierra.calibre}",
                    "area_conductores_mm2": ocupada,
                },
                detalle={"relleno_pct": ocupada / ducto.area_mm2 * CIEN},
            )
        )
    return resultados


@calculo("RC-14", "Puesta a tierra", depende=("RC-09", "RC-12"))
def puesta_a_tierra(ctx: Contexto) -> list[Resultado]:
    resultados = []
    for tramo in tramos(ctx, Rastro()):
        rastro = Rastro()
        resultados.append(
            _resultado(
                "RC-14",
                tramo.sujeto,
                "Conductor de tierra de equipos",
                _tierra(ctx, tramo.sujeto, rastro),
                "",
                "Calibre según el breaker que protege el tramo",
                rastro,
                entradas={"breaker_a": ctx.res("RC-09", tramo.sujeto).decimal},
            )
        )
    rastro = Rastro()
    resultados.append(
        _resultado(
            "RC-14",
            PROYECTO,
            "Resistencia objetivo de puesta a tierra",
            rastro.usar(ctx.perfil.parametro("resistencia_tierra_max_ohm")),
            "ohm",
            "Resistencia medida del electrodo menor que el valor objetivo",
            rastro,
            detalle={
                "electrodo_longitud_m": rastro.usar(ctx.perfil.parametro("electrodo_longitud_m")),
                "electrodo_diametro_pulg": rastro.usar(
                    ctx.perfil.parametro("electrodo_diametro_pulg")
                ),
            },
        )
    )
    return resultados
