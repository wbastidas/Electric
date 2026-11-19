"""Urbanizaciones: sectores de transformación, red de BT y alumbrado público."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from electric.perfiles.carga import Perfil
from electric.urbanizacion import (
    CargaComunal,
    Manzana,
    Urbanizacion,
    calcular_urbanizacion,
    generar_plano_urbanizacion,
)


def _lotizacion(**cambios: object) -> Urbanizacion:
    datos: dict[str, object] = {
        "nombre": "Lotización",
        "manzanas": [Manzana(id="A", lotes=24), Manzana(id="B", lotes=24)],
    }
    datos.update(cambios)
    return Urbanizacion.model_validate(datos)


def test_lotes_y_calles(perfil_cnel: Perfil) -> None:
    c = calcular_urbanizacion(_lotizacion(), perfil_cnel)
    assert len(c.lotes) == 48
    # Calle 0: fila norte de A; calle 1: fila sur de A y norte de B; calle 2: sur de B.
    assert [k.lotes for k in c.calles] == [12, 24, 12]
    assert all(k.longitud_m == D(120) for k in c.calles)
    # Una luminaria cada 30 m desde los 15 m: 15, 45, 75, 105.
    assert all(len(k.luminarias) == 4 for k in c.calles)


def test_cada_sector_cabe_en_su_transformador(perfil_cnel: Perfil) -> None:
    c = calcular_urbanizacion(_lotizacion(), perfil_cnel)
    assert sum(len(s.lotes) for s in c.sectores) == 48
    for s in c.sectores:
        assert s.kva is not None and s.kva <= D(50)
        assert s.demanda_kva * D("1.2") <= s.kva
        assert sum(x.lotes for x in s.circuitos) == len(s.lotes)
        assert all(x.conductor is not None for x in s.circuitos)
    assert c.kva_instalados == sum((s.kva or D(0)) for s in c.sectores)
    # Demanda en MT con la coincidencia de todos los lotes juntos.
    assert c.demanda_kva < sum(s.demanda_kva for s in c.sectores)


def test_transformador_mas_pequeno_divide_la_calle(perfil_cnel: Perfil) -> None:
    grande = calcular_urbanizacion(_lotizacion(), perfil_cnel)
    chico = calcular_urbanizacion(_lotizacion(kva_max_transformador=D(25)), perfil_cnel)
    assert len(chico.sectores) > len(grande.sectores)
    assert all(s.kva is not None and s.kva <= D(25) for s in chico.sectores)


def test_cargas_comunales(perfil_cnel: Perfil) -> None:
    sin = calcular_urbanizacion(_lotizacion(), perfil_cnel)
    con = calcular_urbanizacion(
        _lotizacion(comunales=[CargaComunal(descripcion="Bombeo", kva=D(15), calle=2)]),
        perfil_cnel,
    )
    assert con.demanda_kva == sin.demanda_kva + D(15)
    assert sum(s.comunal_kva for s in con.sectores if s.calle == 2) == D(15)
    with pytest.raises(ValueError, match="calles"):
        _lotizacion(comunales=[CargaComunal(descripcion="X", kva=D(1), calle=9)])


def test_plano(perfil_cnel: Perfil) -> None:
    c = calcular_urbanizacion(_lotizacion(), perfil_cnel)
    dxf = generar_plano_urbanizacion(c)
    assert b"CUADRO DE TRANSFORMADORES" in dxf and b"E-AP" in dxf and b"T-1" in dxf
