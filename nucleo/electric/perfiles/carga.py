"""Carga y consulta de perfiles.

Cada consulta devuelve el valor y un `RefTabla`, para que el cálculo que la
usa pueda decir de qué tabla, versión y fila salió cada número.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import TypeAdapter, ValidationError

from electric.errores import ErrorPerfil, FilaNoEncontrada
from electric.perfiles.esquema import (
    FilaAire,
    FilaArranque,
    FilaCamara,
    FilaCapaSIG,
    FilaCarga,
    FilaConductor,
    FilaConductorMT,
    FilaDemandaUsuario,
    FilaDucto,
    FilaEstiloLuz,
    FilaEstrato,
    FilaEstructuraMT,
    FilaFactorDemanda,
    FilaMedidor,
    FilaMinimoCalibre,
    FilaNivelLuz,
    FilaNivelServicio,
    FilaPlantilla,
    FilaSistema,
    FilaTipoIndustrial,
    FilaTramoDemanda,
    FilaTransformador,
    FilaTransformadorPotencia,
    FilaZonaClimatica,
    MetaPerfil,
    RefTabla,
    Tabla,
    TablaAires,
    TablaArranques,
    TablaBase,
    TablaCamaras,
    TablaCargas,
    TablaCircuitosMinimos,
    TablaCoincidencia,
    TablaConductores,
    TablaConductoresMT,
    TablaDemandaUsuarios,
    TablaDuctos,
    TablaEstilosLuz,
    TablaEstratos,
    TablaEstructurasMT,
    TablaFactoresAgrupamiento,
    TablaFactoresDemanda,
    TablaFactoresEspeciales,
    TablaFactoresTemperatura,
    TablaMedidores,
    TablaMinimosCalibre,
    TablaNivelesLuz,
    TablaNivelesServicio,
    TablaParametros,
    TablaPlantillas,
    TablaRedondeo,
    TablaSerie,
    TablaSIG,
    TablaSistemas,
    TablaTierraEquipos,
    TablaTiposIndustriales,
    TablaTramosDemanda,
    TablaTransformadores,
    TablaTransformadoresPotencia,
    TablaZonasClimaticas,
)

_ADAPTADOR_TABLA: TypeAdapter[Tabla] = TypeAdapter(Tabla)

T = TypeVar("T", bound=TablaBase)

_COMUNES = (
    "cargas",
    "sistemas_tension",
    "conductores",
    "factores_temperatura",
    "factores_agrupamiento",
    "minimos_calibre",
    "serie:breakers",
    "serie:espacios_tablero",
    "serie:barras",
    "medidores",
    "ductos",
    "tierra_equipos",
    "parametros",
    "redondeo",
    "circuitos_minimos",
)
_POR_METODO = {
    "por_categoria": ("factores_demanda", "factores_especiales"),
    "escalonado": ("tramos_demanda",),
}

#: Parámetros que todo perfil debe definir.
PARAMETROS_REQUERIDOS = (
    "factor_potencia",
    "temperatura_ambiente_c",
    "factor_diseno_conductor",
    "caida_ramal_max_pct",
    "caida_total_max_pct",
    "desbalance_max_pct",
    "umbral_tipo_i_kw",
    "umbral_tipo_ii_kw",
    "relleno_ducto_max_pct",
    "reserva_polos_cada",
    "principal_min_a",
    "resistencia_tierra_max_ohm",
    "pasos_max_calibre",
    "diferencial_zonas_humedas",
    "electrodo_longitud_m",
    "electrodo_diametro_pulg",
)


def _clave(tabla: Tabla) -> str:
    return f"serie:{tabla.serie}" if isinstance(tabla, TablaSerie) else tabla.tipo


@dataclass(frozen=True)
class Perfil:
    meta: MetaPerfil
    tablas: dict[str, Tabla]

    # -- acceso genérico ---------------------------------------------------

    def _tabla(self, clave: str, clase: type[T]) -> T:
        tabla = self.tablas.get(clave)
        if tabla is None:
            raise ErrorPerfil(f"el perfil {self.meta.id} no tiene la tabla '{clave}'")
        if not isinstance(tabla, clase):
            raise ErrorPerfil(f"la tabla '{clave}' no es del tipo esperado")
        return tabla

    @staticmethod
    def _ref(tabla: TablaBase, fila: str) -> RefTabla:
        return RefTabla(id=tabla.id, version=tabla.version, fila=fila, estado=tabla.estado)

    # -- parámetros y redondeo ---------------------------------------------

    def parametro(self, clave: str) -> tuple[Decimal, RefTabla]:
        tabla = self._tabla("parametros", TablaParametros)
        for fila in tabla.filas:
            if fila.clave == clave:
                return fila.valor, self._ref(tabla, clave)
        raise FilaNoEncontrada(tabla.id, f"el parámetro '{clave}'")

    def decimales(self, unidad: str) -> int | None:
        tabla = self._tabla("redondeo", TablaRedondeo)
        for fila in tabla.filas:
            if fila.unidad == unidad:
                return fila.decimales
        return None

    # -- cargas y demanda --------------------------------------------------

    def carga(self, tipo: str) -> tuple[FilaCarga, RefTabla]:
        tabla = self._tabla("cargas", TablaCargas)
        for fila in tabla.filas:
            if fila.tipo == tipo:
                return fila, self._ref(tabla, tipo)
        raise FilaNoEncontrada(tabla.id, f"el tipo de carga '{tipo}'")

    def circuitos_minimos(self, area_m2: Decimal) -> tuple[tuple[int, int], RefTabla]:
        """Mínimo de circuitos de iluminación y de tomacorrientes para un área."""
        tabla = self._tabla("circuitos_minimos", TablaCircuitosMinimos)
        for fila in tabla.filas:
            if not _en_tramo(area_m2, fila.area_max, fila.incluye_max):
                continue
            ref = self._ref(tabla, _texto_tramo("área", fila.area_max, fila.incluye_max))
            if fila.por_cada_m2 is not None:
                n = int((area_m2 / fila.por_cada_m2).to_integral_value(rounding="ROUND_CEILING"))
                return (n, n), ref
            if fila.iluminacion is None or fila.tomacorrientes is None:
                raise ErrorPerfil(f"fila incompleta en la tabla '{tabla.id}'")
            return (fila.iluminacion, fila.tomacorrientes), ref
        raise FilaNoEncontrada(tabla.id, f"un área de {area_m2} m²")

    def factores_demanda(self, area_m2: Decimal) -> tuple[FilaFactorDemanda, RefTabla]:
        tabla = self._tabla("factores_demanda", TablaFactoresDemanda)
        for fila in tabla.filas:
            if _en_tramo(area_m2, fila.area_max, fila.incluye_max):
                return fila, self._ref(tabla, fila.categoria)
        raise FilaNoEncontrada(tabla.id, f"un área de {area_m2} m²")

    def factor_especiales(self, cantidad: int) -> tuple[Decimal, RefTabla]:
        tabla = self._tabla("factores_especiales", TablaFactoresEspeciales)
        candidatas = [f for f in tabla.filas if f.cantidad_min <= cantidad]
        if not candidatas:
            raise FilaNoEncontrada(tabla.id, f"{cantidad} cargas especiales")
        fila = max(candidatas, key=lambda f: f.cantidad_min)
        return fila.factor, self._ref(tabla, f"desde {fila.cantidad_min} cargas")

    def tramos_demanda(self) -> tuple[tuple[FilaTramoDemanda, ...], RefTabla]:
        tabla = self._tabla("tramos_demanda", TablaTramosDemanda)
        return tabla.filas, self._ref(tabla, "todos los tramos")

    # -- plantillas de diseño ---------------------------------------------

    def plantillas(self) -> tuple[tuple[FilaPlantilla, ...], TablaPlantillas]:
        tabla = self._tabla("plantillas_ambiente", TablaPlantillas)
        return tabla.filas, tabla

    def plantilla(self, uso: str) -> tuple[FilaPlantilla, RefTabla]:
        filas, tabla = self.plantillas()
        for fila in filas:
            if fila.uso == uso:
                return fila, self._ref(tabla, uso)
        raise FilaNoEncontrada(tabla.id, f"el uso '{uso}'")

    # -- preferencias de diseño (tablas opcionales) -------------------------

    def estilos_iluminacion(self) -> tuple[FilaEstiloLuz, ...]:
        if "estilos_iluminacion" not in self.tablas:
            return ()
        return self._tabla("estilos_iluminacion", TablaEstilosLuz).filas

    def estilo_iluminacion(self, id: str) -> tuple[FilaEstiloLuz, RefTabla]:
        tabla = self._tabla("estilos_iluminacion", TablaEstilosLuz)
        for fila in tabla.filas:
            if fila.id == id:
                return fila, self._ref(tabla, id)
        raise FilaNoEncontrada(tabla.id, f"el estilo de iluminación '{id}'")

    def zonas_climaticas(self) -> tuple[FilaZonaClimatica, ...]:
        if "zonas_climaticas" not in self.tablas:
            return ()
        return self._tabla("zonas_climaticas", TablaZonasClimaticas).filas

    def zona_climatica(self, id: str) -> tuple[FilaZonaClimatica, RefTabla]:
        tabla = self._tabla("zonas_climaticas", TablaZonasClimaticas)
        for fila in tabla.filas:
            if fila.id == id:
                return fila, self._ref(tabla, id)
        raise FilaNoEncontrada(tabla.id, f"la zona climática '{id}'")

    def aires(self) -> tuple[FilaAire, ...]:
        return self._tabla("aires", TablaAires).filas

    def aire_para(self, btu: Decimal) -> tuple[FilaAire, RefTabla]:
        """Menor equipo comercial cuya capacidad cubre la requerida."""
        tabla = self._tabla("aires", TablaAires)
        for fila in tabla.filas:
            if fila.btu >= btu:
                return fila, self._ref(tabla, f"{fila.btu} BTU")
        raise FilaNoEncontrada(tabla.id, f"una capacidad de {btu} BTU")

    # -- industrial (tablas opcionales) ------------------------------------

    def es_industrial(self) -> bool:
        return all(
            c in self.tablas
            for c in ("tipos_industriales", "arranques", "transformadores", "niveles_servicio")
        )

    def tipos_industriales(self) -> tuple[FilaTipoIndustrial, ...]:
        if "tipos_industriales" not in self.tablas:
            return ()
        return self._tabla("tipos_industriales", TablaTiposIndustriales).filas

    def tipo_industrial(self, tipo: str) -> tuple[FilaTipoIndustrial, RefTabla]:
        tabla = self._tabla("tipos_industriales", TablaTiposIndustriales)
        for fila in tabla.filas:
            if fila.tipo == tipo:
                return fila, self._ref(tabla, tipo)
        raise FilaNoEncontrada(tabla.id, f"el tipo de carga industrial '{tipo}'")

    def arranques(self) -> tuple[FilaArranque, ...]:
        if "arranques" not in self.tablas:
            return ()
        return self._tabla("arranques", TablaArranques).filas

    def arranque(self, id: str) -> tuple[FilaArranque, RefTabla]:
        tabla = self._tabla("arranques", TablaArranques)
        for fila in tabla.filas:
            if fila.id == id:
                return fila, self._ref(tabla, id)
        raise FilaNoEncontrada(tabla.id, f"el arranque '{id}'")

    def transformador_para(self, kva: Decimal, fases: int) -> tuple[FilaTransformador, RefTabla]:
        """Menor transformador normalizado de esas fases que cubre la potencia."""
        tabla = self._tabla("transformadores", TablaTransformadores)
        for fila in sorted(tabla.filas, key=lambda f: f.kva):
            if fila.fases == fases and fila.kva >= kva:
                return fila, self._ref(tabla, f"{fila.kva} kVA {fila.fases}F")
        raise FilaNoEncontrada(tabla.id, f"un transformador de {fases} fases de {kva} kVA o más")

    def impedancia_transformador(self, kva: Decimal, fases: int) -> tuple[Decimal, RefTabla]:
        """Impedancia del normalizado más cercano, para un transformador existente."""
        tabla = self._tabla("transformadores", TablaTransformadores)
        candidatos = [f for f in tabla.filas if f.fases == fases] or list(tabla.filas)
        fila = min(candidatos, key=lambda f: abs(f.kva - kva))
        return fila.z_pct, self._ref(tabla, f"impedancia típica de {fila.kva} kVA")

    def nivel_servicio(self, demanda_kw: Decimal) -> tuple[FilaNivelServicio, RefTabla]:
        tabla = self._tabla("niveles_servicio", TablaNivelesServicio)
        for fila in tabla.filas:
            if fila.demanda_max_kw is None or demanda_kw <= fila.demanda_max_kw:
                return fila, self._ref(tabla, fila.id)
        raise FilaNoEncontrada(tabla.id, f"una demanda de {demanda_kw} kW")

    def niveles_servicio(self) -> tuple[FilaNivelServicio, ...]:
        if "niveles_servicio" not in self.tablas:
            return ()
        return self._tabla("niveles_servicio", TablaNivelesServicio).filas

    def estrato(self, estrato: str) -> tuple[FilaEstrato, RefTabla]:
        tabla = self._tabla("demanda_estratos", TablaEstratos)
        for fila in tabla.filas:
            if fila.estrato == estrato:
                return fila, self._ref(tabla, estrato)
        raise FilaNoEncontrada(tabla.id, f"el estrato '{estrato}'")

    def estratos(self) -> tuple[FilaEstrato, ...]:
        if "demanda_estratos" not in self.tablas:
            return ()
        return self._tabla("demanda_estratos", TablaEstratos).filas

    # -- edificios y urbanizaciones -------------------------------------

    def demanda_usuario(self, id: str) -> tuple[FilaDemandaUsuario, RefTabla]:
        tabla = self._tabla("demanda_usuarios", TablaDemandaUsuarios)
        for fila in tabla.filas:
            if fila.id == id:
                return fila, self._ref(tabla, id)
        raise FilaNoEncontrada(tabla.id, f"el tipo de usuario '{id}'")

    def demandas_usuario(self) -> tuple[FilaDemandaUsuario, ...]:
        if "demanda_usuarios" not in self.tablas:
            return ()
        return self._tabla("demanda_usuarios", TablaDemandaUsuarios).filas

    def nivel_luz(self, uso: str) -> tuple[FilaNivelLuz, RefTabla] | None:
        if "niveles_iluminacion" not in self.tablas:
            return None
        tabla = self._tabla("niveles_iluminacion", TablaNivelesLuz)
        for fila in tabla.filas:
            if fila.uso == uso:
                return fila, self._ref(tabla, uso)
        return None

    def transformadores_potencia(
        self,
    ) -> tuple[tuple[FilaTransformadorPotencia, ...], TablaTransformadoresPotencia]:
        tabla = self._tabla("transformadores_potencia", TablaTransformadoresPotencia)
        return tabla.filas, tabla

    def coincidencia(self, usuarios: int) -> tuple[Decimal, RefTabla]:
        tabla = self._tabla("coincidencia", TablaCoincidencia)
        for fila in tabla.filas:
            if fila.usuarios_max is None or usuarios <= fila.usuarios_max:
                return fila.factor, self._ref(tabla, f"{usuarios} usuarios")
        raise FilaNoEncontrada(tabla.id, f"{usuarios} usuarios")

    # -- media tensión (tablas opcionales) -------------------------------

    def conductores_mt(self) -> tuple[FilaConductorMT, ...]:
        if "conductores_mt" not in self.tablas:
            return ()
        return self._tabla("conductores_mt", TablaConductoresMT).filas

    def conductor_mt(self, calibre: str) -> tuple[FilaConductorMT, RefTabla]:
        tabla = self._tabla("conductores_mt", TablaConductoresMT)
        for fila in tabla.filas:
            if fila.calibre == calibre:
                return fila, self._ref(tabla, calibre)
        raise FilaNoEncontrada(tabla.id, f"el conductor de MT '{calibre}'")

    def estructuras_mt(self) -> tuple[tuple[FilaEstructuraMT, ...], RefTabla]:
        tabla = self._tabla("estructuras_mt", TablaEstructurasMT)
        return tabla.filas, self._ref(tabla, "tipos de estructura")

    def camara_para(self, kva: Decimal) -> tuple[FilaCamara, RefTabla]:
        tabla = self._tabla("camaras", TablaCamaras)
        for fila in sorted(tabla.filas, key=lambda f: f.kva_max):
            if kva <= fila.kva_max:
                return fila, self._ref(tabla, f"hasta {fila.kva_max} kVA")
        raise FilaNoEncontrada(tabla.id, f"una cámara de {kva} kVA")

    def servicio_sig(self) -> str | None:
        if "sig" not in self.tablas:
            return None
        return self._tabla("sig", TablaSIG).servicio

    def capas_sig(self) -> tuple[FilaCapaSIG, ...]:
        if "sig" not in self.tablas:
            return ()
        return self._tabla("sig", TablaSIG).filas

    # -- sistema de tensión ------------------------------------------------

    def sistema(self, id_sistema: str | None) -> tuple[FilaSistema, RefTabla]:
        buscado = id_sistema or self.meta.sistema_defecto
        tabla = self._tabla("sistemas_tension", TablaSistemas)
        for fila in tabla.filas:
            if fila.id == buscado:
                return fila, self._ref(tabla, buscado)
        raise FilaNoEncontrada(tabla.id, f"el sistema '{buscado}'")

    # -- conductores -------------------------------------------------------

    def conductores(self) -> tuple[tuple[FilaConductor, ...], TablaConductores]:
        tabla = self._tabla("conductores", TablaConductores)
        return tabla.filas, tabla

    def conductor(self, calibre: str) -> tuple[FilaConductor, RefTabla]:
        filas, tabla = self.conductores()
        for fila in filas:
            if fila.calibre == calibre:
                return fila, self._ref(tabla, calibre)
        raise FilaNoEncontrada(tabla.id, f"el calibre '{calibre}'")

    def factor_temperatura(self, t_c: Decimal) -> tuple[Decimal, RefTabla]:
        tabla = self._tabla("factores_temperatura", TablaFactoresTemperatura)
        for fila in sorted(tabla.filas, key=lambda f: f.t_max):
            if t_c <= fila.t_max:
                return fila.factor, self._ref(tabla, f"hasta {fila.t_max} °C")
        raise FilaNoEncontrada(tabla.id, f"una temperatura de {t_c} °C")

    def factor_agrupamiento(self, portadores: int) -> tuple[Decimal, RefTabla]:
        tabla = self._tabla("factores_agrupamiento", TablaFactoresAgrupamiento)
        for fila in sorted(tabla.filas, key=lambda f: f.n_max):
            if portadores <= fila.n_max:
                return fila.factor, self._ref(tabla, f"hasta {fila.n_max} conductores")
        raise FilaNoEncontrada(tabla.id, f"{portadores} conductores en un ducto")

    def minimo_calibre(self, uso: str) -> tuple[FilaMinimoCalibre, RefTabla]:
        tabla = self._tabla("minimos_calibre", TablaMinimosCalibre)
        for fila in tabla.filas:
            if fila.uso == uso:
                return fila, self._ref(tabla, uso)
        raise FilaNoEncontrada(tabla.id, f"el uso '{uso}'")

    # -- valores normalizados ----------------------------------------------

    def serie(self, nombre: str) -> tuple[tuple[Decimal, ...], TablaSerie]:
        tabla = self._tabla(f"serie:{nombre}", TablaSerie)
        return tabla.filas, tabla

    def normalizado(self, nombre: str, minimo: Decimal) -> tuple[Decimal, RefTabla]:
        """Primer valor normalizado de la serie que es mayor o igual al mínimo."""
        valores, tabla = self.serie(nombre)
        for valor in valores:
            if valor >= minimo:
                return valor, self._ref(tabla, f"{valor}")
        raise FilaNoEncontrada(tabla.id, f"un valor mayor o igual a {minimo}")

    def normalizado_hasta(self, nombre: str, maximo: Decimal) -> Decimal | None:
        """Mayor valor normalizado de la serie que no supera el máximo."""
        valores, _ = self.serie(nombre)
        admitidos = [v for v in valores if v <= maximo]
        return max(admitidos) if admitidos else None

    def medidor(self, breaker: Decimal) -> tuple[FilaMedidor, RefTabla]:
        tabla = self._tabla("medidores", TablaMedidores)
        for fila in tabla.filas:
            if fila.breaker_max is None or breaker <= fila.breaker_max:
                return fila, self._ref(tabla, fila.clase)
        raise FilaNoEncontrada(tabla.id, f"un breaker de {breaker} A")

    def ducto(self, area_requerida_mm2: Decimal) -> tuple[FilaDucto, RefTabla]:
        """Menor ducto cuya área interior es mayor o igual a la requerida."""
        tabla = self._tabla("ductos", TablaDuctos)
        for fila in sorted(tabla.filas, key=lambda f: f.area_mm2):
            if fila.area_mm2 >= area_requerida_mm2:
                return fila, self._ref(tabla, fila.designacion)
        raise FilaNoEncontrada(tabla.id, f"un área interior de {area_requerida_mm2} mm²")

    def tierra_equipos(self, breaker: Decimal) -> tuple[str, RefTabla]:
        tabla = self._tabla("tierra_equipos", TablaTierraEquipos)
        for fila in sorted(tabla.filas, key=lambda f: f.breaker_max):
            if breaker <= fila.breaker_max:
                return fila.calibre, self._ref(tabla, f"hasta {fila.breaker_max} A")
        raise FilaNoEncontrada(tabla.id, f"un breaker de {breaker} A")


def _en_tramo(valor: Decimal, maximo: Decimal | None, incluye: bool) -> bool:
    if maximo is None:
        return True
    return valor <= maximo if incluye else valor < maximo


def _texto_tramo(nombre: str, maximo: Decimal | None, incluye: bool) -> str:
    if maximo is None:
        return f"{nombre} en el último tramo"
    return f"{nombre} {'≤' if incluye else '<'} {maximo}"


def _leer_yaml(ruta: Path) -> Any:
    try:
        with ruta.open(encoding="utf-8") as archivo:
            return yaml.safe_load(archivo)
    except (OSError, yaml.YAMLError) as error:
        raise ErrorPerfil(f"no se pudo leer {ruta}: {error}") from error


def _ordenada(valores: Sequence[Decimal]) -> bool:
    return all(a < b for a, b in zip(valores, valores[1:], strict=False))


def cargar_perfil(carpeta: Path) -> Perfil:
    """Carga y valida un perfil; un perfil que no valida no se carga."""
    try:
        meta = MetaPerfil.model_validate(_leer_yaml(carpeta / "perfil.yaml"))
    except ValidationError as error:
        raise ErrorPerfil(f"perfil.yaml de {carpeta} no es válido:\n{error}") from error

    tablas: dict[str, Tabla] = {}
    ids: set[str] = set()
    for nombre in meta.tablas:
        try:
            tabla = _ADAPTADOR_TABLA.validate_python(_leer_yaml(carpeta / nombre))
        except ValidationError as error:
            raise ErrorPerfil(f"la tabla {nombre} no es válida:\n{error}") from error
        clave = _clave(tabla)
        if clave in tablas:
            raise ErrorPerfil(f"el perfil tiene dos tablas de tipo '{clave}'")
        if tabla.id in ids:
            raise ErrorPerfil(f"identificador de tabla repetido: {tabla.id}")
        if tabla.estado == "verificado" and tabla.verificacion is None:
            raise ErrorPerfil(f"la tabla {tabla.id} está 'verificado' sin registro de verificación")
        ids.add(tabla.id)
        tablas[clave] = tabla

    perfil = Perfil(meta=meta, tablas=tablas)
    _validar_cruces(perfil)
    return perfil


def _validar_cruces(perfil: Perfil) -> None:
    requeridas = _COMUNES + _POR_METODO[perfil.meta.demanda_metodo]
    faltan = [c for c in requeridas if c not in perfil.tablas]
    if faltan:
        raise ErrorPerfil(f"al perfil {perfil.meta.id} le faltan tablas: {', '.join(faltan)}")

    try:
        perfil.sistema(None)
        for clave in PARAMETROS_REQUERIDOS:
            perfil.parametro(clave)
        filas, _ = perfil.conductores()
        calibres = [f.calibre for f in filas]
        if len(calibres) != len(set(calibres)):
            raise ErrorPerfil("hay calibres repetidos en la tabla de conductores")
        if not _ordenada([f.ampacidad for f in filas]):
            raise ErrorPerfil("la tabla de conductores debe ir de menor a mayor ampacidad")
        for uso in ("iluminacion", "tomacorrientes", "especial", "alimentador"):
            minimo, _ = perfil.minimo_calibre(uso)
            perfil.conductor(minimo.calibre)
        tierra = perfil._tabla("tierra_equipos", TablaTierraEquipos)
        for fila in tierra.filas:
            perfil.conductor(fila.calibre)
        for nombre in ("breakers", "espacios_tablero", "barras"):
            valores, _ = perfil.serie(nombre)
            if not valores or not _ordenada(valores):
                raise ErrorPerfil(f"la serie '{nombre}' debe ir de menor a mayor, sin repetir")
    except FilaNoEncontrada as error:
        raise ErrorPerfil(f"perfil {perfil.meta.id} incompleto: {error}") from error
