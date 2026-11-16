"""Edición manual sobre el modelo de prueba: mover, fijar, cambiar de circuito, agregar y quitar."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from electric.calculo import calcular
from electric.diseno import (
    Agregar,
    CambiarCircuito,
    Liberar,
    Mover,
    Quitar,
    disenar,
    editar,
    retrazar,
)
from electric.diseno.edicion import posicion_de
from electric.errores import DatoInvalido
from electric.flujo import Resultado, proyecto_desde_plano
from electric.modelo import Proyecto, hash_canonico
from electric.perfiles import Perfil

from .conftest import EJEMPLOS

PLANTA = EJEMPLOS / "vivienda-plano" / "planta.dxf"


@pytest.fixture(scope="module")
def resultado(perfil_cnel: Perfil) -> Resultado:
    return proyecto_desde_plano(
        PLANTA.read_bytes(),
        "planta.dxf",
        perfil_cnel,
        id="vivienda-plano",
        nombre="Vivienda de prueba con plano",
        equipos=("ducha", "cocina"),
        alimentador_m=D(12),
    )


@pytest.fixture(scope="module")
def proyecto(resultado: Resultado) -> Proyecto:
    return resultado.proyecto


def _ambiente(proyecto: Proyecto, nombre: str) -> str:
    assert proyecto.plano is not None
    return next(a.id for a in proyecto.plano.ambientes if a.nombre == nombre)


def _ubicacion(proyecto: Proyecto, id: str):  # type: ignore[no-untyped-def]
    assert proyecto.plano is not None
    return next(u for u in proyecto.plano.ubicaciones if u.id == id)


def _recorrido(proyecto: Proyecto, circuito: str):  # type: ignore[no-untyped-def]
    assert proyecto.plano is not None
    return next(r for r in proyecto.plano.recorridos if r.circuito == circuito)


def _circuito(proyecto: Proyecto, id: str):  # type: ignore[no-untyped-def]
    return next(c for c in proyecto.circuitos if c.id == id)


def _luz_de(proyecto: Proyecto, nombre: str) -> str:
    aid = _ambiente(proyecto, nombre)
    return next(p.id for p in proyecto.puntos if p.ambiente == aid and p.tipo == "punto_luz")


def test_retrazar_el_diseno_automatico_no_cambia_nada(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    assert hash_canonico(retrazar(proyecto, perfil_cnel)) == hash_canonico(proyecto)


def test_mover_una_luminaria_la_fija_y_rehace_su_recorrido(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    luz = _luz_de(proyecto, "DORMITORIO 3")
    antes = _ubicacion(proyecto, luz)
    circuito = next(p.circuito for p in proyecto.puntos if p.id == luz)
    nuevo = (antes.x + D("0.6"), antes.y - D("0.4"))

    editado = editar(proyecto, [Mover(id=luz, x=nuevo[0], y=nuevo[1])], perfil_cnel).proyecto

    despues = _ubicacion(editado, luz)
    assert (despues.x, despues.y) == nuevo
    assert despues.fijo and despues.ambiente == antes.ambiente
    recorrido = _recorrido(editado, circuito)
    assert any((p.x, p.y) == nuevo for p in recorrido.puntos)
    assert recorrido != _recorrido(proyecto, circuito)
    assert _circuito(editado, circuito).longitud_m != _circuito(proyecto, circuito).longitud_m
    # Los demás circuitos no cambian.
    otros = [c.id for c in proyecto.circuitos if c.id != circuito]
    assert [_recorrido(editado, c) for c in otros] == [_recorrido(proyecto, c) for c in otros]
    assert calcular(editado, perfil_cnel).hash != calcular(proyecto, perfil_cnel).hash


def test_mover_un_punto_a_otro_ambiente_le_cambia_el_ambiente(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    toma = next(p.id for p in proyecto.puntos if p.tipo == "tomacorriente")
    sala = _ambiente(proyecto, "SALA - COMEDOR")
    assert proyecto.plano is not None
    ambiente = next(a for a in proyecto.plano.ambientes if a.id == sala)
    x = sum(p.x for p in ambiente.poligono) / len(ambiente.poligono)
    y = sum(p.y for p in ambiente.poligono) / len(ambiente.poligono)

    editado = editar(proyecto, [Mover(id=toma, x=x, y=y)], perfil_cnel).proyecto

    assert _ubicacion(editado, toma).ambiente == sala
    assert next(p for p in editado.puntos if p.id == toma).ambiente == sala


def test_no_se_puede_mover_fuera_de_los_ambientes(proyecto: Proyecto, perfil_cnel: Perfil) -> None:
    luz = _luz_de(proyecto, "COCINA")
    with pytest.raises(DatoInvalido, match="fuera del plano"):
        editar(proyecto, [Mover(id=luz, x=D(-50), y=D(-50))], perfil_cnel)
    with pytest.raises(DatoInvalido, match="no hay un elemento"):
        editar(proyecto, [Mover(id="X-9", x=D(1), y=D(1))], perfil_cnel)


def test_mover_el_tablero_rehace_todos_los_recorridos(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    tablero = _ubicacion(proyecto, "TD-1")
    nuevo = (tablero.x + D("1.5"), tablero.y)
    editado = editar(proyecto, [Mover(id="TD-1", x=nuevo[0], y=nuevo[1])], perfil_cnel).proyecto
    assert editado.plano is not None
    for recorrido in editado.plano.recorridos:
        assert (recorrido.puntos[0].x, recorrido.puntos[0].y) == nuevo


def test_el_interruptor_movido_sigue_mandando_su_ambiente(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    assert proyecto.plano is not None
    interruptor = proyecto.plano.interruptores[0]
    pasillo = _ambiente(proyecto, "PASILLO")
    ambiente_pasillo = next(a for a in proyecto.plano.ambientes if a.id == pasillo)
    x = sum(p.x for p in ambiente_pasillo.poligono) / len(ambiente_pasillo.poligono)
    y = sum(p.y for p in ambiente_pasillo.poligono) / len(ambiente_pasillo.poligono)

    editado = editar(proyecto, [Mover(id=interruptor.id, x=x, y=y)], perfil_cnel).proyecto

    assert editado.plano is not None
    movido = next(s for s in editado.plano.interruptores if s.id == interruptor.id)
    assert movido.ambiente == interruptor.ambiente and movido.fijo
    assert posicion_de(editado.plano, interruptor.id) == (float(mm2(D(x))), float(mm2(D(y))))
    derivacion = next(
        d
        for r in editado.plano.recorridos
        if r.circuito == movido.circuito
        for d in r.derivaciones
        if (d[1].x, d[1].y) == (movido.x, movido.y)
    )
    assert derivacion


def mm2(valor: D) -> D:
    return valor.quantize(D("0.001"))


def test_volver_a_disenar_conserva_lo_fijado_y_liberar_lo_suelta(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    luz = _luz_de(proyecto, "DORMITORIO 2")
    antes = _ubicacion(proyecto, luz)
    nuevo = (antes.x + D("0.5"), antes.y)
    editado = editar(proyecto, [Mover(id=luz, x=nuevo[0], y=nuevo[1])], perfil_cnel).proyecto
    assert editado.plano is not None

    rediseno = disenar(editado.plano, tuple(editado.cargas_especiales), perfil_cnel)
    fija = next(u for u in rediseno.plano.ubicaciones if u.id == luz)
    assert (fija.x, fija.y) == nuevo and fija.fijo
    assert not any("descartaron" in a for a in rediseno.avisos)

    suelto = editar(editado, [Liberar(id=luz)], perfil_cnel).proyecto
    assert suelto.plano is not None
    otra_vez = disenar(suelto.plano, tuple(suelto.cargas_especiales), perfil_cnel)
    vuelta = next(u for u in otra_vez.plano.ubicaciones if u.id == luz)
    assert (vuelta.x, vuelta.y) == (antes.x, antes.y) and not vuelta.fijo


def test_cambiar_de_circuito_respeta_el_tipo_y_borra_los_vacios(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    luces = [c.id for c in proyecto.circuitos if c.tipo == "iluminacion"]
    tomas = [c.id for c in proyecto.circuitos if c.tipo == "tomacorrientes"]
    luz = next(p for p in proyecto.puntos if p.circuito == luces[0])

    pasado = editar(proyecto, [CambiarCircuito(id=luz.id, circuito=luces[1])], perfil_cnel)
    assert next(p for p in pasado.proyecto.puntos if p.id == luz.id).circuito == luces[1]

    with pytest.raises(DatoInvalido, match="tomacorrientes"):
        editar(proyecto, [CambiarCircuito(id=luz.id, circuito=tomas[0])], perfil_cnel)
    with pytest.raises(DatoInvalido, match="cargas especiales"):
        especial = proyecto.cargas_especiales[0]
        editar(proyecto, [CambiarCircuito(id=especial.id, circuito=luces[0])], perfil_cnel)

    nuevo = editar(proyecto, [CambiarCircuito(id=luz.id, circuito="nuevo")], perfil_cnel)
    agregado = nuevo.proyecto.circuitos[-1]
    assert agregado.tipo == "iluminacion" and agregado.id == f"C{len(proyecto.circuitos) + 1}"
    assert [p.id for p in nuevo.proyecto.puntos if p.circuito == agregado.id] == [luz.id]

    todos = [p.id for p in proyecto.puntos if p.circuito == luces[0]]
    vaciado = editar(
        proyecto, [CambiarCircuito(id=i, circuito=luces[1]) for i in todos], perfil_cnel
    )
    assert luces[0] not in {c.id for c in vaciado.proyecto.circuitos}
    assert any(f"{luces[0]} quedó sin puntos" in a for a in vaciado.avisos)
    calcular(vaciado.proyecto, perfil_cnel)


def test_agregar_un_tomacorriente_lo_suma_al_circuito_del_ambiente(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    cocina = _ambiente(proyecto, "COCINA")
    toma = next(p for p in proyecto.puntos if p.ambiente == cocina and p.tipo == "tomacorriente")
    lugar = _ubicacion(proyecto, toma.id)

    editado = editar(
        proyecto,
        [Agregar(tipo="tomacorriente", x=lugar.x, y=lugar.y + D("0.5"))],
        perfil_cnel,
    )

    nuevo = next(p for p in editado.proyecto.puntos if p.id == f"T-{cocina}-M1")
    assert nuevo.circuito == toma.circuito and nuevo.origen == "fijado"
    ubicado = _ubicacion(editado.proyecto, nuevo.id)
    assert ubicado.fijo and ubicado.altura_m == lugar.altura_m
    antes = calcular(proyecto, perfil_cnel).res("RC-01", toma.circuito).valor
    despues = calcular(editado.proyecto, perfil_cnel).res("RC-01", toma.circuito).valor
    assert isinstance(antes, D) and isinstance(despues, D) and despues > antes


def test_superar_el_maximo_de_puntos_avisa(proyecto: Proyecto, perfil_cnel: Perfil) -> None:
    maximo = int(perfil_cnel.parametro("puntos_max_iluminacion")[0])
    sala = _ambiente(proyecto, "SALA - COMEDOR")
    luz = _ubicacion(proyecto, _luz_de(proyecto, "SALA - COMEDOR"))
    circuito = next(
        p.circuito for p in proyecto.puntos if p.ambiente == sala and p.tipo == "punto_luz"
    )
    actuales = sum(1 for p in proyecto.puntos if p.circuito == circuito)
    agregar = [
        Agregar(tipo="punto_luz", x=luz.x + D("0.1") * k, y=luz.y, circuito=circuito)
        for k in range(1, maximo - actuales + 2)
    ]
    editado = editar(proyecto, agregar, perfil_cnel)
    assert any(f"{circuito} tiene {maximo + 1} puntos" in a for a in editado.avisos)


def test_quitar_las_luces_de_un_ambiente_quita_su_interruptor(
    proyecto: Proyecto, perfil_cnel: Perfil
) -> None:
    lavanderia = _ambiente(proyecto, "LAVANDERÍA")
    luces = [p.id for p in proyecto.puntos if p.ambiente == lavanderia and p.tipo == "punto_luz"]
    editado = editar(proyecto, [Quitar(id=i) for i in luces], perfil_cnel).proyecto
    assert editado.plano is not None
    assert not any(s.ambiente == lavanderia for s in editado.plano.interruptores)
    assert not any(u.id in luces for u in editado.plano.ubicaciones)
    with pytest.raises(DatoInvalido, match="tablero no se puede quitar"):
        editar(proyecto, [Quitar(id="TD-1")], perfil_cnel)


def test_sin_diseno_no_se_puede_editar(proyecto: Proyecto, perfil_cnel: Perfil) -> None:
    assert proyecto.plano is not None
    vacio = proyecto.model_copy(
        update={"plano": proyecto.plano.model_copy(update={"ubicaciones": ()})}
    )
    with pytest.raises(DatoInvalido, match="diseñe"):
        editar(vacio, [Liberar(id="TD-1")], perfil_cnel)
