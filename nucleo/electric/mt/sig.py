"""Red existente desde el geoportal de CNEL (ArcGIS REST) o desde un archivo GeoJSON.

Las URL de las capas y los nombres de sus campos vienen de la tabla `sig` del
perfil, para poder corregirlos sin cambiar el código. Se piden en WGS84
(`outSR=4326`) los elementos que están dentro de un radio alrededor del
punto del proyecto.

El servicio es un MapServer: si una capa no tiene URL, se busca por su nombre
en la lista de capas del servicio (una o todas las que coincidan, p. ej. tramos
aéreos y subterráneos), y cada campo se busca entre sus nombres posibles
(también por alias). Los campos con dominio codificado (fases 7 → «ABC»,
voltaje 13800 → «13.8 kV») se traducen con los dominios que publica cada capa.
"""

from __future__ import annotations

import json
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from electric.errores import DatoInvalido, ErrorElectric
from electric.mt.modelo import (
    Coordenada,
    PosteSIG,
    ProteccionSIG,
    RedExistente,
    TramoSIG,
    TransformadorSIG,
)
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import FilaCapaSIG


class ErrorSIG(ErrorElectric):
    """El geoportal no respondió o respondió algo que no se pudo leer."""

    codigo = "sig_no_disponible"


def _texto(valor: Any) -> str | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def _decimal(valor: Any) -> Decimal | None:
    try:
        return Decimal(str(valor)) if valor not in (None, "") else None
    except InvalidOperation:
        return None


def _campo(atributos: dict[str, Any], capa: FilaCapaSIG, clave: str) -> Any:
    nombre = capa.campos.get(clave)
    if nombre is None:
        return None
    if nombre in atributos:
        return atributos[nombre]
    # Los servicios no siempre respetan mayúsculas.
    for k, v in atributos.items():
        if k.lower() == nombre.lower():
            return v
    return None


def _id(atributos: dict[str, Any], capa: FilaCapaSIG, n: int) -> str:
    return _texto(_campo(atributos, capa, "id")) or f"{capa.capa}-{n}"


def _punto(geometria: dict[str, Any]) -> tuple[Decimal, Decimal] | None:
    """(lat, lon) de una geometría de punto ArcGIS o GeoJSON."""
    if "x" in geometria and "y" in geometria:
        return Decimal(str(geometria["y"])), Decimal(str(geometria["x"]))
    if geometria.get("type") == "Point":
        lon, lat = geometria["coordinates"][:2]
        return Decimal(str(lat)), Decimal(str(lon))
    return None


def _linea(geometria: dict[str, Any]) -> list[tuple[Decimal, Decimal]]:
    if "paths" in geometria:
        caminos = geometria["paths"]
    elif geometria.get("type") == "LineString":
        caminos = [geometria["coordinates"]]
    elif geometria.get("type") == "MultiLineString":
        caminos = geometria["coordinates"]
    else:
        return []
    return [(Decimal(str(p[1])), Decimal(str(p[0]))) for camino in caminos for p in camino]


