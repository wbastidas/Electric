"""Lectura del cuadro de cargas industrial desde Excel o CSV, y su plantilla.

La hoja "Cargas" tiene una fila de encabezados y una fila por máquina. Los
encabezados se reconocen sin importar mayúsculas, tildes ni unidades entre
paréntesis; las columnas que faltan toman los valores típicos del perfil.
"""

from __future__ import annotations

import csv
import io
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from electric.errores import DatoInvalido
from electric.industrial.modelo import Maquina

#: Columna de la plantilla → campo de Maquina, con sus nombres alternativos.
COLUMNAS: dict[str, tuple[str, ...]] = {
    "id": ("codigo", "id", "item", "equipo"),
    "descripcion": ("descripcion", "maquina", "nombre"),
    "tablero": ("tablero", "tablero de distribucion"),
    "tipo": ("tipo", "tipo de carga"),
    "cantidad": ("cantidad", "cant"),
    "potencia": ("potencia",),
    "unidad": ("unidad",),
    "fases": ("fases",),
    "tension_v": ("tension", "voltaje"),
    "fp": ("fp", "factor de potencia", "cos phi"),
    "eficiencia": ("eficiencia", "rendimiento"),
    "factor_utilizacion": ("fu", "factor de utilizacion"),
    "factor_simultaneidad": ("fs", "factor de simultaneidad"),
    "arranque": ("arranque", "metodo de arranque"),
}

ENCABEZADOS = (
    "Código",
    "Descripción",
    "Tablero",
    "Tipo",
    "Cantidad",
    "Potencia",
    "Unidad",
    "Fases",
    "Tensión (V)",
    "FP",
    "Eficiencia",
    "Fu",
    "Fs",
    "Arranque",
)

# fmt: off
EJEMPLO: tuple[tuple[Any, ...], ...] = (
    ("M-01", "Compresor de aire", "TD-1", "motor", 1, 25, "HP", 3, None, 0.86, 0.91, 0.8, 1,
     "estrella_triangulo"),
    ("M-02", "Bombas de agua", "TD-1", "motor", 2, 7.5, "HP", 3, None, None, None, None, None,
     "directo"),
    ("R-01", "Horno eléctrico", "TD-2", "resistiva", 1, 30, "kW", 3, None, 1, None, 0.9, 1, None),
    ("S-01", "Soldadoras", "TD-2", "soldadora", 3, 15, "kVA", 3, None, None, None, None, None,
     None),
    ("L-01", "Iluminación de nave", "TD-3", "iluminacion", 1, 6, "kW", 1, None, None, None, None,
     None, None),
    ("T-01", "Tomacorrientes de oficinas", "TD-3", "tomacorrientes", 1, 4, "kW", 1, None, None,
     None, None, None, None),
)
# fmt: on


