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

from shapely.geometry import LineString, Point, Polygon

from electric.errores import DatoInvalido
from electric.modelo.entidades import CargaEspecial, Circuito, Punto, TipoCircuito
from electric.modelo.plano import (
    Ambiente,
    Interruptor,
    Plano,
    Pt,
    Recorrido,
    Ubicacion,
    cm,
    mm,
)
from electric.perfiles.carga import Perfil
from electric.perfiles.esquema import FilaPlantilla

Coord = tuple[float, float]

#: Separación del punto respecto de la cara del muro, hacia el ambiente.
DESDE_MURO_M = 0.05
#: Distancias mínimas de un punto de pared a un vano y a una esquina.
LIBRE_DE_PUERTA_M = 0.40
LIBRE_DE_ESQUINA_M = 0.30
ENTRE_PUNTOS_M = 0.80
PASO_M = 0.10


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


def _luminarias(recinto: _Recinto) -> list[Coord]:
    """Luminarias repartidas a lo largo del lado mayor del ambiente."""
    plantilla = recinto.plantilla
    n = max(
        plantilla.luminarias_min, _techo(recinto.ambiente.area_m2 / plantilla.area_por_luminaria_m2)
    )
    if n <= 0:
        return []
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


def _en_pared(recinto: _Recinto, cantidad: int, ocupados: list[Coord]) -> list[Coord]:
    """`cantidad` puntos de pared repartidos por el perímetro, lejos de vanos y entre sí."""
    candidatos = recinto.candidatos_de_pared()
    if not candidatos or cantidad <= 0:
        return []
    perimetro = recinto.poligono.exterior.length
    elegidos: list[Coord] = []
    for i in range(cantidad):
        ideal = (i + 0.5) * perimetro / cantidad
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


def _ortogonal(a: Coord, b: Coord) -> list[Coord]:
    """Tramo en L: primero horizontal, luego vertical."""
    if abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9:
        return [a, b]
    return [a, (b[0], a[1]), b]


def _manhattan(a: Coord, b: Coord) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _cadena(origen: Coord, puntos: list[tuple[str, Coord]]) -> list[tuple[str, Coord]]:
    """Orden de visita: siempre el punto más cercano al último visitado."""
    pendientes = list(puntos)
    orden: list[tuple[str, Coord]] = []
    actual = origen
    while pendientes:
        siguiente = min(pendientes, key=lambda p: (round(_manhattan(actual, p[1]), 6), p[0]))
        pendientes.remove(siguiente)
        orden.append(siguiente)
        actual = siguiente[1]
    return orden


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


