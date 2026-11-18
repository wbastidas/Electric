"""Viviendas de varios pisos: un plano por planta, tablero principal y subtableros."""

from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from electric.calculo.resultado import ALIMENTADOR, PROYECTO
from electric.cli import main
from electric.errores import DatoInvalido
from electric.modelo import Preferencias
from electric.perfiles import Perfil
from electric.pisos import PlanoPiso, codigo_piso, disenar_pisos
from electric.salida_cad.unifilar_pisos import generar_unifilar_pisos

EJEMPLO = Path(__file__).resolve().parents[2] / "ejemplos" / "vivienda-2-pisos"


def _planos(equipos_alta: tuple[str, ...] = ("ducha",)) -> list[PlanoPiso]:
    return [
        PlanoPiso(
            (EJEMPLO / "planta-baja.dxf").read_bytes(), "planta-baja.dxf", "Planta baja", 0,
            ("cocina", "ducha"),
        ),
        PlanoPiso(
            (EJEMPLO / "planta-alta.dxf").read_bytes(), "planta-alta.dxf", "Planta alta", 1,
            equipos_alta,
        ),
    ]  # fmt: skip


@pytest.fixture(scope="module")
def diseno(perfil_cnel: Perfil):  # type: ignore[no-untyped-def]
    return disenar_pisos(
        "Casa",
        _planos(),
        perfil_cnel,
        medidor_m=D(15),
        altura_piso_m=D("2.8"),
        preferencias=Preferencias(zona_climatica="costa"),
    )


def test_codigos_de_piso() -> None:
    assert [codigo_piso(n) for n in (-1, 0, 1, 2)] == ["S1", "PB", "P1", "P2"]


def test_cada_planta_se_lee_y_disena_con_su_plano(diseno) -> None:  # type: ignore[no-untyped-def]
    e = diseno.edificacion
    baja, alta = e.pisos
    assert baja.nombre == "Planta baja" and alta.nombre == "Planta alta"
    assert baja.proyecto.plano is not None and alta.proyecto.plano is not None
    assert {a.uso for a in baja.proyecto.plano.ambientes} >= {"cocina", "sala_comedor"}
    assert sum(a.uso == "dormitorio" for a in alta.proyecto.plano.ambientes) == 3
    # La fachada solo en la planta baja; la refrigeradora donde está la cocina.
    assert any(u.ambiente == "EXT" for u in baja.proyecto.plano.ubicaciones)
    assert not any(u.ambiente == "EXT" for u in alta.proyecto.plano.ubicaciones)
    tipos_alta = {c.tipo for c in alta.proyecto.cargas_especiales}
    assert "refrigeradora" not in tipos_alta and "ducha" in tipos_alta
    assert all(not avisos for avisos in diseno.avisos.values())


def test_subtablero_con_su_alimentador(diseno) -> None:  # type: ignore[no-untyped-def]
    e = diseno.edificacion
    assert e.principal.nivel == 0
    (sub,) = e.subtableros
    assert sub.tablero == "TD-P1"
    # Los tableros quedan uno sobre otro en la escalera: solo el tramo vertical.
    assert sub.vertical_m == D("2.8")
    assert sub.longitud_m == sub.vertical_m + sub.horizontal_m
    assert sub.calculado.proyecto.tablero.alimentador_longitud_m == sub.longitud_m
    assert sub.breaker_a < e.calculado.res("RC-09", ALIMENTADOR).decimal
    assert sub.caida_pct < D(2)
    # El plano de la planta alta lleva el tablero con su nombre nuevo.
    plano = sub.calculado.proyecto.plano
    assert plano is not None and any(u.id == "TD-P1" for u in plano.ubicaciones)


def test_la_vivienda_completa_junta_todos_los_circuitos(diseno) -> None:  # type: ignore[no-untyped-def]
    e = diseno.edificacion
    baja, alta = e.pisos
    assert e.area_m2 == baja.proyecto.area_construida_m2 + alta.proyecto.area_construida_m2
    assert len(e.conjunto.circuitos) == len(baja.proyecto.circuitos) + len(alta.proyecto.circuitos)
    assert all(c.id.startswith(("PB-", "P1-")) for c in e.conjunto.circuitos)
    demanda = e.calculado.res("RC-03", PROYECTO).decimal
    planta_alta = e.subtableros[0].demanda_w
    planta_baja = e.calculado_principal.res("RC-03", PROYECTO).decimal
    # La demanda de la vivienda no es la suma de las plantas: se aplica sobre el total.
    assert max(planta_alta, planta_baja) < demanda <= planta_alta + planta_baja
    assert e.calculado.res("RC-05", PROYECTO).valor == "Tipo II"


def test_unifilar_de_la_vivienda(diseno) -> None:  # type: ignore[no-untyped-def]
    texto = generar_unifilar_pisos(diseno.edificacion).decode("utf-8", errors="replace")
    for esperado in ("TABLERO PRINCIPAL TP", "SUBTABLERO TD-P1", "MEDIDOR CNEL EP", "P1"):
        assert esperado in texto


def test_dos_plantas_en_el_mismo_nivel(perfil_cnel: Perfil) -> None:
    planos = _planos()
    repetido = [planos[0], PlanoPiso(planos[1].contenido, "b.dxf", "Otra", 0)]
    with pytest.raises(DatoInvalido, match="mismo nivel"):
        disenar_pisos("X", repetido, perfil_cnel, medidor_m=D(10), altura_piso_m=D(3))


def test_una_sola_planta_no_es_de_varios_pisos(perfil_cnel: Perfil) -> None:
    with pytest.raises(DatoInvalido, match="al menos dos"):
        disenar_pisos("X", _planos()[:1], perfil_cnel, medidor_m=D(10), altura_piso_m=D(3))


def test_cli_disenar_pisos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argumentos = [
        "disenar-pisos",
        str(EJEMPLO / "planta-baja.dxf"),
        str(EJEMPLO / "planta-alta.dxf"),
        "--nombres", "Planta baja,Planta alta",
        "--equipos", "cocina,ducha;ducha",
        "--salida", str(tmp_path),
    ]  # fmt: skip
    assert main(argumentos) == 0
    salida = capsys.readouterr().out
    assert "TD-P1" in salida and "Vivienda completa" in salida
    for archivo in ("planta-baja-red.dxf", "planta-alta-red.png", "unifilar.pdf", "vivienda.json"):
        assert (tmp_path / archivo).exists()
