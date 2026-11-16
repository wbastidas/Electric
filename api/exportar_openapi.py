"""Escribe el contrato OpenAPI del que se generan los tipos de la interfaz web.

python exportar_openapi.py   # desde api/; luego `pnpm gen` en web/
"""

from __future__ import annotations

import json
from pathlib import Path

from electric_api.app import crear_app
from electric_api.config import Config

RAIZ = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    config = Config(
        base_de_datos="sqlite:///:memory:", perfiles=RAIZ / "perfiles", web=RAIZ / "sin-web"
    )
    contrato = crear_app(config).openapi()
    destino = Path(__file__).with_name("openapi.json")
    destino.write_text(json.dumps(contrato, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"escrito {destino}")
