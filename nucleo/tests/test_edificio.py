"""Edificios de departamentos, locales y oficinas."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from electric.edificio import (
    CargaGeneral,
    Edificio,
    TipoUnidad,
    calcular_edificio,
    generar_unifilar_edificio,
)
from electric.edificio.calculo import id_unidad
from electric.errores import DatoInvalido
from electric.perfiles.carga import Perfil


def _torre(**cambios: object) -> Edificio:
    datos: dict[str, object] = {
        "nombre": "Torre",
        "unidades": [
            TipoUnidad(id="Tipo A", estrato="B", pisos=tuple(range(1, 9)), por_piso=2),
            TipoUnidad(id="Tipo B", estrato="C", pisos=tuple(range(1, 9)), por_piso=2),
            TipoUnidad(id="Local", uso="local", area_m2=D(80), pisos=(0,), por_piso=3, fases=3),
        ],
        "servicios": [
            CargaGeneral(descripcion="Ascensor", kw=D("7.5"), motor=True),
            CargaGeneral(descripcion="Bombas", kw=D("3.7"), cantidad=2, motor=True),
            CargaGeneral(descripcion="Áreas comunes", kw=D(4), fp=D("0.95")),
        ],
    }
    datos.update(cambios)
    return Edificio.model_validate(datos)


def test_ids_de_unidades() -> None:
    assert id_unidad(1, 2) == "102"
    assert id_unidad(12, 4) == "1204"
    assert id_unidad(0, 1) == "PB-01"
    assert id_unidad(-1, 3) == "S1-03"


def test_demanda_con_coincidencia(perfil_cnel: Perfil) -> None:
    c = calcular_edificio(_torre(), perfil_cnel)
    deptos = next(g for g in c.grupos if g.nombre == "Departamentos")
    # 16 × 5,5 + 16 × 3,6 = 145,6 kVA; 32 usuarios → FC 0,41.
    assert deptos.usuarios == 32 and deptos.suma_kva == D("145.6")
    assert deptos.factor == D("0.41") and deptos.demanda_kva == D("59.696")
    locales = next(g for g in c.grupos if g.nombre == "Locales y oficinas")
    # 80 m² × 60 VA/m² × 0,8 = 3,84 kVA cada uno.
    assert locales.suma_kva == D("11.52")
    assert c.servicios is not None
    total = deptos.demanda_kva + locales.demanda_kva + c.servicios.demanda_kva
    assert c.demanda_kva == total
    assert c.medidores == 36 and c.modulos == 3
    assert c.nivel.id == "transformador_propio"
    assert c.transformador is not None and c.transformador.kva >= c.demanda_kva * D("1.2")
    assert c.camara is None
    assert c.principal.breaker_a is not None and c.principal.barra_a is not None


def test_alimentadores_por_piso(perfil_cnel: Perfil) -> None:
    c = calcular_edificio(_torre(), perfil_cnel)
    por_id = {u.id: u for u in c.unidades}
    # Centro de medición en planta baja: 3 m por piso + 10 m horizontales.
    assert por_id["101"].longitud_m == D(13) and por_id["804"].longitud_m == D(34)
    assert por_id["PB-01"].fases == 3
    assert all(u.conductor is not None and u.breaker_a for u in c.unidades)
    r = c.resultado("alimentador_unidad", "804")
    assert any("altura entre pisos" in s for s in r.supuestos)
    assert r.det("caida_pct") <= r.det("limite_pct")


def test_edificio_grande_lleva_camara(perfil_cnel: Perfil) -> None:
    grande = _torre(
        unidades=[TipoUnidad(id="Suite", estrato="A", pisos=tuple(range(1, 21)), por_piso=8)],
        resistividad_ohm_m=D(80),
    )
    c = calcular_edificio(grande, perfil_cnel)
    # 160 × 8 kVA × 0,32 ≈ 410 kVA más servicios y reserva: 630 kVA en cuarto.
    assert c.transformador is not None and c.transformador.montaje == "cuarto"
    assert c.camara is not None and c.camara.resistividad_ohm_m == D(80)


def test_generador_de_respaldo(perfil_cnel: Perfil) -> None:
    c = calcular_edificio(_torre(respaldo="servicios_generales"), perfil_cnel)
    assert c.generador is not None and c.generador.kva is not None
    assert c.generador.kva * D("0.8") >= c.generador.carga_kva
    assert c.generador.transferencia_a is not None
    total = calcular_edificio(_torre(respaldo="total"), perfil_cnel)
    assert total.generador is not None and total.generador.carga_kva == total.demanda_kva
    dxf = generar_unifilar_edificio(c)
    assert b"ATS" in dxf and b"CENTRO DE MEDICI" in dxf


def test_edificio_pequeno_desde_la_red(perfil_cnel: Perfil) -> None:
    chico = _torre(
        unidades=[TipoUnidad(id="Depto", estrato="E", pisos=(1, 2), por_piso=1)], servicios=[]
    )
    c = calcular_edificio(chico, perfil_cnel)
    assert c.nivel.id == "red_existente" and c.transformador is None
    assert any("red de CNEL" in a for a in c.avisos)
    assert c.servicios is None and c.medidores == 2


def test_datos_invalidos(perfil_cnel: Perfil) -> None:
    sin_area = _torre(unidades=[TipoUnidad(id="Local", uso="local", pisos=(0,))])
    with pytest.raises(DatoInvalido, match="área"):
        calcular_edificio(sin_area, perfil_cnel)
    with pytest.raises(ValueError, match="distintos"):
        _torre(unidades=[TipoUnidad(id="A", pisos=(1,)), TipoUnidad(id="A", pisos=(2,))])
    with pytest.raises(DatoInvalido, match="trifásico"):
        calcular_edificio(_torre(sistema="monofasico_trifilar_120_240"), perfil_cnel)


def test_iluminacion_de_oficinas(perfil_cnel: Perfil) -> None:
    oficinas = _torre(
        unidades=[TipoUnidad(id="Oficina", uso="oficina", area_m2=D(120), pisos=(1, 2), fases=3)],
        servicios=[],
    )
    c = calcular_edificio(oficinas, perfil_cnel)
    luz = c.iluminacion[0]
    # 500 lx × 120 m² ÷ (4000 lm × 0,6 × 0,8) = 31,25 → 32 paneles.
    assert luz.luminarias == 32 and luz.potencia_w == D(32 * 36)
    assert luz.lux_logrado >= D(500) and luz.circuitos_luz == 3
    # 120 ÷ 8 = 15 puestos × 2 tomas = 30 tomas en 3 circuitos.
    assert luz.puestos == 15 and luz.tomas == 30 and luz.circuitos_tomas == 3
    demanda = c.resultado("demanda_unidad", "Oficina").decimal
    assert demanda == max(luz.demanda_detallada_kva, luz.demanda_densidad_kva)