def _normal(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    base = sin_tildes.lower().split("(")[0]
    return " ".join(base.replace("_", " ").replace(".", " ").split())


def _unidad_en_encabezado(texto: str) -> str | None:
    if "(" not in texto:
        return None
    dentro = texto.split("(", 1)[1].split(")")[0].strip().lower()
    return {"kw": "kW", "hp": "HP", "kva": "kVA"}.get(dentro)


def _mapa(encabezados: list[str]) -> tuple[dict[int, str], str | None]:
    mapa: dict[int, str] = {}
    unidad_potencia = None
    for n, crudo in enumerate(encabezados):
        nombre = _normal(crudo)
        for campo, alias in COLUMNAS.items():
            if nombre in alias and campo not in mapa.values():
                mapa[n] = campo
                if campo == "potencia":
                    unidad_potencia = _unidad_en_encabezado(crudo)
                break
    faltan = [c for c in ("potencia",) if c not in mapa.values()]
    if faltan:
        raise DatoInvalido("el cuadro de cargas no tiene la columna 'Potencia'")
    return mapa, unidad_potencia


def _celda(valor: Any) -> Any:
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = valor.strip()
        if not valor:
            return None
        try:
            return Decimal(valor.replace(",", "."))
        except InvalidOperation:
            return valor
    if isinstance(valor, float):
        return Decimal(str(valor))
    return valor


def _maquinas(filas: list[list[Any]]) -> tuple[Maquina, ...]:
    if not filas:
        raise DatoInvalido("el cuadro de cargas está vacío")
    mapa, unidad = _mapa([str(c or "") for c in filas[0]])
    maquinas: list[Maquina] = []
    errores: list[str] = []
    for numero, fila in enumerate(filas[1:], start=2):
        datos: dict[str, Any] = {}
        for n, campo in mapa.items():
            valor = _celda(fila[n]) if n < len(fila) else None
            if valor is not None:
                datos[campo] = valor
        if not datos:
            continue
        if "potencia" not in datos:
            errores.append(f"fila {numero}: falta la potencia")
            continue
        datos.setdefault("id", f"F{numero}")
        identificador = datos["id"]
        if isinstance(identificador, Decimal) and identificador % 1 == 0:
            identificador = int(identificador)
        datos["id"] = str(identificador)
        for campo in ("cantidad", "fases"):
            if isinstance(datos.get(campo), Decimal):
                datos[campo] = int(datos[campo])
        for campo in ("descripcion", "tablero", "tipo", "arranque", "unidad"):
            if campo in datos:
                datos[campo] = str(datos[campo])
        if "tipo" in datos:
            datos["tipo"] = _normal(datos["tipo"]).replace(" ", "_")
        if "arranque" in datos:
            datos["arranque"] = _normal(datos["arranque"]).replace(" ", "_").replace("-", "_")
        if "unidad" in datos:
            datos["unidad"] = {"kw": "kW", "hp": "HP", "kva": "kVA"}.get(
                datos["unidad"].lower(), datos["unidad"]
            )
        elif unidad:
            datos["unidad"] = unidad
        try:
            maquinas.append(Maquina.model_validate(datos))
        except ValidationError as error:
            detalle = "; ".join(
                f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in error.errors()
            )
            errores.append(f"fila {numero}: {detalle}")
    if errores:
        raise DatoInvalido("el cuadro de cargas tiene errores:\n" + "\n".join(errores))
    if not maquinas:
        raise DatoInvalido("el cuadro de cargas no tiene máquinas")
    return tuple(maquinas)


def leer_cuadro(datos: bytes, nombre: str) -> tuple[Maquina, ...]:
    """Máquinas de un cuadro de cargas en .xlsx o .csv."""
    sufijo = Path(nombre).suffix.lower()
    if sufijo == ".csv":
        texto = datos.decode("utf-8-sig")
        separador = ";" if texto.count(";") > texto.count(",") else ","
        return _maquinas([list(f) for f in csv.reader(io.StringIO(texto), delimiter=separador)])
    if sufijo in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        try:
            libro = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
        except Exception as error:  # openpyxl lanza varios tipos
            raise DatoInvalido(f"no se pudo leer el Excel: {error}") from error
        hoja = libro["Cargas"] if "Cargas" in libro.sheetnames else libro.worksheets[0]
        return _maquinas([list(f) for f in hoja.iter_rows(values_only=True)])
    raise DatoInvalido("el cuadro de cargas debe ser .xlsx o .csv")


def plantilla(tipos: list[tuple[str, str]], arranques: list[tuple[str, str]]) -> bytes:
    """Excel de ejemplo con la hoja Cargas y una hoja de instrucciones."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "Cargas"
    hoja.append(ENCABEZADOS)
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1F4E79")
    for fila in EJEMPLO:
        hoja.append(fila)
    anchos = (9, 28, 9, 15, 9, 9, 8, 7, 11, 7, 10, 7, 7, 19)
    for n, ancho in enumerate(anchos):
        hoja.column_dimensions[chr(65 + n)].width = ancho
    hoja.freeze_panes = "A2"
    for columna, valores in (
        ("D", [t for t, _ in tipos]),
        ("G", ["kW", "HP", "kVA"]),
        ("H", ["1", "3"]),
        ("N", [a for a, _ in arranques]),
    ):
        validacion = DataValidation(type="list", formula1='"' + ",".join(valores) + '"')
        validacion.add(f"{columna}2:{columna}500")
        hoja.add_data_validation(validacion)

    ayuda = libro.create_sheet("Instrucciones")
    lineas = [
        ("Cuadro de cargas industrial",),
        (),
        ("Una fila por máquina o grupo de máquinas iguales. Solo la potencia es obligatoria.",),
        ("Las celdas vacías toman los valores típicos del perfil y la memoria lo indica.",),
        ("Potencia: la de placa de una unidad; en motores, la del eje (HP o kW).",),
        ("Unidad: kW, HP o kVA (soldadoras y transformadores).",),
        ("Fu: factor de utilización; Fs: factor de simultaneidad (entre 0 y 1).",),
        ("Tensión: solo si la placa difiere del sistema elegido.",),
        (),
        ("Tipo", "Descripción"),
        *tipos,
        (),
        ("Arranque (solo motores)", "Descripción"),
        *arranques,
    ]
    for linea in lineas:
        ayuda.append(linea)
    ayuda["A1"].font = Font(bold=True, size=14)
    ayuda.column_dimensions["A"].width = 26
    ayuda.column_dimensions["B"].width = 60
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()
