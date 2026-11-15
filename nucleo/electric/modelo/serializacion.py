"""Serialización canónica: mismas entradas, mismos bytes, mismo hash (RNF-01)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

_CUANTO = Decimal("1e-9")


def decimal_a_texto(valor: Decimal) -> str:
    """Texto estable de un decimal: nueve decimales como máximo, sin ceros de relleno."""
    cuantizado = valor.quantize(_CUANTO)
    if cuantizado == 0:
        return "0"
    texto = format(cuantizado, "f")
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto


def _canonico(valor: Any) -> Any:
    if isinstance(valor, BaseModel):
        return _canonico(valor.model_dump())
    if is_dataclass(valor) and not isinstance(valor, type):
        return _canonico(asdict(valor))
    if isinstance(valor, Decimal):
        return decimal_a_texto(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {str(k): _canonico(v) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_canonico(v) for v in valor]
    if isinstance(valor, float):
        raise TypeError("el modelo no admite coma flotante; use Decimal")
    return valor


def a_json_canonico(valor: Any) -> str:
    """JSON con claves ordenadas y decimales como texto."""
    return json.dumps(_canonico(valor), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def hash_canonico(valor: Any) -> str:
    return hashlib.sha256(a_json_canonico(valor).encode("utf-8")).hexdigest()
