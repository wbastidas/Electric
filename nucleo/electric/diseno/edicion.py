"""Edición manual de la instalación sobre el plano (RF-19).

Cada operación cambia la posición, el circuito o la existencia de un elemento;
después se vuelven a trazar todos los recorridos y longitudes con el mismo
criterio del diseño automático, para que el cálculo siempre parta de la red
que se ve. Lo que el usuario mueve o agrega queda fijado: volver a diseñar no
lo mueve.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import Point, Polygon

from electric.diseno.automatico import EXTERIOR, huella
from electric.diseno.trazado import Coord, trazar_red
from electric.errores import DatoInvalido
from electric.modelo.entidades import Circuito, Proyecto, Punto
from electric.modelo.plano import Plano, Ubicacion, mm
from electric.perfiles.carga import Perfil

TIPOS_AGREGABLES = {"punto_luz": ("L", "iluminacion"), "tomacorriente": ("T", "tomacorrientes")}


class _Op(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Mover(_Op):
    """Lleva un punto, carga especial, interruptor o el tablero a otra posición y lo fija."""

    op: Literal["mover"] = "mover"
    id: str
    x: Decimal
    y: Decimal


class Liberar(_Op):
    """Quita la fijación: el próximo diseño automático puede volver a ubicarlo."""

    op: Literal["liberar"] = "liberar"
    id: str


class CambiarCircuito(_Op):
    """Pasa un punto a otro circuito del mismo tipo, o a uno nuevo con `circuito="nuevo"`."""

    op: Literal["circuito"] = "circuito"
    id: str
    circuito: str


class Agregar(_Op):
    """Agrega una luminaria o un tomacorriente en una posición del plano."""

    op: Literal["agregar"] = "agregar"
    tipo: Literal["punto_luz", "tomacorriente"]
    x: Decimal
    y: Decimal
    #: Si falta, el circuito de ese tipo que ya pasa por el ambiente o el menos cargado.
    circuito: str | None = None


class Quitar(_Op):
    """Quita un punto (luminaria o tomacorriente) de la instalación."""

    op: Literal["quitar"] = "quitar"
    id: str


Edicion = Annotated[Mover | Liberar | CambiarCircuito | Agregar | Quitar, Field(discriminator="op")]


@dataclass(frozen=True)
class Editado:
    proyecto: Proyecto
    #: Consecuencias que el usuario debe ver: circuitos que se excedieron o quedaron vacíos…
    avisos: tuple[str, ...]


#: Hasta dónde fuera de la fachada se admite un punto exterior.
ALCANCE_EXTERIOR_M = 15


def _ambiente_en(plano: Plano, x: Decimal, y: Decimal, perfil: Perfil) -> str:
    punto = Point(float(x), float(y))
    for ambiente in plano.ambientes:
        if Polygon([(float(p.x), float(p.y)) for p in ambiente.poligono]).covers(punto):
            return ambiente.id
    contorno = huella(plano, float(perfil.parametro("muro_exterior_m")[0]))
    if contorno.covers(punto):
        raise DatoInvalido(f"la posición ({x}; {y}) cae sobre un muro")
    if contorno.distance(punto) <= ALCANCE_EXTERIOR_M:
        return EXTERIOR
    raise DatoInvalido(f"la posición ({x}; {y}) está fuera del plano")


def _siguiente_circuito(circuitos: Sequence[Circuito]) -> str:
    usados = {c.id for c in circuitos}
    n = len(circuitos) + 1
    while f"C{n}" in usados:
        n += 1
    return f"C{n}"


def retrazar(proyecto: Proyecto, perfil: Perfil) -> Proyecto:
    """Vuelve a trazar recorridos y longitudes desde la posición actual de cada elemento."""
    plano = proyecto.plano
    if plano is None or not plano.ubicaciones:
        raise DatoInvalido("el proyecto no tiene una instalación ubicada en el plano")
    lugar = {u.id: u for u in plano.ubicaciones}
    tablero_id = proyecto.tablero.id if proyecto.tablero else "TD-1"
    if tablero_id not in lugar:
        raise DatoInvalido(f"el tablero {tablero_id} no está ubicado en el plano")
    tablero = lugar[tablero_id]

    miembros: dict[str, list[str]] = {}
    pares = [(p.id, p.circuito) for p in proyecto.puntos] + [
        (c.id, c.circuito) for c in proyecto.cargas_especiales
    ]
    for eid, circuito in pares:
        if eid not in lugar:
            raise DatoInvalido(f"{eid} no está ubicado en el plano")
        miembros.setdefault(circuito, []).append(eid)

    usos = {a.id: a.uso for a in plano.ambientes}
    luces = {p.ambiente for p in proyecto.puntos if p.tipo == "punto_luz"}
    red = trazar_red(
        proyecto.circuitos,
        miembros,
        {i: (float(u.x), float(u.y)) for i, u in lugar.items()},
        {i: u.altura_m for i, u in lugar.items()},
        {i: u.ambiente or "" for i, u in lugar.items()},
        {aid: perfil.plantilla(uso)[0].zona_humeda for aid, uso in usos.items()} | {EXTERIOR: True},
        (float(tablero.x), float(tablero.y)),
        tablero.altura_m,
        perfil.parametro("altura_techo_m")[0],
        {s.ambiente: s for s in plano.interruptores if s.ambiente in luces},
    )
    return proyecto.model_copy(
        update={
            "circuitos": red.circuitos,
            "plano": plano.model_copy(
                update={"interruptores": red.interruptores, "recorridos": red.recorridos}
            ),
        }
    )


def editar(proyecto: Proyecto, ediciones: Sequence[Edicion], perfil: Perfil) -> Editado:
    """Aplica las ediciones en orden, vuelve a trazar y revisa los límites por circuito."""
    plano = proyecto.plano
    if plano is None or not plano.ubicaciones:
        raise DatoInvalido("diseñe la instalación antes de editarla")
    ubicaciones = {u.id: u for u in plano.ubicaciones}
    interruptores = {s.id: s for s in plano.interruptores}
    puntos = {p.id: p for p in proyecto.puntos}
    especiales = {c.id: c for c in proyecto.cargas_especiales}
    circuitos = list(proyecto.circuitos)
    avisos: list[str] = []
    por_circuito = {c.id: c for c in circuitos}

    for edicion in ediciones:
        if isinstance(edicion, Mover):
            aid = _ambiente_en(plano, edicion.x, edicion.y, perfil)
            x, y = mm(edicion.x), mm(edicion.y)
            if edicion.id in ubicaciones:
                ubicaciones[edicion.id] = ubicaciones[edicion.id].model_copy(
                    update={"x": x, "y": y, "ambiente": aid, "fijo": True}
                )
                if edicion.id in puntos:
                    puntos[edicion.id] = puntos[edicion.id].model_copy(update={"ambiente": aid})
            elif edicion.id in interruptores:
                # Sigue mandando las luces de su ambiente aunque se monte en otro
                # (por ejemplo, en el pasillo junto a la puerta).
                interruptores[edicion.id] = interruptores[edicion.id].model_copy(
                    update={"x": x, "y": y, "fijo": True}
                )
            else:
                raise DatoInvalido(f"no hay un elemento {edicion.id} en el plano")
        elif isinstance(edicion, Liberar):
            if edicion.id in ubicaciones:
                ubicaciones[edicion.id] = ubicaciones[edicion.id].model_copy(update={"fijo": False})
            elif edicion.id in interruptores:
                interruptores[edicion.id] = interruptores[edicion.id].model_copy(
                    update={"fijo": False}
                )
            else:
                raise DatoInvalido(f"no hay un elemento {edicion.id} en el plano")
        elif isinstance(edicion, CambiarCircuito):
            punto = puntos.get(edicion.id)
            if punto is None:
                raise DatoInvalido(
                    f"{edicion.id} no es un punto; las cargas especiales tienen circuito propio"
                )
            tipo = por_circuito[punto.circuito].tipo
            destino = edicion.circuito
            if destino == "nuevo":
                destino = _siguiente_circuito(circuitos)
                nuevo = Circuito(id=destino, tipo=tipo, longitud_m=Decimal("0.01"))
                circuitos.append(nuevo)
                por_circuito[destino] = nuevo
            elif destino not in por_circuito:
                raise DatoInvalido(f"no existe el circuito {destino}")
            elif por_circuito[destino].tipo != tipo:
                raise DatoInvalido(
                    f"{edicion.id} es de un circuito de {tipo}; {destino} es de "
                    f"{por_circuito[destino].tipo}"
                )
            puntos[edicion.id] = punto.model_copy(update={"circuito": destino, "origen": "fijado"})
        elif isinstance(edicion, Agregar):
            prefijo, tipo_circuito = TIPOS_AGREGABLES[edicion.tipo]
            aid = _ambiente_en(plano, edicion.x, edicion.y, perfil)
            n = 1
            while f"{prefijo}-{aid}-M{n}" in ubicaciones:
                n += 1
            pid = f"{prefijo}-{aid}-M{n}"
            destino = edicion.circuito or ""
            if not destino:
                del_tipo = [c.id for c in circuitos if c.tipo == tipo_circuito]
                en_ambiente = [
                    p.circuito
                    for p in puntos.values()
                    if p.ambiente == aid and p.circuito in del_tipo
                ]
                if en_ambiente:
                    destino = max(sorted(set(en_ambiente)), key=en_ambiente.count)
                elif del_tipo:
                    cuenta = [p.circuito for p in puntos.values()]
                    destino = min(del_tipo, key=lambda c: (cuenta.count(c), c))
                else:
                    destino = _siguiente_circuito(circuitos)
                    nuevo = Circuito(id=destino, tipo=tipo_circuito, longitud_m=Decimal("0.01"))
                    circuitos.append(nuevo)
                    por_circuito[destino] = nuevo
            elif destino not in por_circuito or por_circuito[destino].tipo != tipo_circuito:
                raise DatoInvalido(f"{destino} no es un circuito de {tipo_circuito}")
            if aid == EXTERIOR:
                clave = (
                    "altura_luz_exterior_m"
                    if edicion.tipo == "punto_luz"
                    else ("altura_toma_exterior_m")
                )
                altura = perfil.parametro(clave)[0]
            elif edicion.tipo == "punto_luz":
                altura = perfil.parametro("altura_techo_m")[0]
            else:
                uso = next(a.uso for a in plano.ambientes if a.id == aid)
                altura = perfil.plantilla(uso)[0].altura_tomas_m
            ubicaciones[pid] = Ubicacion(
                id=pid, x=mm(edicion.x), y=mm(edicion.y), altura_m=altura, ambiente=aid, fijo=True
            )
            puntos[pid] = Punto(
                id=pid, tipo=edicion.tipo, circuito=destino, ambiente=aid, origen="fijado"
            )
            if edicion.tipo == "punto_luz" and not any(
                s.ambiente == aid for s in interruptores.values()
            ):
                avisos.append(f"{pid}: el ambiente {aid} no tiene interruptor; ubíquelo a mano")
        else:
            if edicion.id not in puntos:
                raise DatoInvalido(
                    f"{edicion.id} no es un punto; las cargas especiales se quitan en "
                    "«Equipos declarados» y el tablero no se puede quitar"
                )
            del puntos[edicion.id]
            del ubicaciones[edicion.id]

    # Circuitos de puntos que quedaron vacíos: desaparecen.
    con_puntos = {p.circuito for p in puntos.values()} | {c.circuito for c in especiales.values()}
    for c in list(circuitos):
        if c.id not in con_puntos and c.tipo in ("iluminacion", "tomacorrientes"):
            circuitos.remove(c)
            avisos.append(f"{c.id} quedó sin puntos y se eliminó")
    # Interruptores de ambientes que ya no tienen luminarias: sobran.
    con_luz = {p.ambiente for p in puntos.values() if p.tipo == "punto_luz"}
    for sid, s in list(interruptores.items()):
        if s.ambiente not in con_luz:
            del interruptores[sid]

    par = perfil.parametro
    limites = {
        "iluminacion": int(par("puntos_max_iluminacion")[0]),
        "tomacorrientes": int(par("salidas_max_tomacorrientes")[0]),
    }
    for c in circuitos:
        if c.tipo in limites:
            cantidad = sum(1 for p in puntos.values() if p.circuito == c.id)
            if cantidad > limites[c.tipo]:
                avisos.append(f"{c.id} tiene {cantidad} puntos; el máximo es {limites[c.tipo]}")

    editado = proyecto.model_copy(
        update={
            "puntos": tuple(puntos.values()),
            "circuitos": tuple(circuitos),
            "plano": plano.model_copy(
                update={
                    "ubicaciones": tuple(ubicaciones.values()),
                    "interruptores": tuple(interruptores.values()),
                }
            ),
        }
    )
    # Valida la coherencia del conjunto (circuitos referidos, ids únicos…).
    editado = Proyecto.model_validate(editado.model_dump())
    return Editado(proyecto=retrazar(editado, perfil), avisos=tuple(avisos))


def posicion_de(plano: Plano, id: str) -> Coord | None:
    """Posición actual de un elemento del plano, para la interfaz y las pruebas."""
    for u in plano.ubicaciones:
        if u.id == id:
            return (float(u.x), float(u.y))
    for s in plano.interruptores:
        if s.id == id:
            return (float(s.x), float(s.y))
    return None


__all__ = [
    "Agregar",
    "CambiarCircuito",
    "Edicion",
    "Editado",
    "Liberar",
    "Mover",
    "Quitar",
    "editar",
    "posicion_de",
    "retrazar",
]
