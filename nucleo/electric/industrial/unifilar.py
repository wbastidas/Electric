"""Diagrama unifilar de una industria en DXF.

De arriba hacia abajo: red de CNEL, transformador (particular o existente con
su acometida), medición, breaker principal, barra del tablero principal con
el banco de capacitores, y una columna por tablero de distribución con su
breaker, alimentador y los circuitos de sus máquinas. Cada punto lleva la
corriente de cortocircuito y la capacidad de interrupción elegida.
"""

from __future__ import annotations

from decimal import Decimal

from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment
from ezdxf.layouts.layout import Modelspace

from electric.industrial.analisis import AnalisisIndustrial, _t
from electric.industrial.estudios import PRINCIPAL, Estudios
from electric.salida_cad.dxf import _verificado

ALTO = 2.2
PASO_MAQUINA = 26.0
CAPAS = {"E-UNIF": 7, "E-UNIF-TEXT": 7, "E-UNIF-CC": 1, "E-UNIF-MARCO": 8}


def _texto(
    msp: Modelspace,
    texto: str,
    x: float,
    y: float,
    alto: float = ALTO,
    capa: str = "E-UNIF-TEXT",
    alineacion: TextEntityAlignment = TextEntityAlignment.LEFT,
) -> None:
    msp.add_text(texto, height=alto, dxfattribs={"layer": capa}).set_placement(
        (x, y), align=alineacion
    )


def _linea(msp: Modelspace, a: tuple[float, float], b: tuple[float, float]) -> None:
    msp.add_line(a, b, dxfattribs={"layer": "E-UNIF"})


def _breaker(msp: Modelspace, x: float, y: float) -> float:
    """Interruptor como rectángulo con diagonal; devuelve la y inferior."""
    msp.add_lwpolyline(
        [(x - 2, y), (x + 2, y), (x + 2, y - 6), (x - 2, y - 6)],
        close=True,
        dxfattribs={"layer": "E-UNIF"},
    )
    _linea(msp, (x - 2, y - 6), (x + 2, y))
    return y - 6


def _a(valor: Decimal | None, unidad: str) -> str:
    return f"{_t(valor, 0)} {unidad}" if valor is not None else "fuera de serie"