def _elementos(
    capa: FilaCapaSIG, rasgos: list[tuple[dict[str, Any], dict[str, Any]]]
) -> tuple[list[Any], int]:
    """Convierte (atributos, geometría) de una capa; devuelve también cuántos se omitieron."""
    salida: list[Any] = []
    omitidos = 0
    for n, (atr, geo) in enumerate(rasgos, start=1):
        ident = _id(atr, capa, n)
        if capa.capa == "tramos_mt":
            puntos = _linea(geo)
            if len(puntos) < 2:
                omitidos += 1
                continue
            salida.append(
                TramoSIG(
                    id=ident,
                    puntos=tuple(Coordenada(lat=la, lon=lo) for la, lo in puntos),
                    conductor=_texto(_campo(atr, capa, "conductor")),
                    fases=_texto(_campo(atr, capa, "fases")),
                    alimentador=_texto(_campo(atr, capa, "alimentador")),
                    tension=_texto(_campo(atr, capa, "tension")),
                )
            )
            continue
        punto = _punto(geo)
        if punto is None:
            omitidos += 1
            continue
        lat, lon = punto
        comunes = {"id": ident, "lat": lat, "lon": lon}
        alimentador = _texto(_campo(atr, capa, "alimentador"))
        if capa.capa == "postes":
            salida.append(
                PosteSIG(
                    **comunes,
                    estructura=_texto(_campo(atr, capa, "estructura")),
                    material=_texto(_campo(atr, capa, "material")),
                    altura=_texto(_campo(atr, capa, "altura")),
                    alimentador=alimentador,
                )
            )
        elif capa.capa == "transformadores":
            clientes = _decimal(_campo(atr, capa, "clientes"))
            salida.append(
                TransformadorSIG(
                    **comunes,
                    kva=_decimal(_campo(atr, capa, "kva")),
                    fases=_texto(_campo(atr, capa, "fases")),
                    clientes=int(clientes) if clientes is not None else None,
                    alimentador=alimentador,
                    cargabilidad_pct=_decimal(_campo(atr, capa, "cargabilidad")),
                )
            )
        else:
            salida.append(
                ProteccionSIG(
                    **comunes,
                    tipo=_texto(_campo(atr, capa, "tipo")),
                    capacidad=_texto(_campo(atr, capa, "capacidad")),
                    alimentador=alimentador,
                )
            )
    return salida, omitidos


def _armar(
    perfil: Perfil,
    por_capa: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]],
    origen: str,
    capas: list[FilaCapaSIG] | None = None,
) -> tuple[RedExistente, list[str]]:
    avisos: list[str] = []
    listas: dict[str, list[Any]] = {}
    for capa in capas if capas is not None else perfil.capas_sig():
        elementos, omitidos = _elementos(capa, por_capa.get(capa.capa, []))
        listas[capa.capa] = elementos
        if omitidos:
            avisos.append(f"{omitidos} elementos de {capa.capa} sin geometría válida se omitieron.")
    return (
        RedExistente(
            postes=tuple(listas.get("postes", [])),
            tramos=tuple(listas.get("tramos_mt", [])),
            transformadores=tuple(listas.get("transformadores", [])),
            protecciones=tuple(listas.get("protecciones", [])),
            origen=origen,
        ),
        avisos,
    )


def leer_geojson(datos: bytes, perfil: Perfil) -> tuple[RedExistente, list[str]]:
    """Red existente desde un GeoJSON.

    Cada rasgo indica su capa en la propiedad `capa` (postes, tramos_mt,
    transformadores, protecciones); si falta, las líneas son tramos de MT y los
    puntos, postes. Los demás campos siguen los nombres de la tabla `sig`.
    """
    try:
        coleccion = json.loads(datos.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DatoInvalido(f"el archivo no es un GeoJSON válido: {error}") from error
    if coleccion.get("type") != "FeatureCollection":
        raise DatoInvalido("el GeoJSON debe ser una FeatureCollection")
    por_capa: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for rasgo in coleccion.get("features", []):
        atr = rasgo.get("properties") or {}
        geo = rasgo.get("geometry") or {}
        capa = atr.get("capa") or (
            "tramos_mt" if geo.get("type") in ("LineString", "MultiLineString") else "postes"
        )
        por_capa.setdefault(capa, []).append((atr, geo))
    # Cada campo se busca entre sus nombres posibles, como en el geoportal.
    capas = []
    for fila in perfil.capas_sig():
        presentes = [{"name": k} for k in {k for a, _ in por_capa.get(fila.capa, []) for k in a}]
        hallados = _resolver_campos(fila, presentes)
        capas.append(
            fila.model_copy(
                update={"campos": {d: c or fila.campos[d] for d, c in hallados.items()}}
            )
        )
    return _armar(perfil, por_capa, "archivo GeoJSON", capas)


def url_consulta(capa: FilaCapaSIG, lat: Decimal, lon: Decimal, radio_m: int) -> str:
    if not capa.url:
        raise ErrorSIG(f"falta la URL de la capa {capa.capa} en la tabla sig del perfil")
    parametros = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": str(radio_m),
        "units": "esriSRUnit_Meter",
        "outFields": "*",
        "outSR": "4326",
        "returnGeometry": "true",
        "f": "json",
    }
    return f"{capa.url.rstrip('/')}/query?{urllib.parse.urlencode(parametros)}"


