"""Cálculo de una extensión de red de media tensión.

1. Geometría: cada vano del arranque al último poste, con su longitud y el
   ángulo de deflexión en cada poste (coordenadas proyectadas en metros
   alrededor del arranque; basta para extensiones de unos kilómetros).
2. Estructuras: derivación en el arranque, terminal al final y, en los postes
   de línea, pasante, angular o retención angular según el ángulo; retención
   en alineación cada cierto número de vanos seguidos.
3. Vanos: comparación con el vano máximo de la zona.
4. Caída de tensión por momento eléctrico, vano por vano, con la carga que
   queda aguas abajo de cada vano (transformadores nuevos).
5. Cortocircuito trifásico en el arranque y al final de la línea.
6. Protección: seccionador fusible de la derivación y fusible de cada
   transformador nuevo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from electric.calculo.resultado import Rastro, Resultado, redondear
from electric.errores import FilaNoEncontrada
from electric.mt.modelo import ExtensionMT
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import Estado, FilaEstructuraMT, peor_estado

CERO = Decimal(0)
MIL = Decimal(1000)
RAIZ3 = Decimal(3).sqrt()
#: IEC 60909: factor de tensión máximo en media tensión.
C_MT = Decimal("1.1")
SUJETO = "red_mt"


def _c(valor: Decimal, decimales: int) -> str:
    """Número para un texto: coma decimal."""
    return f"{redondear(valor, decimales):f}".replace(".", ",")


def proyectar(lat: Decimal, lon: Decimal, lat0: Decimal, lon0: Decimal) -> tuple[float, float]:
    """Metros al este y al norte del punto de referencia (equirrectangular local)."""
    x = (float(lon) - float(lon0)) * math.cos(math.radians(float(lat0))) * 111_320.0
    y = (float(lat) - float(lat0)) * 110_540.0
    return x, y


@dataclass(frozen=True)
class Vano:
    desde: str
    hasta: str
    longitud_m: Decimal
    #: Potencia que pasa por el vano (transformadores aguas abajo, con su factor).
    carga_kva: Decimal
    caida_pct: Decimal
    caida_acumulada_pct: Decimal
    excede: bool


@dataclass(frozen=True)
class PosteCalculado:
    id: str
    x: float
    y: float
    lat: Decimal
    lon: Decimal
    angulo: Decimal | None
    estructura: str
    estructura_nombre: str
    codigo: str | None
    transformador_kva: Decimal | None
    fusible: str | None


@dataclass(frozen=True)
class RedCalculada:
    extension: ExtensionMT
    arranque: PosteCalculado
    postes: tuple[PosteCalculado, ...]
    vanos: tuple[Vano, ...]
    longitud_m: Decimal
    kva_total: Decimal
    corriente_a: Decimal
    caida_pct: Decimal
    ik_arranque_ka: Decimal
    ik_final_ka: Decimal
    fusible_derivacion: str | None
    resultados: tuple[Resultado, ...]
    avisos: tuple[str, ...]
    estado: Estado


def _angulo(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """Deflexión en b, en grados: 0 si a, b y c están alineados."""
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        return 0.0
    coseno = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(coseno))


def _fusible(perfil: Perfil, kva: Decimal, kv: Decimal, rastro: Rastro) -> str | None:
    factor = rastro.usar(perfil.parametro("factor_fusible_mt"))
    corriente = kva / (RAIZ3 * kv) * factor
    try:
        return f"{rastro.usar(perfil.normalizado('fusibles_mt', corriente))}K"
    except FilaNoEncontrada:
        return None


def calcular_red(extension: ExtensionMT, perfil: Perfil) -> RedCalculada:
    avisos: list[str] = []
    resultados: list[Resultado] = []

    def resultado(
        id: str,
        nombre: str,
        valor: Decimal | str,
        unidad: str,
        formula: str,
        rastro: Rastro,
        entradas: dict[str, Decimal | str] | None = None,
        detalle: dict[str, Decimal | str] | None = None,
        avisos_r: tuple[str, ...] = (),
    ) -> None:
        resultados.append(
            Resultado(
                id=id,
                sujeto=SUJETO,
                nombre=nombre,
                valor=valor,
                unidad=unidad,
                formula=formula,
                entradas=entradas or {},
                detalle=detalle or {},
                tablas=rastro.tablas,
                supuestos=rastro.supuestos,
                avisos=avisos_r,
                estado=rastro.estado,
            )
        )

    a = extension.arranque
    puntos = [(a.lat, a.lon, "Arranque")] + [(p.lat, p.lon, p.id) for p in extension.postes]
    xy = [proyectar(lat, lon, a.lat, a.lon) for lat, lon, _ in puntos]

    # 1 y 2. Geometría y estructuras.
    r_est = Rastro()
    tipos, ref = perfil.estructuras_mt()
    r_est.anotar(ref)
    por_id = {t.id: t for t in tipos}
    linea = sorted(
        (t for t in tipos if t.funcion == "linea" and t.angulo_max is not None),
        key=lambda t: t.angulo_max or CERO,
    )
    cada = int(r_est.usar(perfil.parametro("retencion_cada_vanos")))

    def codigo(t: FilaEstructuraMT) -> str | None:
        return t.codigo_3f if extension.fases == 3 else t.codigo_1f

    r_prot = Rastro()
    calculados: list[PosteCalculado] = []
    seguidos = 0
    for n, poste in enumerate(extension.postes, start=1):
        angulo: float | None = None
        if n < len(extension.postes):
            angulo = _angulo(xy[n - 1], xy[n], xy[n + 1])
        if poste.estructura and poste.estructura in por_id:
            tipo = por_id[poste.estructura]
        elif poste.estructura:
            tipo = FilaEstructuraMT(
                id=poste.estructura, nombre=poste.estructura, funcion="linea", codigo_3f=None
            )
        elif angulo is None:
            tipo = por_id["terminal"]
        else:
            tipo = next(
                (t for t in linea if Decimal(str(angulo)) <= (t.angulo_max or CERO)),
                linea[-1] if linea else por_id["terminal"],
            )
            if angulo > float(linea[-1].angulo_max or 0):
                avisos.append(
                    f"Poste {poste.id}: deflexión de {angulo:.0f}°, mayor que la que admite "
                    "cualquier estructura de línea; revise el trazado o use dos retenciones."
                )
            if tipo.id == "pasante":
                seguidos += 1
                if seguidos >= cada and "retencion" in por_id:
                    tipo = por_id["retencion"]
                    seguidos = 0
            else:
                seguidos = 0
        fusible = (
            _fusible(perfil, poste.transformador_kva, extension.tension_kv, r_prot)
            if poste.transformador_kva
            else None
        )
        calculados.append(
            PosteCalculado(
                id=poste.id,
                x=xy[n][0],
                y=xy[n][1],
                lat=poste.lat,
                lon=poste.lon,
                angulo=redondear(Decimal(str(angulo)), 1) if angulo is not None else None,
                estructura=tipo.id,
                estructura_nombre=tipo.nombre,
                codigo=codigo(tipo),
                transformador_kva=poste.transformador_kva,
                fusible=fusible,
            )
        )
    tipo_arranque = por_id["arranque"]
    arranque = PosteCalculado(
        id=a.poste or "Arranque",
        x=0.0,
        y=0.0,
        lat=a.lat,
        lon=a.lon,
        angulo=None,
        estructura=tipo_arranque.id,
        estructura_nombre=tipo_arranque.nombre,
        codigo=codigo(tipo_arranque),
        transformador_kva=None,
        fusible=None,
    )
    conteo: dict[str, int] = {}
    for p in calculados:
        conteo[p.estructura_nombre] = conteo.get(p.estructura_nombre, 0) + 1
    resultado(
        "estructuras",
        "Estructuras",
        ", ".join(f"{n} {nombre.lower()}" for nombre, n in conteo.items()),
        "",
        "Derivación en el arranque, terminal al final; en línea según el ángulo de deflexión",
        r_est,
        detalle={"postes": Decimal(len(calculados))},
    )

    # 3 y 4. Vanos y caída de tensión.
    r_v = Rastro()
    conductor = r_v.usar(perfil.conductor_mt(extension.conductor))
    vano_max = r_v.usar(
        perfil.parametro("vano_max_urbano_m" if extension.zona == "urbana" else "vano_max_rural_m")
    )
    limite = r_v.usar(perfil.parametro("caida_mt_max_pct"))
    factor = r_v.usar(perfil.parametro("factor_carga_transformador_mt"))
    seno = (Decimal(1) - extension.fp * extension.fp).sqrt()
    z = conductor.r_ohm_km * extension.fp + conductor.x_ohm_km * seno
    kv = extension.tension_kv
    # Momento eléctrico: ΔV % = kVA × km × (R cos φ + X sen φ) ÷ (10 × kV²) en trifásico;
    # en monofásico (fase-neutro, ida y vuelta) es seis veces mayor.
    k_fases = Decimal(1) if extension.fases == 3 else Decimal(6)
    cargas = [(p.transformador_kva or CERO) * factor for p in extension.postes]
    vanos: list[Vano] = []
    acumulada = a.caida_previa_pct
    largos = 0
    for n in range(1, len(puntos)):
        longitud = Decimal(str(math.hypot(xy[n][0] - xy[n - 1][0], xy[n][1] - xy[n - 1][1])))
        aguas_abajo = sum(cargas[n - 1 :], CERO)
        caida = k_fases * aguas_abajo * longitud / MIL * z / (10 * kv * kv)
        acumulada += caida
        excede = redondear(longitud, 1) > vano_max
        largos += excede
        vanos.append(
            Vano(
                desde=puntos[n - 1][2],
                hasta=puntos[n][2],
                longitud_m=redondear(longitud, 1),
                carga_kva=aguas_abajo,
                caida_pct=caida,
                caida_acumulada_pct=acumulada,
                excede=excede,
            )
        )
    longitud_total = sum((v.longitud_m for v in vanos), CERO)
    if largos:
        avisos.append(
            f"{largos} vano(s) superan el máximo de {vano_max} m en zona {extension.zona}: "
            "agregue postes intermedios."
        )
    resultado(
        "longitud",
        "Longitud de la extensión",
        longitud_total,
        "m",
        "Suma de los vanos entre el arranque y el último poste",
        r_v,
        detalle={
            "vanos": Decimal(len(vanos)),
            "vano_mayor_m": max(v.longitud_m for v in vanos),
            "vano_max_m": vano_max,
        },
    )
    kva_total = sum((p.transformador_kva or CERO for p in extension.postes), CERO)
    corriente = sum(cargas, CERO) / (RAIZ3 * kv if extension.fases == 3 else kv / RAIZ3)
    avisos_caida: tuple[str, ...] = ()
    if acumulada > limite:
        avisos_caida = (
            f"La caída al final ({_c(acumulada, 2)} %) supera el límite de {limite} %: "
            "use un conductor mayor.",
        )
        avisos.extend(avisos_caida)
    resultado(
        "caida_mt",
        "Caída de tensión al final",
        acumulada,
        "%",
        "ΔV % = Σ kVA aguas abajo × km × (R cos φ + X sen φ) ÷ (10 × kV²)",
        r_v,
        entradas={
            "conductor": conductor.calibre,
            "kva_transformadores": kva_total,
            "factor_carga": factor,
            "caida_previa_pct": a.caida_previa_pct,
        },
        detalle={"corriente_a": corriente, "ampacidad_a": conductor.ampacidad},
        avisos_r=avisos_caida,
    )
    if corriente > conductor.ampacidad:
        avisos.append(
            f"La corriente ({_c(corriente, 0)} A) supera la ampacidad del {conductor.calibre}."
        )

    # 5. Cortocircuito.
    r_cc = Rastro()
    if a.scc_mva is not None:
        scc = a.scc_mva
        r_cc.supuesto(f"potencia de cortocircuito de {scc} MVA en el arranque")
    else:
        scc = r_cc.usar(perfil.parametro("potencia_cc_red_mva"))
        r_cc.supuesto(f"potencia de cortocircuito de {scc} MVA del perfil, por confirmar con CNEL")
    zs = kv * kv / scc
    largo_km = longitud_total / MIL
    r_l = conductor.r_ohm_km * largo_km
    x_l = conductor.x_ohm_km * largo_km
    ik_arranque = C_MT * kv / (RAIZ3 * zs)
    ik_final = C_MT * kv / (RAIZ3 * ((r_l) ** 2 + (zs + x_l) ** 2).sqrt())
    capacidad = r_cc.usar(perfil.parametro("capacidad_seccionador_ka"))
    avisos_cc: tuple[str, ...] = ()
    if ik_arranque > capacidad:
        avisos_cc = (
            f"El cortocircuito en el arranque ({_c(ik_arranque, 2)} kA) supera la "
            f"capacidad del seccionador fusible ({capacidad} kA).",
        )
        avisos.extend(avisos_cc)
    resultado(
        "cortocircuito_mt",
        "Cortocircuito en el arranque",
        redondear(ik_arranque, 2),
        "kA",
        "Ik = c × kV ÷ (√3 × |Zred + Zlínea|), c = 1,1; Zred = kV² ÷ Scc",
        r_cc,
        entradas={"scc_mva": scc, "tension_kv": kv},
        detalle={"ik_final_ka": redondear(ik_final, 2), "capacidad_ka": capacidad},
        avisos_r=avisos_cc,
    )

    # 6. Protección de la derivación.
    fusible = _fusible(perfil, kva_total, kv, r_prot) if kva_total > 0 else None
    resultado(
        "proteccion_mt",
        "Seccionador fusible de la derivación",
        fusible or "sin carga",
        "",
        "Fusible K de 1,5 × la corriente de los transformadores nuevos; uno por transformador",
        r_prot,
        detalle={"transformadores": Decimal(sum(1 for p in calculados if p.fusible))},
    )

    return RedCalculada(
        extension=extension,
        arranque=arranque,
        postes=tuple(calculados),
        vanos=tuple(vanos),
        longitud_m=longitud_total,
        kva_total=kva_total,
        corriente_a=corriente,
        caida_pct=acumulada,
        ik_arranque_ka=ik_arranque,
        ik_final_ka=ik_final,
        fusible_derivacion=fusible,
        resultados=tuple(resultados),
        avisos=tuple(avisos),
        estado=peor_estado([r.estado for r in resultados]),
    )
