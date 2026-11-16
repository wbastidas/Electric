"""Arranque de desarrollo: `python -m electric_api`."""

from __future__ import annotations

import uvicorn

from electric_api.app import crear_app

if __name__ == "__main__":
    uvicorn.run(crear_app(), host="127.0.0.1", port=8000)
