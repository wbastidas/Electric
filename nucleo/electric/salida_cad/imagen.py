"""Imagen PNG o PDF de un DXF, para revisar sin abrir CAD."""

from __future__ import annotations

import io
from typing import Literal

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from ezdxf import recover  # noqa: E402
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration  # noqa: E402
from ezdxf.addons.drawing.frontend import Frontend  # noqa: E402
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402
from ezdxf.addons.drawing.properties import RenderContext  # noqa: E402

from electric.errores import DatoInvalido  # noqa: E402


def renderizar(
    dxf: bytes, formato: Literal["png", "pdf"] = "png", ancho_pulg: float = 16.5
) -> bytes:
    """Dibuja el espacio modelo sobre fondo blanco, en tamaño A3 apaisado."""
    try:
        doc, _ = recover.read(io.BytesIO(dxf))
    except Exception as error:  # noqa: BLE001
        raise DatoInvalido(f"no se pudo leer el DXF: {error}") from error
    figura = plt.figure(figsize=(ancho_pulg, ancho_pulg / 1.414))
    try:
        ejes = figura.add_axes((0.02, 0.02, 0.96, 0.96))
        config = Configuration(
            background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR
        )
        Frontend(RenderContext(doc), MatplotlibBackend(ejes), config=config).draw_layout(
            doc.modelspace(), finalize=True
        )
        salida = io.BytesIO()
        # Sin metadatos de fecha, para que la misma entrada dé el mismo archivo.
        metadatos = {"CreationDate": None} if formato == "pdf" else {"Software": None}
        figura.savefig(salida, format=formato, dpi=150, metadata=metadatos)
        return salida.getvalue()
    finally:
        plt.close(figura)
