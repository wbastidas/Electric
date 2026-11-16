"""Salida CAD: DXF con la instalación en capas propias, y su imagen o PDF."""

from electric.salida_cad.dxf import CAPAS, generar_dxf
from electric.salida_cad.imagen import renderizar

__all__ = ["CAPAS", "generar_dxf", "renderizar"]
