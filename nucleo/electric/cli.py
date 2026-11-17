"""Línea de comandos del núcleo.

electric calcular ejemplos/vivienda-120m2/proyecto.json
electric validar-perfil perfiles/cnel-ep
electric industrial cuadro.xlsx --existente-kva 75 --clientes C=20 --distancia 60
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import astuple
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from electric.calculo import Calculado, Resultado, calcular, presentar
from electric.calculo.cuadro import cuadro_de_cargas, resumen, tablas_sin_verificar
from electric.errores import ErrorElectric
from electric.modelo import Preferencias, Proyecto, a_json_canonico
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


def informe(calculado: Calculado, perfil: Perfil) -> str:
    """Informe de texto: resumen del proyecto y cuadro de cargas."""
    proyecto = calculado.proyecto
    datos = resumen(calculado, perfil)
    ancho = max(len(d.etiqueta) for d in datos) + 1
    lineas = [
        AVISO_BORRADOR,
        "",
        f"Proyecto: {proyecto.nombre} ({proyecto.id})",
        f"Perfil:   {perfil.meta.nombre}, versión {perfil.meta.version}",
        f"Huella:   {calculado.hash[:16]}",
        "",
        *[f"{(d.etiqueta + ':').ljust(ancho)} {d.texto}" for d in datos],
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
    filas = [astuple(f) for f in cuadro_de_cargas(calculado, perfil)]
    lineas.append(_tabla(encabezado, filas))

    avisos = [f"{r.id} {r.sujeto}: {a}" for r in calculado.resultados for a in r.avisos]
    if avisos:
        lineas += ["", "Avisos", *[f"- {a}" for a in avisos]]

    supuestos = sorted({s for r in calculado.resultados for s in r.supuestos})
    if supuestos:
        lineas += ["", "Supuestos aplicados", *[f"- {s}" for s in supuestos]]

    pendientes = tablas_sin_verificar(calculado)
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


def _disenar(args: argparse.Namespace) -> int:

    from electric.flujo import proyecto_desde_plano
    from electric.salida_cad import generar_dxf, renderizar

    origen = Path(args.plano)
    try:
        contenido = origen.read_bytes()
    except OSError as error:
        raise ErrorElectric(f"no se pudo leer {origen}: {error}") from error
    perfil = cargar_perfil(_carpeta_perfiles(args.perfiles) / args.perfil)
    equipos = tuple(e for e in args.equipos.split(",") if e)
    resultado = proyecto_desde_plano(
        contenido,
        origen.name,
        perfil,
        id=origen.stem,
        nombre=args.nombre or f"Proyecto de {origen.name}",
        equipos=equipos,
        preferencias=Preferencias(
            iluminacion=args.iluminacion,
            zona_climatica=args.zona,
            refrigeradora=not args.sin_refrigeradora,
            exteriores=not args.sin_exteriores,
        ),
        alimentador_m=Decimal(args.alimentador),
        factor_a_metros=args.escala,
    )
    plano = resultado.proyecto.plano
    assert plano is not None
    print(
        f"Plano: {origen.name} · {len(plano.ambientes)} ambientes · {plano.area_construida_m2} m²"
    )
    filas = [(a.id, a.nombre or "(sin nombre)", a.uso, f"{a.area_m2} m²") for a in plano.ambientes]
    print(_tabla(("Ambiente", "Nombre", "Uso", "Área"), filas))
    if resultado.avisos:
        print("\nPor revisar")
        for aviso in resultado.avisos:
            print(f"- {aviso}")
    print()
    print(informe(resultado.calculado, perfil))

    if args.salida:
        carpeta = Path(args.salida)
        carpeta.mkdir(parents=True, exist_ok=True)
        dxf = generar_dxf(contenido, resultado.proyecto, resultado.calculado, perfil)
        (carpeta / "proyecto.json").write_text(
            resultado.proyecto.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (carpeta / "red.dxf").write_bytes(dxf)
        (carpeta / "red.png").write_bytes(renderizar(dxf, "png"))
        (carpeta / "red.pdf").write_bytes(renderizar(dxf, "pdf"))
        print(f"\nEscritos en {carpeta}: proyecto.json, red.dxf, red.png, red.pdf")
    return 0


def _validar_perfil(args: argparse.Namespace) -> int:
    perfil = cargar_perfil(Path(args.carpeta))
    print(f"Perfil {perfil.meta.id} {perfil.meta.version}: válido, {len(perfil.tablas)} tablas")
    for tabla in sorted(perfil.tablas.values(), key=lambda t: t.id):
        print(f"- {tabla.id} v{tabla.version}: {tabla.estado}")
    return 0


def _plantilla_industrial(args: argparse.Namespace) -> int:
    from electric.industrial import plantilla

    perfil = cargar_perfil(_carpeta_perfiles(args.perfiles) / args.perfil)
    datos = plantilla(
        [(t.tipo, t.nombre) for t in perfil.tipos_industriales()],
        [(a.id, a.nombre) for a in perfil.arranques()],
    )
    Path(args.salida).write_bytes(datos)
    print(f"Plantilla escrita en {args.salida}")
    return 0


def _clientes(texto: str) -> dict[str, int]:
    salida: dict[str, int] = {}
    for parte in filter(None, texto.split(",")):
        estrato, _, n = parte.partition("=")
        if not n:
            raise ErrorElectric(f"clientes '{parte}': use ESTRATO=N, por ejemplo C=20")
        salida[estrato.strip()] = int(n)
    return salida


def _distancias(texto: str) -> dict[str, Decimal]:
    salida: dict[str, Decimal] = {}
    for parte in filter(None, texto.split(",")):
        tablero, _, metros = parte.partition("=")
        if not metros:
            raise ErrorElectric(f"distancia '{parte}': use TABLERO=M, por ejemplo TD-1=40")
        salida[tablero.strip()] = Decimal(metros)
    return salida


def _industrial(args: argparse.Namespace) -> int:
    from electric.industrial import Industria, TransformadorExistente, analizar, leer_cuadro
    from electric.industrial.estudios import estudiar
    from electric.industrial.informe import informe_industrial
    from electric.industrial.unifilar import generar_unifilar
    from electric.salida_cad import renderizar

    origen = Path(args.cuadro)
    try:
        contenido = origen.read_bytes()
    except OSError as error:
        raise ErrorElectric(f"no se pudo leer {origen}: {error}") from error
    perfil = cargar_perfil(_carpeta_perfiles(args.perfiles) / args.perfil)
    existente = None
    if args.existente_kva is not None:
        existente = TransformadorExistente(
            codigo=args.codigo,
            kva=Decimal(args.existente_kva),
            fases=args.existente_fases,
            demanda_kva=Decimal(args.demanda) if args.demanda is not None else None,
            clientes=_clientes(args.clientes),
            distancia_m=Decimal(args.distancia),
        )
    industria = Industria(
        nombre=args.nombre or origen.stem,
        sistema=args.sistema,
        maquinas=leer_cuadro(contenido, origen.name),
        fp_objetivo=Decimal(args.fp_objetivo) if args.fp_objetivo else None,
        existente=existente,
        distancias_m=_distancias(args.distancias),
        scc_red_mva=Decimal(args.scc) if args.scc else None,
    )
    analisis = analizar(industria, perfil)
    estudios = estudiar(analisis, perfil)
    print(informe_industrial(analisis, perfil, estudios))
    if args.unifilar:
        destino = Path(args.unifilar)
        dxf = generar_unifilar(analisis, estudios)
        destino.write_bytes(dxf)
        destino.with_suffix(".pdf").write_bytes(renderizar(dxf, "pdf"))
        print(f"\nUnifilar escrito en {destino} y {destino.with_suffix('.pdf')}")
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

    d = comandos.add_parser("disenar", help="lee un plano DXF, diseña la instalación y la calcula")
    d.add_argument("plano", help="plano arquitectónico en DXF")
    d.add_argument("--perfil", default="cnel-ep", help="perfil normativo (por defecto cnel-ep)")
    d.add_argument("--perfiles", help="carpeta que contiene los perfiles")
    d.add_argument("--nombre", help="nombre del proyecto")
    d.add_argument("--equipos", default="", help="cargas especiales, separadas por coma")
    d.add_argument("--alimentador", required=True, help="longitud del medidor al tablero, en m")
    d.add_argument("--escala", type=float, help="metros por unidad de dibujo, si el DXF no lo dice")
    d.add_argument("--zona", help="zona climática: costa, sierra, amazonia, galapagos")
    d.add_argument(
        "--iluminacion", default="plafon", help="estilo: plafon, foco_central, ojos_de_buey"
    )
    d.add_argument("--sin-exteriores", action="store_true", help="sin luces ni tomas de fachada")
    d.add_argument(
        "--sin-refrigeradora", action="store_true", help="sin tomacorriente dedicado de refri"
    )
    d.add_argument(
        "--salida", help="carpeta donde escribir proyecto.json, red.dxf, red.png y red.pdf"
    )
    d.set_defaults(funcion=_disenar)

    i = comandos.add_parser(
        "industrial", help="analiza un cuadro de cargas industrial y la factibilidad del servicio"
    )
    i.add_argument("cuadro", help="cuadro de cargas en .xlsx o .csv")
    i.add_argument("--perfil", default="cnel-ep", help="perfil normativo (por defecto cnel-ep)")
    i.add_argument("--perfiles", help="carpeta que contiene los perfiles")
    i.add_argument("--nombre", help="nombre de la industria")
    i.add_argument("--sistema", default="trifasico_127_220", help="sistema de tensión")
    i.add_argument("--fp-objetivo", help="factor de potencia objetivo")
    i.add_argument("--existente-kva", help="kVA del transformador de CNEL más cercano")
    i.add_argument("--existente-fases", type=int, choices=(1, 3), default=3)
    i.add_argument("--codigo", help="código del transformador existente")
    i.add_argument("--demanda", help="demanda actual medida del transformador, en kVA")
    i.add_argument("--clientes", default="", help="clientes por estrato: C=20,comercial=2")
    i.add_argument("--distancia", default="0", help="metros de acometida hasta la industria")
    i.add_argument("--distancias", default="", help="metros a cada tablero: TD-1=40,TD-2=25")
    i.add_argument("--scc", help="potencia de cortocircuito de la red, en MVA")
    i.add_argument("--unifilar", help="escribe el diagrama unifilar en este .dxf (y su .pdf)")
    i.set_defaults(funcion=_industrial)

    t = comandos.add_parser("plantilla-industrial", help="escribe la plantilla Excel del cuadro")
    t.add_argument("salida", help="archivo .xlsx de salida")
    t.add_argument("--perfil", default="cnel-ep")
    t.add_argument("--perfiles", help="carpeta que contiene los perfiles")
    t.set_defaults(funcion=_plantilla_industrial)

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
