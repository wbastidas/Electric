"""Línea de comandos del núcleo.

electric calcular ejemplos/vivienda-120m2/proyecto.json
electric validar-perfil perfiles/cnel-ep
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from electric.calculo import ALIMENTADOR, PROYECTO, Calculado, Resultado, calcular, presentar
from electric.errores import ErrorElectric
from electric.modelo import Proyecto, a_json_canonico
from electric.perfiles import Perfil, cargar_perfil

AVISO_BORRADOR = (
    "BORRADOR sujeto a revisión y firma de un profesional habilitado. "
    "No válido para presentar a CNEL EP."
)


def _carpeta_perfiles(indicada: str | None) -> Path:
    if indicada:
        return Path(indicada)
    for base in (Path.cwd(), *Path.cwd().parents):
        if (base / "perfiles").is_dir():
            return base / "perfiles"
    raise ErrorElectric("no se encontró la carpeta 'perfiles'; indíquela con --perfiles")


def _tabla(encabezado: Sequence[str], filas: Sequence[Sequence[str]]) -> str:
    anchos = [max(len(f[n]) for f in (encabezado, *filas)) for n in range(len(encabezado))]
    linea = "  ".join("-" * a for a in anchos)
    cuerpo = ["  ".join(c.ljust(a) for c, a in zip(f, anchos, strict=True)) for f in filas]
    cabeza = "  ".join(c.ljust(a) for c, a in zip(encabezado, anchos, strict=True))
    return "\n".join([cabeza, linea, *cuerpo])


def _texto(resultado: Resultado, perfil: Perfil) -> str:
    return presentar(resultado.valor, resultado.unidad, perfil)


def _breaker(calculado: Calculado, sujeto: str) -> str:
    resultado = calculado.res("RC-09", sujeto)
    return f"{resultado.det('polos'):f}P {resultado.decimal.normalize():f} A"


def informe(calculado: Calculado, perfil: Perfil) -> str:
    """Informe de texto: resumen del proyecto y cuadro de cargas."""
    proyecto = calculado.proyecto

    def v(id: str, sujeto: str) -> str:
        return _texto(calculado.res(id, sujeto), perfil)

    lineas = [
        AVISO_BORRADOR,
        "",
        f"Proyecto: {proyecto.nombre} ({proyecto.id})",
        f"Perfil:   {perfil.meta.nombre}, versión {perfil.meta.version}",
        f"Huella:   {calculado.hash[:16]}",
        "",
        f"Carga instalada:    {v('RC-01', PROYECTO)}",
        f"Demanda máxima:     {v('RC-03', PROYECTO)}",
        f"Clasificación CNEL: {v('RC-05', PROYECTO)}",
        f"Circuitos mínimos:  {v('RC-02', PROYECTO)}",
        f"Desbalance:         {v('RC-10', PROYECTO)}",
        f"Tablero:            {proyecto.tablero.id}, {v('RC-11', proyecto.tablero.id)}, "
        f"principal {_breaker(calculado, ALIMENTADOR)}",
        f"Medidor:            {v('RC-12', PROYECTO)}",
        f"Tierra:             resistencia objetivo menor que {v('RC-14', PROYECTO)}",
        "",
        "Cuadro de cargas",
    ]
    encabezado = (
        "Circuito",
        "Tipo",
        "Fase",
        "Carga",
        "Corriente",
        "Breaker",
        "Conductor",
        "Tierra",
        "Ducto",
        "Longitud",
        "Caída",
    )
    tipos = {c.id: c.tipo for c in proyecto.circuitos}
    largos = {c.id: c.longitud_m for c in proyecto.circuitos}
    filas = []
    for sujeto in [*tipos, ALIMENTADOR]:
        es_ramal = sujeto != ALIMENTADOR
        largo = largos[sujeto] if es_ramal else proyecto.tablero.alimentador_longitud_m
        filas.append(
            (
                sujeto,
                tipos.get(sujeto, "alimentador"),
                v("RC-10", sujeto) if es_ramal else "",
                v("RC-01", sujeto) if es_ramal else v("RC-03", PROYECTO),
                v("RC-06", sujeto),
                _breaker(calculado, sujeto),
                v("RC-07", sujeto),
                v("RC-14", sujeto),
                v("RC-13", sujeto),
                presentar(largo, "m", perfil),
                v("RC-08", sujeto),
            )
        )
    lineas.append(_tabla(encabezado, filas))

    avisos = [f"{r.id} {r.sujeto}: {a}" for r in calculado.resultados for a in r.avisos]
    if avisos:
        lineas += ["", "Avisos", *[f"- {a}" for a in avisos]]

    supuestos = sorted({s for r in calculado.resultados for s in r.supuestos})
    if supuestos:
        lineas += ["", "Supuestos aplicados", *[f"- {s}" for s in supuestos]]

    pendientes = sorted(
        {
            (t.id, t.version, t.estado)
            for r in calculado.resultados
            for t in r.tablas
            if t.estado != "verificado"
        }
    )
    if pendientes:
        lineas += ["", f"Tablas sin verificar usadas en este cálculo: {len(pendientes)}"]
        lineas += [f"- {i} {ver} ({estado})" for i, ver, estado in pendientes]
    return "\n".join(lineas)


def explicacion(calculado: Calculado, perfil: Perfil, filtro: str | None) -> str:
    """Detalle de cada resultado: fórmula, entradas, tablas y estado (RF-23)."""
    bloques = []
    for r in calculado.resultados:
        if filtro and filtro not in (r.id, f"{r.id}:{r.sujeto}"):
            continue
        lineas = [f"{r.id} · {r.sujeto} · {r.nombre}: {_texto(r, perfil)}  [{r.estado}]"]
        lineas.append(f"  fórmula: {r.formula}")
        for clave, valor in r.entradas.items():
            lineas.append(f"  entrada {clave} = {presentar(valor, '', perfil)}")
        for clave, valor in r.detalle.items():
            lineas.append(f"  detalle {clave} = {presentar(valor, '', perfil)}")
        for t in r.tablas:
            lineas.append(f"  tabla {t.id} v{t.version}, fila «{t.fila}» ({t.estado})")
        for s in r.supuestos:
            lineas.append(f"  supuesto: {s}")
        for a in r.avisos:
            lineas.append(f"  aviso: {a}")
        bloques.append("\n".join(lineas))
    return "\n\n".join(bloques)


def cargar_proyecto(ruta: Path) -> Proyecto:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"), parse_float=str)
    except (OSError, json.JSONDecodeError) as error:
        raise ErrorElectric(f"no se pudo leer {ruta}: {error}") from error
    try:
        return Proyecto.model_validate(datos)
    except ValidationError as error:
        raise ErrorElectric(f"el proyecto {ruta} no es válido:\n{error}") from error


def _calcular(args: argparse.Namespace) -> int:
    proyecto = cargar_proyecto(Path(args.proyecto))
    perfil = cargar_perfil(_carpeta_perfiles(args.perfiles) / proyecto.perfil.id)
    calculado = calcular(proyecto, perfil)
    if args.json:
        print(
            a_json_canonico(
                {
                    "aviso": AVISO_BORRADOR,
                    "huella": calculado.hash,
                    "perfil": {"id": calculado.perfil_id, "version": calculado.perfil_version},
                    "resultados": list(calculado.resultados),
                }
            )
        )
    elif args.explicar is not None:
        print(explicacion(calculado, perfil, args.explicar or None))
    else:
        print(informe(calculado, perfil))
    return 0


def _validar_perfil(args: argparse.Namespace) -> int:
    perfil = cargar_perfil(Path(args.carpeta))
    print(f"Perfil {perfil.meta.id} {perfil.meta.version}: válido, {len(perfil.tablas)} tablas")
    for tabla in sorted(perfil.tablas.values(), key=lambda t: t.id):
        print(f"- {tabla.id} v{tabla.version}: {tabla.estado}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(prog="electric", description=__doc__)
    comandos = analizador.add_subparsers(dest="comando", required=True)

    c = comandos.add_parser("calcular", help="calcula un proyecto y muestra el cuadro de cargas")
    c.add_argument("proyecto", help="archivo JSON del proyecto")
    c.add_argument("--perfiles", help="carpeta que contiene los perfiles")
    c.add_argument("--json", action="store_true", help="salida JSON canónica")
    c.add_argument(
        "--explicar",
        nargs="?",
        const="",
        metavar="RC[:SUJETO]",
        help="muestra fórmula, entradas y tablas de cada resultado, o solo del indicado",
    )
    c.set_defaults(funcion=_calcular)

    p = comandos.add_parser("validar-perfil", help="valida un perfil y lista sus tablas")
    p.add_argument("carpeta", help="carpeta del perfil")
    p.set_defaults(funcion=_validar_perfil)

    args = analizador.parse_args(argv)
    try:
        resultado: int = args.funcion(args)
    except ErrorElectric as error:
        print(f"Error ({error.codigo}): {error}", file=sys.stderr)
        return 1
    return resultado


if __name__ == "__main__":
    sys.exit(main())