def generar_unifilar(analisis: AnalisisIndustrial, estudios: Estudios) -> bytes:
    doc = Drawing.new("R2010")
    doc.units = 4  # milímetros
    for capa, color in CAPAS.items():
        doc.layers.add(capa, color=color)
    msp = doc.modelspace()
    industria = analisis.industria
    decision = analisis.decision
    sistema = analisis.sistema
    polos = "3P" if sistema.fases == 3 else "2P"
    cc = {p.punto: p for p in estudios.cortocircuito}

    # Anchura: una columna por tablero, del ancho de sus máquinas.
    maquinas_por_tablero = {
        t.tablero: [c for c in estudios.circuitos if c.tablero == t.tablero]
        for t in analisis.tableros
    }
    anchos = [max(len(m), 1) * PASO_MAQUINA + 16 for m in maquinas_por_tablero.values()]
    banco = analisis.resultado("factor_potencia").det("banco_kvar")
    extra_banco = 40.0 if banco > 0 else 0.0
    total = sum(anchos) + extra_banco
    x0 = -total / 2

    # Red de CNEL.
    y = 0.0
    msp.add_circle((0, y), 4, dxfattribs={"layer": "E-UNIF"})
    _texto(msp, "~", 0, y, 4, alineacion=TextEntityAlignment.MIDDLE_CENTER)
    _texto(msp, f"RED CNEL EP {_t(estudios.tension_media_kv, 1)} kV", 7, y + 1)
    _texto(msp, f"Scc = {_t(estudios.scc_red_mva, 0)} MVA (por confirmar)", 7, y - 2.5)
    _linea(msp, (0, y - 4), (0, y - 14))

    # Transformador.
    y = -19.0
    msp.add_circle((0, y), 5, dxfattribs={"layer": "E-UNIF"})
    msp.add_circle((0, y - 7), 5, dxfattribs={"layer": "E-UNIF"})
    tension = f"{_t(estudios.tension_media_kv, 1)} kV / {sistema.v_linea}-{sistema.v_fase_neutro} V"
    if decision.opcion == "existente" and industria.existente is not None:
        ex = industria.existente
        _texto(msp, f"TRANSFORMADOR EXISTENTE CNEL {ex.codigo or ''}".strip(), 8, y + 1)
        _texto(msp, f"{_t(ex.kva, 1)} kVA {ex.fases}F · {tension}", 8, y - 2.5)
        _texto(msp, "Conexión sujeta a factibilidad de CNEL", 8, y - 6)
    elif decision.transformador is not None:
        t = decision.transformador
        _texto(msp, "TRANSFORMADOR PARTICULAR", 8, y + 1)
        _texto(msp, f"{_t(t.kva, 1)} kVA {t.fases}F · {tension}", 8, y - 2.5)
        _texto(msp, f"Z = {_t(t.z_pct, 2)} % · montaje en {t.montaje}", 8, y - 6)
    y -= 12
    if decision.opcion == "existente" and decision.acometida is not None and industria.existente:
        cable, n = decision.acometida
        conductor = f"{n} × {cable.calibre}" if n > 1 else cable.calibre
        _linea(msp, (0, y), (0, y - 12))
        _texto(
            msp,
            f"Acometida {conductor} por fase · {_t(industria.existente.distancia_m, 0)} m",
            3,
            y - 6,
        )
        y -= 12
    else:
        _linea(msp, (0, y), (0, y - 4))
        y -= 4

    # Medición.
    msp.add_lwpolyline(
        [(-4, y), (4, y), (4, y - 7), (-4, y - 7)], close=True, dxfattribs={"layer": "E-UNIF"}
    )
    _texto(msp, "kWh", 0, y - 3.5, 2, alineacion=TextEntityAlignment.MIDDLE_CENTER)
    principal = analisis.resultado("breaker_principal")
    medidor = principal.detalle.get("medidor", "")
    _texto(msp, f"MEDICIÓN EN {decision.nivel.medicion.upper()} · {medidor}", 7, y - 3.5)
    y -= 7
    _linea(msp, (0, y), (0, y - 4))
    y -= 4

    # Breaker principal.
    tp = cc.get(PRINCIPAL)
    valor = principal.valor
    texto_principal = f"{polos} {valor} A" if isinstance(valor, Decimal) else str(valor)
    yb = _breaker(msp, 0, y)
    _texto(msp, f"PRINCIPAL {texto_principal}", 4, y - 2)
    if tp is not None:
        _texto(msp, f"Icu {_a(tp.capacidad_ka, 'kA')}", 4, y - 5.5)
    _linea(msp, (0, yb), (0, yb - 6))
    y = yb - 6

    # Barra del tablero principal.
    msp.add_lwpolyline(
        [(x0, y), (x0 + total, y)], dxfattribs={"layer": "E-UNIF", "const_width": 1.0}
    )
    _texto(msp, f"TABLERO PRINCIPAL {PRINCIPAL}", x0, y + 2.5)
    if tp is not None:
        _texto(
            msp,
            f"Ik = {_t(tp.ik_ka, 2)} kA · ip = {_t(tp.ip_ka, 1)} kA",
            x0 + total,
            y + 2.5,
            capa="E-UNIF-CC",
            alineacion=TextEntityAlignment.RIGHT,
        )
    barra = y

    x = x0
    if banco > 0:
        cx = x + 20
        _linea(msp, (cx, barra), (cx, barra - 8))
        yb = _breaker(msp, cx, barra - 8)
        _linea(msp, (cx, yb), (cx, yb - 6))
        _linea(msp, (cx - 4, yb - 6), (cx + 4, yb - 6))
        _linea(msp, (cx - 4, yb - 8), (cx + 4, yb - 8))
        _texto(msp, "BANCO DE", cx, yb - 12, alineacion=TextEntityAlignment.MIDDLE_CENTER)
        _texto(
            msp,
            f"CAPACITORES {_t(banco, 1)} kVAr",
            cx,
            yb - 15,
            alineacion=TextEntityAlignment.MIDDLE_CENTER,
        )
        x += extra_banco

    alimentadores = {a.tablero: a for a in estudios.alimentadores}
    fondo = barra
    for (tablero, circuitos), ancho in zip(maquinas_por_tablero.items(), anchos, strict=True):
        cx = x + 8
        alim = alimentadores[tablero]
        _linea(msp, (cx, barra), (cx, barra - 6))
        yb = _breaker(msp, cx, barra - 6)
        _texto(msp, f"{polos} {_a(alim.breaker_a, 'A')}", cx + 3.5, barra - 8)
        if alim.conductor is not None:
            cond = alim.conductor
            _texto(msp, f"{cond.texto} · {_t(cond.longitud_m, 0)} m", cx + 3.5, yb - 6)
            _texto(msp, f"ΔV {_t(cond.caida_pct, 2)} %", cx + 3.5, yb - 9.5)
        else:
            _texto(msp, "sin conductor", cx + 3.5, yb - 6)
        _linea(msp, (cx, yb), (cx, yb - 18))
        ytd = yb - 18
        msp.add_lwpolyline(
            [(cx, ytd), (x + ancho - 8, ytd)], dxfattribs={"layer": "E-UNIF", "const_width": 0.7}
        )
        _texto(msp, f"TABLERO {tablero}", cx, ytd + 2)
        punto = cc.get(tablero)
        if punto is not None:
            _texto(
                msp,
                f"Ik {_t(punto.ik_ka, 2)} kA",
                x + ancho - 8,
                ytd + 2,
                capa="E-UNIF-CC",
                alineacion=TextEntityAlignment.RIGHT,
            )
        for n, circuito in enumerate(circuitos):
            mx = cx + 6 + n * PASO_MAQUINA
            _linea(msp, (mx, ytd), (mx, ytd - 5))
            ym = _breaker(msp, mx, ytd - 5)
            _linea(msp, (mx, ym), (mx, ym - 10))
            fila = next(f for f in analisis.filas if f.maquina.id == circuito.maquina)
            if fila.maquina.tipo == "motor":
                msp.add_circle((mx, ym - 13), 3, dxfattribs={"layer": "E-UNIF"})
                _texto(msp, "M", mx, ym - 13, 2.2, alineacion=TextEntityAlignment.MIDDLE_CENTER)
            else:
                msp.add_lwpolyline(
                    [(mx - 3, ym - 10), (mx + 3, ym - 10), (mx + 3, ym - 16), (mx - 3, ym - 16)],
                    close=True,
                    dxfattribs={"layer": "E-UNIF"},
                )
            lineas = [
                circuito.maquina
                + (f" ×{fila.maquina.cantidad}" if fila.maquina.cantidad > 1 else ""),
                (fila.maquina.descripcion or fila.tipo_nombre)[:18],
                f"{fila.maquina.potencia} {fila.maquina.unidad}",
                f"{circuito.polos}P {_a(circuito.breaker_a, 'A')}",
                circuito.conductor.texto if circuito.conductor else "sin conductor",
            ]
            for k, linea in enumerate(lineas):
                _texto(
                    msp,
                    linea,
                    mx,
                    ym - 20 - k * 3.2,
                    1.8,
                    alineacion=TextEntityAlignment.TOP_CENTER,
                )
            fondo = min(fondo, ym - 20 - len(lineas) * 3.2)
        x += ancho

    # Cuadro de rótulo.
    y = fondo - 10
    _texto(msp, f"DIAGRAMA UNIFILAR · {industria.nombre}", x0, y, 3.5)
    _texto(msp, f"{sistema.descripcion} · Fuente: {estudios.fuente}", x0, y - 5.5)
    _texto(
        msp,
        "BORRADOR sujeto a revisión y firma de un profesional habilitado. Valores por verificar.",
        x0,
        y - 9.5,
    )
    margen = 10.0
    arriba = 10.0
    abajo = y - 14
    msp.add_lwpolyline(
        [
            (x0 - margen, arriba),
            (x0 + total + margen, arriba),
            (x0 + total + margen, abajo),
            (x0 - margen, abajo),
        ],
        close=True,
        dxfattribs={"layer": "E-UNIF-MARCO"},
    )
    return _verificado(doc)
