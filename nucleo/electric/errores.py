"""Errores tipados del núcleo.

Ante un dato que falta, el núcleo se detiene con uno de estos errores para que
la interfaz lo convierta en una pregunta; nunca interpola ni asume (RNF-13).
"""

from __future__ import annotations


class ErrorElectric(Exception):
    """Base de los errores del núcleo. `codigo` es estable y lo usa la interfaz."""

    codigo = "error"


class ErrorPerfil(ErrorElectric):
    """El perfil no es válido o no se pudo cargar."""

    codigo = "perfil_invalido"


class FilaNoEncontrada(ErrorElectric):
    """Una tabla del perfil no tiene fila para el dato pedido."""

    codigo = "fila_no_encontrada"

    def __init__(self, tabla: str, consulta: str) -> None:
        super().__init__(f"la tabla '{tabla}' no tiene fila para {consulta}")
        self.tabla = tabla
        self.consulta = consulta


class DatoInvalido(ErrorElectric):
    """Un dato del proyecto no se puede usar con el perfil elegido."""

    codigo = "dato_invalido"


class SinSolucion(ErrorElectric):
    """Ningún valor normalizado del perfil cumple las condiciones del cálculo."""

    codigo = "sin_solucion"

    def __init__(self, sujeto: str, motivo: str) -> None:
        super().__init__(f"{sujeto}: {motivo}")
        self.sujeto = sujeto
        self.motivo = motivo