def leer_featureset(texto: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Atributos y geometría de una respuesta ArcGIS REST en JSON."""
    datos = _json(texto)
    return [(f.get("attributes") or {}, f.get("geometry") or {}) for f in datos.get("features", [])]


# --- Conexión y reconocimiento de capas y campos ---------------------------------------

Lector = Callable[[str], str]


def leer_url(url: str, tiempo_s: float = 20) -> str:
    try:
        with urllib.request.urlopen(url, timeout=tiempo_s) as respuesta:  # noqa: S310
            texto: str = respuesta.read().decode("utf-8")
            return texto
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ErrorSIG(f"no se pudo conectar con el geoportal: {error}") from error


def _json(texto: str) -> dict[str, Any]:
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as error:
        raise ErrorSIG(f"el geoportal no respondió JSON: {error}") from error
    if not isinstance(datos, dict):
        raise ErrorSIG("el geoportal respondió algo que no es un objeto JSON")
    if "error" in datos:
        raise ErrorSIG(f"el geoportal respondió con un error: {datos['error']}")
    return datos


def _normal(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().replace("_", " ").split())


@dataclass(frozen=True)
class CapaResuelta:
    capa: str
    url: str | None
    #: Nombre de la capa en el servicio.
    nombre: str | None
    #: Dato → campo encontrado en la capa (None si no se encontró).
    campos: dict[str, str | None]
    #: Campos que tiene la capa en el servicio.
    disponibles: tuple[str, ...]
    #: Dominios codificados: campo → {código: nombre}.
    dominios: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Descubrimiento:
    servicio: str | None
    capas: tuple[CapaResuelta, ...]
    #: Todas las capas del servicio: (id, nombre).
    capas_servicio: tuple[tuple[int, str], ...]
    avisos: tuple[str, ...]


def _coincide(palabra: str, nombre: str) -> bool:
    """Una palabra suelta coincide con el inicio de una palabra del nombre (poste → Postes);
    una frase, si aparece entera."""
    objetivo = _normal(palabra)
    texto = _normal(nombre)
    if " " in objetivo:
        return objetivo in texto
    return any(p.startswith(objetivo) for p in texto.split(" "))


def _elegir_capas(
    capa: FilaCapaSIG, capas: list[tuple[int, str]], usadas: set[int]
) -> list[tuple[int, str]]:
    """Capas del servicio para un dato: la primera que coincide, o todas si `todas`."""
    libres = [
        (i, n)
        for i, n in capas
        if i not in usadas and not any(_coincide(x, n) for x in capa.excluir)
    ]
    if capa.todas:
        return [(i, n) for i, n in libres if any(_coincide(p, n) for p in capa.palabras)]
    for palabra in capa.palabras:
        candidatas = [(i, n) for i, n in libres if _coincide(palabra, n)]
        if candidatas:
            return candidatas[:1]
    return []


def _dominios(campos_capa: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    salida: dict[str, dict[str, str]] = {}
    for c in campos_capa:
        valores = (c.get("domain") or {}).get("codedValues") or []
        if valores:
            salida[str(c.get("name"))] = {
                str(v.get("code")): str(v.get("name")) for v in valores if "code" in v
            }
    return salida


def _resolver_campos(capa: FilaCapaSIG, campos_capa: list[dict[str, Any]]) -> dict[str, str | None]:
    nombres = {_normal(str(c.get("name", ""))): str(c.get("name")) for c in campos_capa}
    alias = {_normal(str(c.get("alias", ""))): str(c.get("name")) for c in campos_capa}
    salida: dict[str, str | None] = {}
    for dato, preferido in capa.campos.items():
        encontrado = None
        for candidato in (preferido, *capa.alternativos.get(dato, ())):
            clave = _normal(candidato)
            encontrado = nombres.get(clave) or alias.get(clave)
            if encontrado:
                break
        salida[dato] = encontrado
    return salida


def descubrir(
    perfil: Perfil, leer: Lector | None = None, solo: set[str] | None = None
) -> Descubrimiento:
    """Qué capa del servicio corresponde a cada dato y con qué campos.

    `solo` limita el reconocimiento a esos datos (p. ej. {"transformadores"}).
    """
    leer = leer or leer_url
    servicio = perfil.servicio_sig()
    avisos: list[str] = []
    capas_servicio: list[tuple[int, str]] = []
    if servicio:
        datos = _json(leer(f"{servicio.rstrip('/')}?f=json"))
        capas_servicio = [
            (int(c["id"]), str(c.get("name", ""))) for c in datos.get("layers", []) if "id" in c
        ]
    usadas: set[int] = set()
    for capa in perfil.capas_sig():
        if capa.url:
            final = capa.url.rstrip("/").rsplit("/", 1)[-1]
            if final.isdigit():
                usadas.add(int(final))
    resueltas: list[CapaResuelta] = []
    for capa in perfil.capas_sig():
        if solo is not None and capa.capa not in solo:
            continue
        destinos: list[tuple[str, str | None]] = []
        if capa.url:
            destinos = [(capa.url, None)]
        elif servicio:
            for i, n in _elegir_capas(capa, capas_servicio, usadas):
                usadas.add(i)
                destinos.append((f"{servicio.rstrip('/')}/{i}", n))
        if not destinos:
            avisos.append(
                f"No se encontró en el servicio la capa de {capa.capa.replace('_', ' ')}."
            )
            resueltas.append(CapaResuelta(capa.capa, None, None, {}, ()))
            continue
        for url, nombre in destinos:
            info = _json(leer(f"{url.rstrip('/')}?f=json"))
            nombre = nombre or str(info.get("name", "")) or None
            campos_capa = list(info.get("fields") or [])
            resueltos = _resolver_campos(capa, campos_capa)
            faltan = [
                d
                for d, c in resueltos.items()
                # En protecciones, el tipo de equipo sale del nombre de la capa.
                if c is None and not (capa.capa == "protecciones" and d == "tipo")
            ]
            if faltan:
                avisos.append(
                    f"Capa «{nombre}»: no se encontraron los campos de {', '.join(faltan)}; "
                    "agréguelos en la tabla sig del perfil."
                )
            resueltas.append(
                CapaResuelta(
                    capa=capa.capa,
                    url=url,
                    nombre=nombre,
                    campos=resueltos,
                    disponibles=tuple(str(c.get("name")) for c in campos_capa),
                    dominios=_dominios(campos_capa),
                )
            )
    return Descubrimiento(
        servicio=servicio,
        capas=tuple(resueltas),
        capas_servicio=tuple(capas_servicio),
        avisos=tuple(avisos),
    )


def consultar_geoportal(
    perfil: Perfil,
    lat: Decimal,
    lon: Decimal,
    radio_m: int = 300,
    leer: Lector | None = None,
    solo: set[str] | None = None,
) -> tuple[RedExistente, list[str]]:
    """Red existente alrededor de un punto, consultando cada capa reconocida del geoportal."""
    if not perfil.servicio_sig() and not any(c.url for c in perfil.capas_sig()):
        raise ErrorSIG("falta la URL del servicio del geoportal en la tabla sig del perfil")
    leer = leer or leer_url
    hallazgo = descubrir(perfil, leer, solo)
    avisos = list(hallazgo.avisos)
    por_capa: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    configuradas: dict[str, FilaCapaSIG] = {c.capa: c for c in perfil.capas_sig()}
    resueltas: dict[str, FilaCapaSIG] = {}
    for capa in hallazgo.capas:
        if capa.url is None:
            continue
        campos = {d: c for d, c in capa.campos.items() if c is not None}
        fila = configuradas[capa.capa].model_copy(update={"url": capa.url, "campos": campos})
        rasgos = leer_featureset(leer(url_consulta(fila, lat, lon, radio_m)))
        # Todas las capas de un mismo dato se leen con nombres de campo comunes.
        normales: dict[str, str] = {}
        for dato in configuradas[capa.capa].campos:
            normales[dato] = f"__{dato}"
        for atr, _geo in rasgos:
            traducidos: dict[str, Any] = {}
            for dato, campo in campos.items():
                valor = atr.get(campo)
                dominio = capa.dominios.get(campo)
                if dominio is not None and valor is not None:
                    clave = _texto(valor)
                    valor = dominio.get(clave or "", valor)
                traducidos[dato] = valor
            if capa.capa == "protecciones" and capa.nombre:
                # El tipo de equipo es el nombre de la capa (Seccionador Fusible, …).
                propio = _texto(traducidos.get("tipo"))
                traducidos["tipo"] = capa.nombre if not propio else f"{capa.nombre} ({propio})"
            for dato in normales:
                atr[normales[dato]] = traducidos.get(dato)
        resueltas[capa.capa] = configuradas[capa.capa].model_copy(
            update={"url": capa.url, "campos": normales}
        )
        por_capa.setdefault(capa.capa, []).extend(rasgos)
    if not resueltas:
        raise ErrorSIG("no se reconoció ninguna capa del geoportal")
    red, otros = _armar(perfil, por_capa, "geoportal CNEL", list(resueltas.values()))
    return red, avisos + otros


# --- Transformador más cercano a una carga ---------------------------------------------


@dataclass(frozen=True)
class TransformadorCercano:
    transformador: TransformadorSIG
    distancia_m: Decimal
    #: Demanda actual según la cargabilidad del SIG (None si el SIG no la tiene).
    demanda_kva: Decimal | None
    #: Fases del servicio que puede dar: 1 o 3.
    fases_servicio: int


def fases_servicio(t: TransformadorSIG) -> int:
    """1 o 3 según las fases conectadas: un banco de dos transformadores (delta abierta)
    da servicio trifásico."""
    letras = sum(1 for c in (t.fases or "") if c.upper() in "ABC")
    if letras >= 3:
        return 3
    if letras == 2 and ";" in t.id:
        return 3
    return 1


def transformadores_cercanos(
    perfil: Perfil,
    lat: Decimal,
    lon: Decimal,
    radio_m: int = 300,
    leer: Lector | None = None,
) -> tuple[list[TransformadorCercano], list[str]]:
    """Transformadores del geoportal alrededor de un punto, del más cercano al más lejano."""
    from electric.mt.calculo import proyectar

    red, avisos = consultar_geoportal(perfil, lat, lon, radio_m, leer, {"transformadores"})
    salida: list[TransformadorCercano] = []
    for t in red.transformadores:
        x, y = proyectar(t.lat, t.lon, lat, lon)
        demanda = None
        if t.kva is not None and t.cargabilidad_pct is not None and t.cargabilidad_pct > 0:
            demanda = (t.kva * t.cargabilidad_pct / 100).quantize(Decimal("0.1"))
        salida.append(
            TransformadorCercano(
                transformador=t,
                distancia_m=Decimal(str(round((x * x + y * y) ** 0.5, 1))),
                demanda_kva=demanda,
                fases_servicio=fases_servicio(t),
            )
        )
    salida.sort(key=lambda c: c.distancia_m)
    return salida, avisos
