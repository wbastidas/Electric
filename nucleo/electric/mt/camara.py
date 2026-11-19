"""Cámara de transformación de un cliente con medición en media tensión.

Para la potencia del transformador elige:

- El fusible de MT del primario y los transformadores de medida (TC y TP).
- Las celdas: llegada, protección, medición y transformador.
- Las dimensiones interiores de la cámara, de la tabla del perfil.
- La malla de puesta a tierra: rectángulo alrededor de la cámara con
  separación entre conductores y varillas suficientes para no superar la
  resistencia máxima, con la fórmula de Sverak (IEEE 80):
  R = ρ × [1/L + 1/√(20 A) × (1 + 1/(1 + h × √(20/A)))].

Y dibuja la planta de la cámara con la malla y el unifilar del cliente en MT.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from ezdxf.enums import TextEntityAlignment

from electric.calculo.resultado import Rastro, Resultado, redondear
from electric.errores import FilaNoEncontrada
from electric.mt.salidas import _documento, _n, _texto
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import Estado, FilaCamara, peor_estado
from electric.salida_cad.dxf import _verificado

RAIZ3 = Decimal(3).sqrt()
#: Profundidad de la malla.
PROFUNDIDAD_M = 0.6
SEPARACIONES = (3.0, 2.0, 1.5, 1.0)
SUJETO = "camara"


@dataclass(frozen=True)
class Malla:
    largo_m: float
    ancho_m: float
    separacion_m: float
    conductor_m: float
    varillas: int
    longitud_total_m: float
    resistencia_ohm: float
    limite_ohm: float
    cumple: bool


@dataclass(frozen=True)
class Camara:
    kva: Decimal
    tension_kv: Decimal
    v_bt: Decimal
    corriente_primaria_a: Decimal
    corriente_secundaria_a: Decimal
    fusible: str | None
    tc: str | None
    tp: str
    celdas: tuple[tuple[str, str], ...]
    dimensiones: FilaCamara | None
    malla: Malla
    resistividad_ohm_m: Decimal
    resultados: tuple[Resultado, ...]
    avisos: tuple[str, ...]
    estado: Estado


def _sverak(rho: float, longitud: float, area: float) -> float:
    h = PROFUNDIDAD_M
    return rho * (
        1 / longitud + 1 / math.sqrt(20 * area) * (1 + 1 / (1 + h * math.sqrt(20 / area)))
    )


def _malla(largo: float, ancho: float, rho: float, limite: float, varilla: float) -> Malla:
    area = largo * ancho
    mejor: Malla | None = None
    for separacion in SEPARACIONES:
        n_largo = max(int(math.ceil(largo / separacion)) + 1, 2)
        n_ancho = max(int(math.ceil(ancho / separacion)) + 1, 2)
        conductor = n_largo * ancho + n_ancho * largo
        perimetro = 2 * (n_largo + n_ancho) - 4
        for varillas in range(4, perimetro + 1, 2):
            total = conductor + varillas * varilla
            r = _sverak(rho, total, area)
            mejor = Malla(
                largo_m=largo,
                ancho_m=ancho,
                separacion_m=separacion,
                conductor_m=conductor,
                varillas=varillas,
                longitud_total_m=total,
                resistencia_ohm=r,
                limite_ohm=limite,
                cumple=r <= limite,
            )
            if mejor.cumple:
                return mejor
    assert mejor is not None
    return mejor


def disenar_camara(
    kva: Decimal,
    perfil: Perfil,
    *,
    tension_kv: Decimal | None = None,
    v_bt: Decimal = Decimal(220),
    resistividad_ohm_m: Decimal | None = None,
) -> Camara:
    avisos: list[str] = []
    resultados: list[Resultado] = []
    rastro = Rastro()
    kv = tension_kv or rastro.usar(perfil.parametro("tension_media_kv"))
    i_primaria = kva / (RAIZ3 * kv)
    i_secundaria = kva * 1000 / (RAIZ3 * v_bt)

    # Protección y medida.
    r_med = Rastro()
    factor = r_med.usar(perfil.parametro("factor_fusible_mt"))
    try:
        fusible: str | None = (
            f"{r_med.usar(perfil.normalizado('fusibles_mt', i_primaria * factor))}K"
        )
    except FilaNoEncontrada:
        fusible = None
        avisos.append(
            "La corriente primaria supera la serie de fusibles: use un interruptor de MT."
        )
    factor_tc = r_med.usar(perfil.parametro("factor_tc"))
    try:
        primario = r_med.usar(perfil.normalizado("relaciones_tc", i_primaria * factor_tc))
        tc: str | None = f"{primario}/5 A"
    except FilaNoEncontrada:
        tc = None
        avisos.append("La corriente primaria supera la serie de relaciones de TC.")
    tp = f"{_n(kv * 1000, 0)}/120 V"
    resultados.append(
        Resultado(
            id="medicion_mt",
            sujeto=SUJETO,
            nombre="Protección y medición en MT",
            valor=f"fusible {fusible or '—'} · TC {tc or '—'} · TP {tp}",
            unidad="",
            formula="In = kVA ÷ (√3 × kV); fusible K y TC normalizados sobre In × factor",
            entradas={"kva": kva, "tension_kv": kv, "corriente_primaria_a": i_primaria},
            tablas=r_med.tablas,
            estado=r_med.estado,
        )
    )
    celdas = (
        ("Llegada", "Seccionador tripolar de operación sin carga y pararrayos"),
        ("Protección", f"Seccionador bajo carga con fusibles {fusible or 'por definir'}"),
        ("Medición", f"3 TC {tc or 'por definir'} y 3 TP {tp}, medidor de CNEL"),
        ("Transformador", f"{_n(kva, 1)} kVA, {_n(kv, 1)} kV / {_n(v_bt, 0)} V"),
    )

    # Dimensiones.
    r_dim = Rastro()
    try:
        dimensiones: FilaCamara | None = r_dim.usar(perfil.camara_para(kva))
    except FilaNoEncontrada:
        dimensiones = None
        avisos.append(f"No hay dimensiones de cámara para {kva} kVA en el perfil.")
    resultados.append(
        Resultado(
            id="camara",
            sujeto=SUJETO,
            nombre="Dimensiones interiores de la cámara",
            valor=(
                f"{_n(dimensiones.largo_m, 1)} × {_n(dimensiones.ancho_m, 1)} × "
                f"{_n(dimensiones.alto_m, 1)} m"
                if dimensiones
                else "sin tabla"
            ),
            unidad="",
            formula="Menor cámara de la tabla cuya potencia cubre la del transformador",
            entradas={"kva": kva},
            tablas=r_dim.tablas,
            estado=r_dim.estado,
        )
    )

    # Malla de puesta a tierra.
    r_t = Rastro()
    if resistividad_ohm_m is None:
        resistividad_ohm_m = r_t.usar(perfil.parametro("resistividad_suelo_ohm_m"))
        r_t.supuesto(f"resistividad del suelo de {resistividad_ohm_m} Ω·m sin medición")
    clave = "resistencia_tierra_max_ohm" if kva <= 250 else "resistencia_tierra_mt_max_ohm"
    limite = r_t.usar(perfil.parametro(clave))
    margen = float(r_t.usar(perfil.parametro("margen_malla_m")))
    varilla = float(r_t.usar(perfil.parametro("varilla_tierra_m")))
    largo = float(dimensiones.largo_m if dimensiones else Decimal(3)) + 2 * margen
    ancho = float(dimensiones.ancho_m if dimensiones else Decimal(3)) + 2 * margen
    malla = _malla(largo, ancho, float(resistividad_ohm_m), float(limite), varilla)
    avisos_malla: tuple[str, ...] = ()
    if not malla.cumple:
        avisos_malla = (
            f"Con {resistividad_ohm_m} Ω·m la malla no baja de "
            f"{_n(malla.resistencia_ohm, 1)} Ω (máximo {limite} Ω): amplíe la malla, use "
            "varillas más largas o mejore el suelo.",
        )
        avisos.extend(avisos_malla)
    resultados.append(
        Resultado(
            id="malla",
            sujeto=SUJETO,
            nombre="Malla de puesta a tierra",
            valor=redondear(Decimal(str(malla.resistencia_ohm)), 2),
            unidad="ohm",
            formula="R = ρ × [1/L + 1/√(20 A) × (1 + 1/(1 + h √(20/A)))] (Sverak, IEEE 80)",
            entradas={"resistividad_ohm_m": resistividad_ohm_m, "limite_ohm": limite},
            detalle={
                "malla": f"{_n(largo, 1)} × {_n(ancho, 1)} m cada {_n(malla.separacion_m, 1)} m",
                "conductor_m": redondear(Decimal(str(malla.conductor_m)), 1),
                "varillas": Decimal(malla.varillas),
            },
            tablas=r_t.tablas,
            supuestos=r_t.supuestos,
            avisos=avisos_malla,
            estado=r_t.estado,
        )
    )
    return Camara(
        kva=kva,
        tension_kv=kv,
        v_bt=v_bt,
        corriente_primaria_a=i_primaria,
        corriente_secundaria_a=i_secundaria,
        fusible=fusible,
        tc=tc,
        tp=tp,
        celdas=celdas,
        dimensiones=dimensiones,
        malla=malla,
        resistividad_ohm_m=resistividad_ohm_m,
        resultados=tuple(resultados),
        avisos=tuple(avisos),
        estado=peor_estado([r.estado for r in resultados]),
    )


def generar_plano_camara(camara: Camara, nombre: str, breaker_bt: str | None = None) -> bytes:
    """Planta de la cámara con celdas, transformador y malla, y el unifilar del cliente."""
    doc, msp = _documento()
    d = camara.dimensiones
    largo = float(d.largo_m) if d else 3.0
    ancho = float(d.ancho_m) if d else 3.0
    muro = 0.2
    alto = 0.12
    # Muros.
    for dx, dy in ((0, 0), (muro, muro)):
        msp.add_lwpolyline(
            [
                (-muro + dx, -muro + dy),
                (largo + muro - dx, -muro + dy),
                (largo + muro - dx, ancho + muro - dy),
                (-muro + dx, ancho + muro - dy),
            ],
            close=True,
            dxfattribs={"layer": "MT-TEXTO"},
        )
    # Puerta en el lado largo inferior.
    puerta = min(1.2, largo * 0.4)
    msp.add_line((0.2, -muro), (0.2, -muro - puerta), dxfattribs={"layer": "MT-COTAS"})
    msp.add_arc((0.2, -muro), puerta, 270, 360, dxfattribs={"layer": "MT-COTAS"})
    # Celdas junto a la pared del fondo.
    ancho_celda = min(0.75, (largo * 0.6) / 3)
    for n, (titulo, _) in enumerate(camara.celdas[:3]):
        x = 0.15 + n * (ancho_celda + 0.05)
        msp.add_lwpolyline(
            [(x, ancho - 0.9), (x + ancho_celda, ancho - 0.9), (x + ancho_celda, ancho - 0.05),
             (x, ancho - 0.05)],
            close=True,
            dxfattribs={"layer": "MT-NUEVA"},
        )  # fmt: skip
        _texto(msp, titulo.upper(), x + ancho_celda / 2, ancho - 0.5, alto * 0.7,
               alineacion=TextEntityAlignment.MIDDLE_CENTER)  # fmt: skip
    # Transformador al otro extremo.
    tl = min(1.6, largo * 0.35)
    ta = min(1.2, ancho * 0.45)
    tx, ty = largo - tl - 0.4, (ancho - ta) / 2
    msp.add_lwpolyline(
        [(tx, ty), (tx + tl, ty), (tx + tl, ty + ta), (tx, ty + ta)],
        close=True,
        dxfattribs={"layer": "MT-TRAFOS"},
    )
    for k, linea in enumerate(("TRANSFORMADOR", f"{_n(camara.kva, 1)} kVA")):
        _texto(msp, linea, tx + tl / 2, ty + ta / 2 + (0.1 - k * 0.22), alto * 0.8, "MT-TRAFOS",
               TextEntityAlignment.MIDDLE_CENTER)  # fmt: skip
    # Malla de tierra centrada en la cámara.
    m = camara.malla
    ox = (largo - m.largo_m) / 2
    oy = (ancho - m.ancho_m) / 2
    n_l = max(int(math.ceil(m.largo_m / m.separacion_m)) + 1, 2)
    n_a = max(int(math.ceil(m.ancho_m / m.separacion_m)) + 1, 2)
    paso_l = m.largo_m / (n_l - 1)
    paso_a = m.ancho_m / (n_a - 1)
    for i in range(n_l):
        x = ox + i * paso_l
        msp.add_line((x, oy), (x, oy + m.ancho_m), dxfattribs={"layer": "MT-COTAS"})
    for j in range(n_a):
        y = oy + j * paso_a
        msp.add_line((ox, y), (ox + m.largo_m, y), dxfattribs={"layer": "MT-COTAS"})
    perimetro = (
        [(ox + i * paso_l, oy) for i in range(n_l)]
        + [(ox + m.largo_m, oy + j * paso_a) for j in range(1, n_a)]
        + [(ox + i * paso_l, oy + m.ancho_m) for i in range(n_l - 2, -1, -1)]
        + [(ox, oy + j * paso_a) for j in range(n_a - 2, 0, -1)]
    )
    esquinas = [
        (ox, oy),
        (ox + m.largo_m, oy),
        (ox + m.largo_m, oy + m.ancho_m),
        (ox, oy + m.ancho_m),
    ]
    resto = [p for p in perimetro if p not in esquinas]
    extra = m.varillas - 4
    elegidas = esquinas + (
        [resto[round(k * len(resto) / extra)] for k in range(extra)] if extra > 0 and resto else []
    )
    for x, y in elegidas[: m.varillas]:
        msp.add_circle((x, y), 0.08, dxfattribs={"layer": "MT-POSTES"})

    # Datos.
    y = oy - 0.8
    lineas = [
        f"CÁMARA DE TRANSFORMACIÓN · {nombre}",
        f"Interior {_n(largo, 1)} × {_n(ancho, 1)} m"
        + (f", altura {_n(d.alto_m, 1)} m" if d else ""),
        *(f"{t}: {texto}" for t, texto in camara.celdas),
        f"Malla {_n(m.largo_m, 1)} × {_n(m.ancho_m, 1)} m cada {_n(m.separacion_m, 1)} m, "
        f"{m.varillas} varillas, R = {_n(m.resistencia_ohm, 2)} Ω (máx. {_n(m.limite_ohm, 0)} Ω), "
        f"ρ = {camara.resistividad_ohm_m} Ω·m",
        "BORRADOR sujeto a revisión y firma de un profesional habilitado.",
    ]
    for n, linea in enumerate(lineas):
        _texto(msp, linea, ox, y - n * alto * 2.2, alto * (1.4 if n == 0 else 1))

    # Unifilar del cliente, a la derecha.
    ux = largo + 3.0
    uy = ancho + 0.5
    pasos = [
        ("Red CNEL", f"{_n(camara.tension_kv, 1)} kV"),
        ("Llegada", "seccionador y pararrayos"),
        ("Protección", f"fusibles {camara.fusible or '—'}"),
        ("Medición", f"TC {camara.tc or '—'} · TP {camara.tp}"),
        ("Transformador", f"{_n(camara.kva, 1)} kVA"),
        ("Baja tensión", f"breaker {breaker_bt or '—'} · {_n(camara.v_bt, 0)} V"),
    ]
    for n, (titulo, texto) in enumerate(pasos):
        y0 = uy - n * 0.9
        msp.add_circle((ux, y0), 0.12, dxfattribs={"layer": "MT-NUEVA"})
        if n:
            msp.add_line((ux, y0 + 0.78), (ux, y0 + 0.12), dxfattribs={"layer": "MT-NUEVA"})
        _texto(msp, f"{titulo}: {texto}", ux + 0.3, y0 - 0.05, alto)
    _texto(msp, "UNIFILAR DEL CLIENTE EN MT", ux, uy + 0.5, alto * 1.2)
    return _verificado(doc)
