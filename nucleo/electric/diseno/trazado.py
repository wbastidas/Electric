"""Recorridos de los circuitos desde el tablero y su longitud para la caída de tensión.

Lo usan el diseño automático y la edición manual: ambos parten de dónde está
cada punto y a qué circuito pertenece, y obtienen el mismo trazado.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from electric.modelo.entidades import Circuito
from electric.modelo.plano import Interruptor, Pt, Recorrido, cm, mm

Coord = tuple[float, float]


@dataclass(frozen=True)
class Red:
    circuitos: tuple[Circuito, ...]
    recorridos: tuple[Recorrido, ...]
    #: Solo los interruptores de ambientes con luminarias, con su circuito.
    interruptores: tuple[Interruptor, ...]


def manhattan(a: Coord, b: Coord) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def ortogonal(a: Coord, b: Coord) -> list[Coord]:
    """Tramo en L: primero horizontal, luego vertical."""
    if abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9:
        return [a, b]
    return [a, (b[0], a[1]), b]


def cadena(origen: Coord, puntos: Sequence[tuple[str, Coord]]) -> list[tuple[str, Coord]]:
    """Orden de visita: siempre el punto más cercano al último visitado."""
    pendientes = list(puntos)
    orden: list[tuple[str, Coord]] = []
    actual = origen
    while pendientes:
        siguiente = min(pendientes, key=lambda p: (round(manhattan(actual, p[1]), 6), p[0]))
        pendientes.remove(siguiente)
        orden.append(siguiente)
        actual = siguiente[1]
    return orden


def trazar_red(
    circuitos: Sequence[Circuito],
    miembros: Mapping[str, Sequence[str]],
    posicion: Mapping[str, Coord],
    altura: Mapping[str, Decimal],
    de_ambiente: Mapping[str, str],
    humedo: Mapping[str, bool],
    tablero: Coord,
    alt_tablero: Decimal,
    alt_techo: Decimal,
    interruptores: Mapping[str, Interruptor],
) -> Red:
    """Traza cada circuito y le pone su longitud equivalente y si va por zona húmeda.

    `miembros` da, por circuito, los puntos o la carga especial que alimenta.
    `interruptores` va por ambiente; cada uno se conecta al primer circuito de
    iluminación que pasa por su ambiente, desde la luminaria más cercana.
    Un circuito sin miembros se deja como está y sin recorrido.
    """
    bajada_tablero = float(alt_techo - alt_tablero)
    salida_circuitos: list[Circuito] = []
    recorridos: list[Recorrido] = []
    conectados: dict[str, Interruptor] = {}

    for circuito in circuitos:
        ids = list(miembros.get(circuito.id, ()))
        if not ids:
            salida_circuitos.append(circuito)
            continue
        orden = cadena(tablero, [(i, posicion[i]) for i in ids])
        traza: list[Coord] = [tablero]
        acumulado = 0.0
        distancias = []
        for i, p in orden:
            acumulado += manhattan(traza[-1], p)
            traza.extend(ortogonal(traza[-1], p)[1:])
            distancias.append(bajada_tablero + acumulado + float(alt_techo - altura[i]))
        bajadas = sum(float(alt_techo - altura[i]) for i, _ in orden)
        largo = bajada_tablero + acumulado + bajadas
        equivalente = sum(distancias) / len(distancias)

        derivaciones: list[tuple[Coord, Coord]] = []
        if circuito.tipo == "iluminacion":
            for aid in dict.fromkeys(de_ambiente[i] for i in ids):
                interruptor = interruptores.get(aid)
                if interruptor is None or aid in conectados:
                    continue
                destino = (float(interruptor.x), float(interruptor.y))
                propias = [i for i in ids if de_ambiente[i] == aid]
                cercana = min(propias, key=lambda i: (manhattan(posicion[i], destino), i))
                derivaciones.append((posicion[cercana], destino))
                conectados[aid] = interruptor.model_copy(update={"circuito": circuito.id})

        salida_circuitos.append(
            circuito.model_copy(
                update={
                    "longitud_m": cm(max(equivalente, 0.01)),
                    "zona_humeda": circuito.tipo != "iluminacion"
                    and any(humedo.get(de_ambiente[i], False) for i in ids),
                }
            )
        )
        recorridos.append(
            Recorrido(
                circuito=circuito.id,
                puntos=tuple(Pt(x=mm(x), y=mm(y)) for x, y in traza),
                derivaciones=tuple(
                    (Pt(x=mm(a[0]), y=mm(a[1])), Pt(x=mm(b[0]), y=mm(b[1])))
                    for a, b in derivaciones
                ),
                longitud_m=cm(largo),
            )
        )

    return Red(
        circuitos=tuple(salida_circuitos),
        recorridos=tuple(recorridos),
        interruptores=tuple(conectados.values()),
    )
