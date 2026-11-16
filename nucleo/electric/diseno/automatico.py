"""Diseño automático: del plano interpretado a puntos, circuitos y recorridos.

Sigue las plantillas por tipo de ambiente del perfil (RF-15) y los límites de
puntos por circuito (RF-18). Es determinista: mismos ambientes y mismo perfil
dan la misma instalación. Los criterios de colocación son una propuesta de
partida, marcada por verificar, que el ingeniero revisa.

Simplificaciones de esta versión, a la vista del usuario:
- Los recorridos son ortogonales y encadenan los puntos de cada circuito; no
  esquivan muros ni comparten ducto entre circuitos.
- La longitud para la caída de tensión es la equivalente por momento de carga:
  el promedio de la distancia del tablero a cada punto, incluidas las bajadas
  desde el techo. Es exacta para la caída en el último punto porque todos los
  puntos de un circuito tienen la misma potencia por defecto.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from electric.diseno.trazado import Coord, trazar_red
from electric.errores import DatoInvalido, FilaNoEncontrada
from electric.modelo.entidades import (
    CargaEspecial,
    Circuito,
    Preferencias,
    Punto,
    TipoCircuito,
)
from electric.modelo.plano import Ambiente, Interruptor, Plano, Ubicacion, mm
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import FilaPlantilla

#: Separación del punto respecto de la cara del muro, hacia el ambiente.
DESDE_MURO_M = 0.05
#: Distancias mínimas de un punto de pared a un vano y a una esquina.
LIBRE_DE_PUERTA_M = 0.40
LIBRE_DE_ESQUINA_M = 0.30
ENTRE_PUNTOS_M = 0.80
PASO_M = 0.10
#: Ambiente de lo que va fuera de la edificación: luces y tomas de fachada.
EXTERIOR = "EXT"


@dataclass(frozen=True)
class Diseno:
    puntos: tuple[Punto, ...]
    cargas_especiales: tuple[CargaEspecial, ...]
    circuitos: tuple[Circuito, ...]
    plano: Plano
    #: Decisiones que el usuario debería revisar.
    avisos: tuple[str, ...]


@dataclass
class _Recinto:
    ambiente: Ambiente
    poligono: Polygon
    plantilla: FilaPlantilla
    vanos: list[LineString]

    def candidatos_de_pared(self) -> list[tuple[float, Coord]]:
        """Puntos sobre la pared, libres de vanos y esquinas: (distancia recorrida, punto)."""
        anillo = self.poligono.exterior
        vertices = [Point(c) for c in anillo.coords]
        validos = []
        pasos = int(anillo.length / PASO_M)
        for i in range(pasos):
            s = i * PASO_M
            p = anillo.interpolate(s)
            if any(p.distance(v) < LIBRE_DE_ESQUINA_M for v in vertices):
                continue
            if any(p.distance(vano) < LIBRE_DE_PUERTA_M for vano in self.vanos):
                continue
            validos.append((s, self.hacia_adentro(p)))
        return validos

    def hacia_adentro(self, p: Point) -> Coord:
        """Desplaza un punto del contorno unos centímetros hacia el interior."""
        mejor: tuple[float, Coord] = (-1.0, (p.x, p.y))
        for angulo in range(0, 360, 45):
            a = math.radians(angulo)
            q = Point(p.x + DESDE_MURO_M * math.cos(a), p.y + DESDE_MURO_M * math.sin(a))
            if not self.poligono.contains(q):
                continue
            separacion = round(self.poligono.exterior.distance(q), 6)
            if separacion > mejor[0]:
                mejor = (separacion, (q.x, q.y))
        return mejor[1]


def _interior(poligono: Polygon) -> Coord:
    punto = poligono.representative_point()
    return (punto.x, punto.y)


def _techo(valor: Decimal) -> int:
    return int(valor.to_integral_value(rounding=ROUND_CEILING))


def _luminarias(
    recinto: _Recinto,
    area_por_luminaria: Decimal | None = None,
    minimo: int | None = None,
    distribucion: str = "eje",
) -> list[Coord]:
    """Luminarias en fila por el lado mayor del ambiente, o en cuadrícula."""
    plantilla = recinto.plantilla
    area = area_por_luminaria or plantilla.area_por_luminaria_m2
    n = max(
        plantilla.luminarias_min if minimo is None else minimo,
        _techo(recinto.ambiente.area_m2 / area),
    )
    if n <= 0:
        return []
    if distribucion == "reticula" and n > 1:
        return _reticula(recinto.poligono, n)
    poligono = recinto.poligono
    if n == 1:
        centro = poligono.centroid
        if not poligono.contains(centro):
            centro = poligono.representative_point()
        return [(centro.x, centro.y)]
    rectangulo = poligono.minimum_rotated_rectangle
    if not isinstance(rectangulo, Polygon):
        punto = poligono.representative_point()
        return [(punto.x, punto.y)]
    caja = list(rectangulo.exterior.coords)[:4]
    a, b, c = caja[0], caja[1], caja[2]
    if math.dist(a, b) < math.dist(b, c):  # el eje largo va de a→b
        a, b, c = b, c, caja[3]
    largo = (b[0] - a[0], b[1] - a[1])
    ancho = (c[0] - b[0], c[1] - b[1])
    posiciones = []
    for i in range(n):
        t = (i + 0.5) / n
        p = Point(a[0] + largo[0] * t + ancho[0] / 2, a[1] + largo[1] * t + ancho[1] / 2)
        if not poligono.contains(p):
            # Ambiente en L: el punto de la franja que sí cae dentro.
            franja = LineString(
                [
                    (a[0] + largo[0] * t, a[1] + largo[1] * t),
                    (a[0] + largo[0] * t + ancho[0], a[1] + largo[1] * t + ancho[1]),
                ]
            ).intersection(poligono)
            p = franja.centroid if not franja.is_empty else poligono.representative_point()
        posiciones.append((p.x, p.y))
    return posiciones


def _reticula(poligono: Polygon, n: int) -> list[Coord]:
    """Cuadrícula de unas `n` luminarias alineada con el rectángulo del ambiente."""
    rectangulo = poligono.minimum_rotated_rectangle
    if not isinstance(rectangulo, Polygon):
        punto = poligono.representative_point()
        return [(punto.x, punto.y)]
    caja = list(rectangulo.exterior.coords)[:4]
    a, b, c = caja[0], caja[1], caja[2]
    if math.dist(a, b) < math.dist(b, c):
        a, b, c = b, c, caja[3]
    largo, ancho = math.dist(a, b), math.dist(b, c)
    columnas = max(1, round(math.sqrt(n * largo / max(ancho, 0.01))))
    filas = max(1, math.ceil(n / columnas))
    posiciones = []
    for j in range(filas):
        for i in range(columnas):
            t, u = (i + 0.5) / columnas, (j + 0.5) / filas
            p = Point(
                a[0] + (b[0] - a[0]) * t + (c[0] - b[0]) * u,
                a[1] + (b[1] - a[1]) * t + (c[1] - b[1]) * u,
            )
            if poligono.contains(p):
                posiciones.append((p.x, p.y))
    if not posiciones:
        punto = poligono.representative_point()
        posiciones.append((punto.x, punto.y))
    return posiciones


def _ideales_extremos(recinto: _Recinto, cantidad: int) -> list[float]:
    """Posiciones a 45 cm de cada extremo de las paredes sin puerta, la más larga primero."""
    anillo = recinto.poligono.exterior
    coords = list(anillo.coords)
    paredes = []
    s = 0.0
    for p, q in zip(coords, coords[1:], strict=False):
        largo = math.dist(p, q)
        tramo = LineString([p, q])
        if largo >= 1.2 and not any(tramo.distance(v) < 0.05 for v in recinto.vanos):
            paredes.append((-round(largo, 6), s, largo))
        s += largo
    ideales: list[float] = []
    for _, inicio, largo in sorted(paredes):
        ideales += [inicio + 0.45, inicio + largo - 0.45]
    return ideales[:cantidad]


def _en_pared(
    recinto: _Recinto,
    cantidad: int,
    ocupados: list[Coord],
    ideales: list[float] | None = None,
) -> list[Coord]:
    """`cantidad` puntos de pared lejos de vanos y entre sí.

    Sin `ideales` se reparten por el perímetro; con ellos, se buscan cerca de
    esas distancias recorridas, y lo que falte se completa por el perímetro.
    """
    candidatos = recinto.candidatos_de_pared()
    if not candidatos or cantidad <= 0:
        return []
    perimetro = recinto.poligono.exterior.length
    objetivos = list(ideales or [])[:cantidad]
    objetivos += [(i + 0.5) * perimetro / cantidad for i in range(len(objetivos), cantidad)]
    elegidos: list[Coord] = []
    for ideal in objetivos:
        libres = [
            (abs(s - ideal), s, p)
            for s, p in candidatos
            if all(math.dist(p, q) >= ENTRE_PUNTOS_M for q in elegidos + ocupados)
        ]
        if not libres:
            break
        elegidos.append(min(libres)[2])
    return elegidos


def _interruptor(recinto: _Recinto, distancia: float) -> Coord | None:
    """Junto a la primera puerta del ambiente, del lado del marco opuesto a la bisagra."""
    anillo = recinto.poligono.exterior
    for vano in recinto.vanos:
        (bx, by), (mx, my) = vano.coords[0], vano.coords[1]
        largo = math.dist((bx, by), (mx, my))
        ux, uy = (mx - bx) / largo, (my - by) / largo
        for origen, signo in (((mx, my), 1), ((bx, by), -1)):
            p = Point(origen[0] + signo * ux * distancia, origen[1] + signo * uy * distancia)
            if anillo.distance(p) <= 0.35:
                sobre = anillo.interpolate(anillo.project(p))
                return recinto.hacia_adentro(sobre)
    return None


def huella(plano: Plano, muro_m: float) -> Polygon:
    """Contorno exterior de la edificación: los ambientes unidos y engrosados por el muro."""
    poligonos = [
        Polygon([(float(p.x), float(p.y)) for p in a.poligono]).buffer(muro_m, join_style="mitre")
        for a in plano.ambientes
    ]
    union = unary_union(poligonos)
    partes = list(union.geoms) if isinstance(union, MultiPolygon) else [union]
    mayor = max(partes, key=lambda g: g.area)
    assert isinstance(mayor, Polygon)
    return Polygon(mayor.exterior)


def _hacia_afuera(huella_: Polygon, s: float) -> Coord:
    """Punto de la fachada a `s` metros recorridos, unos centímetros hacia afuera."""
    anillo = huella_.exterior
    p = anillo.interpolate(s % anillo.length)
    mejor: tuple[float, Coord] = (-1.0, (p.x, p.y))
    for angulo in range(0, 360, 45):
        a = math.radians(angulo)
        q = Point(p.x + DESDE_MURO_M * math.cos(a), p.y + DESDE_MURO_M * math.sin(a))
        if huella_.covers(q):
            continue
        separacion = round(huella_.distance(q), 6)
        if separacion > mejor[0]:
            mejor = (separacion, (q.x, q.y))
    return mejor[1]


def _repartir(grupos: list[list[str]], minimo: int, maximo: int) -> list[list[str]]:
    """Reparte los puntos, ambiente por ambiente, en circuitos de tamaño parecido.

    Respeta el mínimo de circuitos y el máximo de puntos por circuito. Cada
    corte se mueve al límite entre dos ambientes si queda a dos puntos o menos
    y no rompe el máximo; así un ambiente solo se parte cuando hace falta.
    """
    puntos = [p for grupo in grupos for p in grupo]
    total = len(puntos)
    if total == 0:
        return []
    k = min(max(minimo, math.ceil(total / maximo)), total)
    limites = set()
    acumulado = 0
    for grupo in grupos:
        acumulado += len(grupo)
        limites.add(acumulado)

    cortes = [0]
    for j in range(1, k):
        ideal = round(total * j / k)
        previo = cortes[-1]
        quedan = k - j
        validos = [
            c
            for c in range(ideal - 2, ideal + 3)
            if c in limites and 0 < c - previo <= maximo and quedan <= total - c <= quedan * maximo
        ]
        cortes.append(min(validos, key=lambda c: (abs(c - ideal), c)) if validos else ideal)
    cortes.append(total)
    return [puntos[a:b] for a, b in zip(cortes, cortes[1:], strict=False)]


def disenar(
    plano: Plano,
    cargas: tuple[CargaEspecial, ...],
    perfil: Perfil,
    preferencias: Preferencias | None = None,
) -> Diseno:
    """Coloca la instalación en los ambientes del plano y arma circuitos y recorridos.

    `cargas` son los equipos especiales que declaró el usuario; se conservan su
    tipo, potencia y conexión, y se les asigna ambiente y circuito.

    Si el plano ya trae ubicaciones o interruptores fijados por el usuario, el
    diseño los deja donde están; el resto se vuelve a colocar. Lo que no vuelve
    a generarse (un punto agregado a mano) se descarta con un aviso.

    `preferencias` son las del escenario: estilo de iluminación, zona
    climática, refrigeradora, exteriores y cambios por ambiente. Las cargas
    que el diseño propone (aire, refrigeradora) se regeneran siempre: las que
    llegan con origen "auto" se descartan.
    """
    preferencias = preferencias or Preferencias()
    cargas = tuple(c for c in cargas if c.origen != "auto")
    if not plano.ambientes:
        raise DatoInvalido("el plano no tiene ambientes; no hay dónde diseñar")
    avisos: list[str] = []
    fijas: dict[str, Ubicacion] = {u.id: u for u in plano.ubicaciones if u.fijo}
    fijos_s: dict[str, Interruptor] = {s.id: s for s in plano.interruptores if s.fijo}
    fijados: set[str] = set()
    par = perfil.parametro
    alt_interruptor = par("altura_interruptor_m")[0]
    alt_tablero = par("altura_tablero_m")[0]
    alt_techo = par("altura_techo_m")[0]
    dist_interruptor = float(par("distancia_interruptor_puerta_m")[0])
    max_il = int(par("puntos_max_iluminacion")[0])
    max_to = int(par("salidas_max_tomacorrientes")[0])
    min_il, min_to = perfil.circuitos_minimos(plano.area_construida_m2)[0]
    estilos = {e.id: e for e in perfil.estilos_iluminacion()}
    if estilos and preferencias.iluminacion not in estilos:
        raise DatoInvalido(f"el perfil no tiene el estilo {preferencias.iluminacion}")
    zona = (
        perfil.zona_climatica(preferencias.zona_climatica)[0]
        if preferencias.zona_climatica
        else None
    )

    recintos: list[_Recinto] = []
    for ambiente in plano.ambientes:
        poligono = Polygon([(float(p.x), float(p.y)) for p in ambiente.poligono])
        vanos = [
            LineString(
                [(float(d.bisagra.x), float(d.bisagra.y)), (float(d.extremo.x), float(d.extremo.y))]
            )
            for d in plano.puertas
            if ambiente.id in d.ambientes
        ]
        recintos.append(_Recinto(ambiente, poligono, perfil.plantilla(ambiente.uso)[0], vanos))

    posicion: dict[str, Coord] = {}
    altura: dict[str, Decimal] = {}
    de_ambiente: dict[str, str] = {}
    luces: dict[str, list[str]] = {}
    tomas: dict[str, list[str]] = {}
    interruptores: dict[str, Coord] = {}

    for recinto in recintos:
        aid = recinto.ambiente.id
        luces[aid], tomas[aid] = [], []
        propia = preferencias.ambientes.get(aid)
        estilo = estilos.get((propia.iluminacion if propia else None) or preferencias.iluminacion)
        if propia and propia.iluminacion and propia.iluminacion not in estilos:
            raise DatoInvalido(f"el perfil no tiene el estilo de iluminación {propia.iluminacion}")
        repartidas = (
            _luminarias(
                recinto, estilo.area_por_luminaria_m2, estilo.luminarias_min, estilo.distribucion
            )
            if estilo is not None
            else _luminarias(recinto)
        )
        for n, p in enumerate(repartidas, start=1):
            pid = f"L-{aid}-{n}"
            posicion[pid], altura[pid], de_ambiente[pid] = p, alt_techo, aid
            luces[aid].append(pid)
        plantilla = recinto.plantilla
        cantidad = max(
            plantilla.tomas_min, _techo(recinto.ambiente.perimetro_m / plantilla.separacion_tomas_m)
        )
        modo = (propia.tomas if propia else None) or plantilla.tomas_distribucion
        ideales = _ideales_extremos(recinto, cantidad) if modo == "extremos" else None
        ubicadas = _en_pared(recinto, cantidad, [], ideales)
        if len(ubicadas) < cantidad:
            avisos.append(
                f"{aid} {recinto.ambiente.nombre}: caben {len(ubicadas)} "
                f"de {cantidad} tomacorrientes"
            )
        for n, p in enumerate(ubicadas, start=1):
            pid = f"T-{aid}-{n}"
            posicion[pid], altura[pid], de_ambiente[pid] = p, plantilla.altura_tomas_m, aid
            tomas[aid].append(pid)
        if luces[aid]:
            lugar = _interruptor(recinto, dist_interruptor)
            if lugar is None:
                avisos.append(
                    f"{aid} {recinto.ambiente.nombre}: sin puerta donde ubicar el interruptor"
                )
            else:
                interruptores[aid] = lugar

    # Cargas especiales: cada una en un ambiente que admita ese equipo.
    nuevas_cargas: list[tuple[CargaEspecial, str]] = []
    ocupados: dict[str, list[Coord]] = {
        r.ambiente.id: [posicion[t] for t in tomas[r.ambiente.id]] for r in recintos
    }
    usados: set[tuple[str, str]] = set()
    for n, carga in enumerate(cargas, start=1):
        admiten = [r for r in recintos if carga.tipo in r.plantilla.equipos]
        libres = [r for r in admiten if (r.ambiente.id, carga.tipo) not in usados]
        posibles = libres or admiten
        if posibles:
            destino = posibles[0]
        else:
            destino = recintos[0]
            avisos.append(
                f"{carga.tipo}: ningún ambiente lo admite; se ubicó en {destino.ambiente.id}"
            )
        aid = destino.ambiente.id
        usados.add((aid, carga.tipo))
        sitios = _en_pared(destino, 1, ocupados[aid])
        p = sitios[0] if sitios else _interior(destino.poligono)
        ocupados[aid].append(p)
        cid = f"E-{aid}-{n}"
        posicion[cid], altura[cid], de_ambiente[cid] = p, destino.plantilla.altura_tomas_m, aid
        nuevas_cargas.append((carga, cid))

    # Cargas que propone el diseño: aire acondicionado por zona y refrigeradora.
    for recinto in recintos:
        aid = recinto.ambiente.id
        propia = preferencias.ambientes.get(aid)
        quiere = propia.aire if propia and propia.aire is not None else None
        if quiere is None:
            quiere = bool(zona and zona.aire and recinto.plantilla.aire)
        if not quiere:
            continue
        por_m2 = zona.btu_por_m2 if zona else Decimal(600)
        requerido = recinto.ambiente.area_m2 * por_m2
        try:
            equipo = perfil.aire_para(requerido)[0]
            exceso = ""
        except FilaNoEncontrada:
            equipo = perfil.aires()[-1]
            exceso = " (no alcanza: considere dos equipos)"
        base = perfil.carga("aire_acondicionado")[0]
        alt_aire = par("altura_aire_m")[0]
        sitios = _en_pared(recinto, 1, ocupados[aid])
        p = sitios[0] if sitios else _interior(recinto.poligono)
        ocupados[aid].append(p)
        cid = f"E-{aid}-AA"
        posicion[cid], altura[cid], de_ambiente[cid] = p, alt_aire, aid
        nota = (
            f"{equipo.btu} BTU para {recinto.ambiente.area_m2} m² × {por_m2} BTU/m²"
            f"{' (' + zona.nombre + ')' if zona else ''}{exceso}"
        )
        if exceso:
            avisos.append(f"{aid} {recinto.ambiente.nombre}: aire de {requerido} BTU{exceso}")
        nuevas_cargas.append(
            (
                CargaEspecial(
                    id=cid,
                    tipo="aire_acondicionado",
                    circuito="-",
                    potencia_w=max(equipo.potencia, base.potencia),
                    conexion=equipo.conexion,
                    origen="auto",
                    nota=nota,
                ),
                cid,
            )
        )
    if preferencias.refrigeradora:
        cocina = next((r for r in recintos if r.plantilla.refrigeradora), None)
        if cocina is not None:
            aid = cocina.ambiente.id
            sitios = _en_pared(cocina, 1, ocupados[aid])
            p = sitios[0] if sitios else _interior(cocina.poligono)
            ocupados[aid].append(p)
            cid = f"E-{aid}-REF"
            posicion[cid], altura[cid], de_ambiente[cid] = p, cocina.plantilla.altura_tomas_m, aid
            nuevas_cargas.append(
                (
                    CargaEspecial(
                        id=cid,
                        tipo="refrigeradora",
                        circuito="-",
                        origen="auto",
                        nota="Tomacorriente dedicado",
                    ),
                    cid,
                )
            )

    # Exteriores: luz y toma junto a cada puerta que da afuera, y luces por la fachada.
    luces_ext: list[str] = []
    tomas_ext: list[str] = []
    centro_interior = list(posicion.values())
    if preferencias.exteriores:
        muro = float(par("muro_exterior_m")[0])
        contorno = huella(plano, muro)
        anillo = contorno.exterior
        separacion = float(par("separacion_luces_exteriores_m")[0])
        alt_luz_ext = par("altura_luz_exterior_m")[0]
        alt_toma_ext = par("altura_toma_exterior_m")[0]
        puertas_ext = [d for d in plano.puertas if len(d.ambientes) == 1]
        en_fachada: list[float] = []
        for d in puertas_ext:
            medio = Point(
                (float(d.bisagra.x) + float(d.extremo.x)) / 2,
                (float(d.bisagra.y) + float(d.extremo.y)) / 2,
            )
            if anillo.distance(medio) > muro + 0.3:
                continue  # puerta a un patio interior o mal leída
            s0 = anillo.project(medio)
            en_fachada.append(s0 + 0.75)
            n = len(tomas_ext) + 1
            tid = f"T-{EXTERIOR}-{n}"
            posicion[tid] = _hacia_afuera(contorno, s0 - 1.0)
            altura[tid], de_ambiente[tid] = alt_toma_ext, EXTERIOR
            tomas_ext.append(tid)
        largo = anillo.length
        k = 0.0
        while k < largo:
            cerca = [abs(k - x) % largo for x in en_fachada]
            if all(min(c, largo - c) >= separacion / 2 for c in cerca):
                en_fachada.append(k)
            k += separacion
        for n, s_ in enumerate(sorted(x % largo for x in en_fachada), start=1):
            lid = f"L-{EXTERIOR}-{n}"
            posicion[lid] = _hacia_afuera(contorno, s_)
            altura[lid], de_ambiente[lid] = alt_luz_ext, EXTERIOR
            luces_ext.append(lid)
        # Interruptor de exteriores: dentro, junto a la primera puerta que da afuera.
        for d in puertas_ext:
            dentro = next((r for r in recintos if r.ambiente.id == d.ambientes[0]), None)
            if dentro is None:
                continue
            vano = LineString(
                [(float(d.bisagra.x), float(d.bisagra.y)), (float(d.extremo.x), float(d.extremo.y))]
            )
            solo = _Recinto(dentro.ambiente, dentro.poligono, dentro.plantilla, [vano])
            lugar = _interruptor(solo, dist_interruptor + 0.25)
            if lugar is not None:
                interruptores[EXTERIOR] = lugar
                break
        if luces_ext and EXTERIOR not in interruptores:
            avisos.append("sin puerta exterior donde ubicar el interruptor de las luces de fachada")

    # Lo que el usuario fijó se queda donde lo dejó.
    for pid, u in fijas.items():
        if pid in posicion and u.ambiente:
            posicion[pid] = (float(u.x), float(u.y))
            altura[pid], de_ambiente[pid] = u.altura_m, u.ambiente
            fijados.add(pid)
    for aid in list(interruptores):
        s = fijos_s.get(f"S-{aid}")
        if s is not None:
            interruptores[aid] = (float(s.x), float(s.y))
            fijados.add(s.id)

    # Tablero: en el ambiente de mayor preferencia, en la pared más cercana a las cargas.
    con_tablero = sorted(
        (r for r in recintos if r.plantilla.prioridad_tablero is not None),
        key=lambda r: (r.plantilla.prioridad_tablero or 0, r.ambiente.id),
    )
    if con_tablero:
        casa = con_tablero[0]
    else:
        casa = recintos[0]
        avisos.append(f"ningún ambiente admite el tablero; se ubicó en {casa.ambiente.id}")
    cx = sum(p[0] for p in centro_interior) / len(centro_interior)
    cy = sum(p[1] for p in centro_interior) / len(centro_interior)
    paredes = [
        (round(math.dist(p, (cx, cy)), 6), s, p)
        for s, p in casa.candidatos_de_pared()
        if all(math.dist(p, q) >= ENTRE_PUNTOS_M for q in ocupados[casa.ambiente.id])
    ]
    tablero: Coord = min(paredes)[2] if paredes else _interior(casa.poligono)
    tablero_ambiente = casa.ambiente.id
    if "TD-1" in fijas and fijas["TD-1"].ambiente:
        tablero = (float(fijas["TD-1"].x), float(fijas["TD-1"].y))
        tablero_ambiente = fijas["TD-1"].ambiente
        alt_tablero = fijas["TD-1"].altura_m
        fijados.add("TD-1")
    perdidos = sorted((set(fijas) | set(fijos_s)) - fijados)
    if perdidos:
        avisos.append(
            "se descartaron elementos fijados que el nuevo diseño no genera: " + ", ".join(perdidos)
        )

    # Circuitos: los ambientes se recorren en orden angular alrededor del tablero.
    def angulo(r: _Recinto) -> tuple[float, str]:
        c = r.poligono.centroid
        return (round(math.atan2(c.y - tablero[1], c.x - tablero[0]), 6), r.ambiente.id)

    en_orden = sorted(recintos, key=angulo)
    circuitos: list[Circuito] = []
    miembros: dict[str, list[str]] = {}
    puntos: list[Punto] = []

    def agregar(tipo: TipoCircuito, ids: list[str], tipo_punto: str | None) -> str:
        cid = f"C{len(circuitos) + 1}"
        # La longitud y la zona húmeda las pone el trazado.
        circuitos.append(Circuito(id=cid, tipo=tipo, longitud_m=Decimal("0.01")))
        miembros[cid] = ids
        if tipo_punto:
            puntos.extend(
                Punto(id=i, tipo=tipo_punto, circuito=cid, ambiente=de_ambiente[i], origen="auto")
                for i in ids
            )
        return cid

    for grupo in _repartir([luces[r.ambiente.id] for r in en_orden], min_il, max_il):
        agregar("iluminacion", grupo, "punto_luz")
    for grupo in _repartir([luces_ext], 1, max_il):
        agregar("iluminacion", grupo, "punto_luz")
    for grupo in _repartir([tomas[r.ambiente.id] for r in en_orden], min_to, max_to):
        agregar("tomacorrientes", grupo, "tomacorriente")
    for grupo in _repartir([tomas_ext], 1, max_to):
        agregar("tomacorrientes", grupo, "tomacorriente")
    cargas_finales = []
    for carga, cid_punto in nuevas_cargas:
        circuito = agregar("especial", [cid_punto], None)
        cargas_finales.append(
            CargaEspecial(
                id=cid_punto,
                tipo=carga.tipo,
                circuito=circuito,
                potencia_w=carga.potencia_w,
                conexion=carga.conexion,
                origen=carga.origen,
                nota=carga.nota,
            )
        )

    # Se traza con las mismas coordenadas, al milímetro, que se guardan; así
    # volver a trazar lo guardado da exactamente lo mismo.
    def al_mm(c: Coord) -> Coord:
        return (float(mm(c[0])), float(mm(c[1])))

    posicion = {i: al_mm(c) for i, c in posicion.items()}
    tablero = al_mm(tablero)
    interruptores = {aid: al_mm(c) for aid, c in interruptores.items()}
    red = trazar_red(
        circuitos,
        miembros,
        posicion,
        altura,
        de_ambiente,
        {r.ambiente.id: r.plantilla.zona_humeda for r in recintos} | {EXTERIOR: True},
        tablero,
        alt_tablero,
        alt_techo,
        {
            aid: Interruptor(
                id=f"S-{aid}",
                x=mm(x),
                y=mm(y),
                altura_m=alt_interruptor,
                ambiente=aid,
                circuito="",
                fijo=f"S-{aid}" in fijados,
            )
            for aid, (x, y) in interruptores.items()
        },
    )

    ubicaciones = [
        Ubicacion(
            id=i,
            x=mm(p[0]),
            y=mm(p[1]),
            altura_m=altura[i],
            ambiente=de_ambiente[i],
            fijo=i in fijados,
        )
        for i, p in posicion.items()
    ]
    ubicaciones.append(
        Ubicacion(
            id="TD-1",
            x=mm(tablero[0]),
            y=mm(tablero[1]),
            altura_m=alt_tablero,
            ambiente=tablero_ambiente,
            fijo="TD-1" in fijados,
        )
    )
    return Diseno(
        puntos=tuple(puntos),
        cargas_especiales=tuple(cargas_finales),
        circuitos=red.circuitos,
        plano=plano.model_copy(
            update={
                "ubicaciones": tuple(ubicaciones),
                "interruptores": red.interruptores,
                "recorridos": red.recorridos,
            }
        ),
        avisos=tuple(avisos),
    )
