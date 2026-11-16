"""Informe de texto del análisis industrial (para la línea de comandos)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from electric.calculo.resultado import presentar
from electric.industrial.analisis import AnalisisIndustrial
from electric.perfiles.carga import Perfil


def _n(valor: Decimal, decimales: int = 1) -> str:
    return f"{valor:.{decimales}f}".replace(".", ",")


def _tabla(encabezado: tuple[str, ...], filas: Sequence[tuple[str, ...]]) -> str:
    anchos = [max(len(f[n]) for f in (encabezado, *filas)) for n in range(len(encabezado))]
    lineas = ["  ".join(c.ljust(a) for c, a in zip(f, anchos, strict=True)) for f in [encabezado]]
    lineas.append("  ".join("-" * a for a in anchos))
    lineas += ["  ".join(c.ljust(a) for c, a in zip(f, anchos, strict=True)) for f in filas]
    return "\n".join(lineas)


def informe_industrial(analisis: AnalisisIndustrial, perfil: Perfil) -> str:
    partes = [f"{analisis.industria.nombre} · {analisis.sistema.descripcion}", ""]
    filas = [
        (
            f.maquina.id,
            f.maquina.descripcion[:28],
            f.maquina.tablero,
            str(f.maquina.cantidad),
            f"{f.maquina.potencia} {f.maquina.unidad}",
            _n(f.instalada_kw, 2),
            _n(f.fp, 2),
            _n(f.corriente_a),
            _n(f.demanda_kw, 2),
            f.arranque or "",
        )
        for f in analisis.filas
    ]
    partes.append(
        _tabla(
            (
                "Código",
                "Descripción",
                "Tablero",
                "Cant",
                "Placa",
                "kW",
                "FP",
                "In A",
                "Dem kW",
                "Arranque",
            ),
            filas,
        )
    )
    partes += ["", "Tableros"]
    partes.append(
        _tabla(
            ("Tablero", "Instalada kW", "Demanda kW", "kVA", "FP", "I A", "Breaker"),
            [
                (
                    t.tablero,
                    _n(t.instalada_kw, 2),
                    _n(t.demanda_kw, 2),
                    _n(t.demanda_kva, 2),
                    _n(t.fp, 2),
                    _n(t.corriente_a),
                    f"{t.breaker_a} A" if t.breaker_a is not None else "fuera de serie",
                )
                for t in analisis.tableros
            ],
        )
    )
    partes += ["", "Resultados"]
    for r in analisis.resultados:
        partes.append(f"- {r.nombre}: {presentar(r.valor, r.unidad, perfil)}")
        for aviso in r.avisos:
            partes.append(f"    ! {aviso}")
    d = analisis.decision
    partes += ["", f"Decisión: {d.titulo}"]
    for motivo in d.motivos:
        partes.append(f"- {motivo}")
    for c in d.comprobaciones:
        partes.append(f"  [{'ok' if c.cumple else 'NO'}] {c.nombre}: {c.detalle}")
    if d.transformador is not None and d.opcion != "existente":
        t = d.transformador
        partes.append(
            f"Transformador propuesto: {t.kva} kVA, {t.fases}F, {t.montaje}, Z {t.z_pct} %"
        )
    if analisis.avisos:
        partes += ["", "Por revisar"] + [f"- {a}" for a in analisis.avisos]
    partes += ["", f"Estado de las tablas usadas: {analisis.estado}"]
    return "\n".join(partes)
