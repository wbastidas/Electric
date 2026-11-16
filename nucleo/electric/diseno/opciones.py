"""Del asistente a las opciones iniciales: Básica, Recomendada y Confort.

El usuario responde unas pocas preguntas (clima, aire, gustos de iluminación,
equipos y exteriores) y la plataforma le devuelve tres escenarios para elegir:

- **Básica:** lo mínimo. Plafón según el área, sin aire, sin refrigeradora
  dedicada; exteriores solo si los pidió.
- **Recomendada:** exactamente lo que respondió.
- **Confort:** ojos de buey en las zonas sociales, aire en todos los ambientes
  que lo admiten, refrigeradora dedicada y fachada completa.

Las tres llevan los mismos equipos declarados (ducha, cocina…), así la
comparación muestra solo el efecto de los criterios.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from electric.errores import DatoInvalido
from electric.modelo.entidades import PreferenciaAmbiente, Preferencias
from electric.modelo.plano import Plano
from electric.perfiles.carga import Perfil

Opcion = Literal["basica", "recomendada", "confort"]
OPCIONES: tuple[Opcion, ...] = ("basica", "recomendada", "confort")
NOMBRES: dict[Opcion, str] = {
    "basica": "Básica",
    "recomendada": "Recomendada",
    "confort": "Confort",
}
#: Estilo de las zonas sociales en la opción Confort.
ESTILO_CONFORT = "ojos_de_buey"


class Respuestas(BaseModel):
    """Lo que el usuario contestó en el asistente."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    zona_climatica: str | None = None
    #: "zona": según la zona climática; "dormitorios": solo dormitorios;
    #: "todos": todos los ambientes que lo admiten; "ninguno".
    aire: Literal["zona", "dormitorios", "todos", "ninguno"] = "zona"
    #: Estilo para toda la casa.
    iluminacion: str = "plafon"
    #: Estilos para sala, comedor, cocina y estudio, y para dormitorios; si
    #: faltan, el general.
    iluminacion_social: str | None = None
    iluminacion_dormitorios: str | None = None
    refrigeradora: bool = True
    exteriores: bool = True
    #: Cargas especiales que el usuario declaró: ducha, cocina, calefón…
    equipos: tuple[str, ...] = Field(default=(), max_length=30)


def _por_zona(plano: Plano, perfil: Perfil) -> dict[str, tuple[str, bool]]:
    """Por ambiente: zona de la casa y si su plantilla admite aire."""
    salida: dict[str, tuple[str, bool]] = {}
    for ambiente in plano.ambientes:
        plantilla = perfil.plantilla(ambiente.uso)[0]
        salida[ambiente.id] = (plantilla.zona_casa, plantilla.aire)
    return salida


def preferencias_para(
    opcion: Opcion, respuestas: Respuestas, plano: Plano, perfil: Perfil
) -> Preferencias:
    """Criterios de diseño de una de las tres opciones iniciales."""
    estilos = {e.id for e in perfil.estilos_iluminacion()}
    for estilo in (
        respuestas.iluminacion,
        respuestas.iluminacion_social,
        respuestas.iluminacion_dormitorios,
    ):
        if estilo is not None and estilo not in estilos:
            raise DatoInvalido(f"el perfil no tiene el estilo de iluminación {estilo}")
    if respuestas.zona_climatica is not None:
        perfil.zona_climatica(respuestas.zona_climatica)
    for tipo in respuestas.equipos:
        if not perfil.carga(tipo)[0].especial:
            raise DatoInvalido(f"'{tipo}' no es un equipo especial del perfil")

    zonas = _por_zona(plano, perfil)
    ambientes: dict[str, PreferenciaAmbiente] = {}

    if opcion == "basica":
        for aid in zonas:
            ambientes[aid] = PreferenciaAmbiente(aire=False)
        return Preferencias(
            iluminacion="plafon" if "plafon" in estilos else respuestas.iluminacion,
            zona_climatica=respuestas.zona_climatica,
            refrigeradora=False,
            exteriores=respuestas.exteriores,
            ambientes=ambientes,
        )

    for aid, (zona, admite_aire) in zonas.items():
        luz: str | None = None
        if zona == "social":
            luz = respuestas.iluminacion_social
            if opcion == "confort" and ESTILO_CONFORT in estilos:
                luz = ESTILO_CONFORT
        elif zona == "dormitorios":
            luz = respuestas.iluminacion_dormitorios
        aire: bool | None = None
        if opcion == "confort":
            aire = admite_aire
        elif respuestas.aire == "ninguno":
            aire = False
        elif respuestas.aire == "todos":
            aire = admite_aire
        elif respuestas.aire == "dormitorios":
            aire = admite_aire and zona == "dormitorios"
        if luz is not None or aire is not None:
            ambientes[aid] = PreferenciaAmbiente(iluminacion=luz, aire=aire)

    confort = opcion == "confort"
    return Preferencias(
        iluminacion=respuestas.iluminacion,
        zona_climatica=respuestas.zona_climatica,
        refrigeradora=respuestas.refrigeradora or confort,
        exteriores=respuestas.exteriores or confort,
        ambientes=ambientes,
    )