def disenar(plano: Plano, cargas: tuple[CargaEspecial, ...], perfil: Perfil) -> Diseno:
    """Coloca la instalación en los ambientes del plano y arma circuitos y recorridos.

    `cargas` son los equipos especiales que declaró el usuario; se conservan su
    tipo, potencia y conexión, y se les asigna ambiente y circuito.
    """
    if not plano.ambientes:
        raise DatoInvalido("el plano no tiene ambientes; no hay dónde diseñar")
    avisos: list[str] = []
    par = perfil.parametro
    alt_interruptor = par("altura_interruptor_m")[0]
    alt_tablero = par("altura_tablero_m")[0]
    alt_techo = par("altura_techo_m")[0]
    dist_interruptor = float(par("distancia_interruptor_puerta_m")[0])
    max_il = int(par("puntos_max_iluminacion")[0])
    max_to = int(par("salidas_max_tomacorrientes")[0])
    min_il, min_to = perfil.circuitos_minimos(plano.area_construida_m2)[0]

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
        for n, p in enumerate(_luminarias(recinto), start=1):
            pid = f"L-{aid}-{n}"
            posicion[pid], altura[pid], de_ambiente[pid] = p, alt_techo, aid
            luces[aid].append(pid)
        plantilla = recinto.plantilla
        cantidad = max(
            plantilla.tomas_min, _techo(recinto.ambiente.perimetro_m / plantilla.separacion_tomas_m)
        )
        ubicadas = _en_pared(recinto, cantidad, [])
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
    cx = sum(p[0] for p in posicion.values()) / len(posicion)
    cy = sum(p[1] for p in posicion.values()) / len(posicion)
    paredes = [
        (round(math.dist(p, (cx, cy)), 6), s, p)
        for s, p in casa.candidatos_de_pared()
        if all(math.dist(p, q) >= ENTRE_PUNTOS_M for q in ocupados[casa.ambiente.id])
    ]
    tablero: Coord = min(paredes)[2] if paredes else _interior(casa.poligono)

    # Circuitos: los ambientes se recorren en orden angular alrededor del tablero.
    def angulo(r: _Recinto) -> tuple[float, str]:
        c = r.poligono.centroid
        return (round(math.atan2(c.y - tablero[1], c.x - tablero[0]), 6), r.ambiente.id)

    en_orden = sorted(recintos, key=angulo)
    circuitos: list[Circuito] = []
    puntos: list[Punto] = []
    recorridos: list[Recorrido] = []
    salida_interruptores: list[Interruptor] = []
    humedo = {r.ambiente.id: r.plantilla.zona_humeda for r in recintos}
    bajada_tablero = float(alt_techo - alt_tablero)

    def trazar(ids: list[str]) -> tuple[list[Coord], float, float]:
        """Traza, longitud física y longitud equivalente por momento de carga."""
        orden = _cadena(tablero, [(i, posicion[i]) for i in ids])
        traza: list[Coord] = [tablero]
        acumulado = 0.0
        distancias = []
        for i, p in orden:
            acumulado += _manhattan(traza[-1], p)
            traza.extend(_ortogonal(traza[-1], p)[1:])
            distancias.append(bajada_tablero + acumulado + float(alt_techo - altura[i]))
        bajadas = sum(float(alt_techo - altura[i]) for i, _ in orden)
        return traza, bajada_tablero + acumulado + bajadas, sum(distancias) / len(distancias)

    def agregar(tipo: TipoCircuito, ids: list[str], tipo_punto: str | None) -> str:
        cid = f"C{len(circuitos) + 1}"
        traza, largo, equivalente = trazar(ids)
        derivaciones = []
        if tipo == "iluminacion":
            for aid in dict.fromkeys(de_ambiente[i] for i in ids):
                if aid not in interruptores:
                    continue
                propias = [i for i in ids if de_ambiente[i] == aid]
                cercana = min(
                    propias, key=lambda i: (_manhattan(posicion[i], interruptores[aid]), i)
                )
                derivaciones.append((posicion[cercana], interruptores[aid]))
                if not any(s.ambiente == aid for s in salida_interruptores):
                    x, y = interruptores[aid]
                    salida_interruptores.append(
                        Interruptor(
                            id=f"S-{aid}",
                            x=mm(x),
                            y=mm(y),
                            altura_m=alt_interruptor,
                            ambiente=aid,
                            circuito=cid,
                        )
                    )
        circuitos.append(
            Circuito(
                id=cid,
                tipo=tipo,
                longitud_m=cm(max(equivalente, 0.01)),
                zona_humeda=tipo != "iluminacion" and any(humedo[de_ambiente[i]] for i in ids),
            )
        )
        recorridos.append(
            Recorrido(
                circuito=cid,
                puntos=tuple(Pt(x=mm(x), y=mm(y)) for x, y in traza),
                derivaciones=tuple(
                    (Pt(x=mm(a[0]), y=mm(a[1])), Pt(x=mm(b[0]), y=mm(b[1])))
                    for a, b in derivaciones
                ),
                longitud_m=cm(largo),
            )
        )
        if tipo_punto:
            puntos.extend(
                Punto(id=i, tipo=tipo_punto, circuito=cid, ambiente=de_ambiente[i], origen="auto")
                for i in ids
            )
        return cid

    for grupo in _repartir([luces[r.ambiente.id] for r in en_orden], min_il, max_il):
        agregar("iluminacion", grupo, "punto_luz")
    for grupo in _repartir([tomas[r.ambiente.id] for r in en_orden], min_to, max_to):
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
            )
        )

    ubicaciones = [
        Ubicacion(id=i, x=mm(p[0]), y=mm(p[1]), altura_m=altura[i], ambiente=de_ambiente[i])
        for i, p in posicion.items()
    ]
    ubicaciones.append(
        Ubicacion(
            id="TD-1",
            x=mm(tablero[0]),
            y=mm(tablero[1]),
            altura_m=alt_tablero,
            ambiente=casa.ambiente.id,
        )
    )
    return Diseno(
        puntos=tuple(puntos),
        cargas_especiales=tuple(cargas_finales),
        circuitos=tuple(circuitos),
        plano=plano.model_copy(
            update={
                "ubicaciones": tuple(ubicaciones),
                "interruptores": tuple(salida_interruptores),
                "recorridos": tuple(recorridos),
            }
        ),
        avisos=tuple(avisos),
    )
