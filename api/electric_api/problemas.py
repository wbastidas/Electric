"""Errores de la API en formato RFC 9457 (application/problem+json)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

TIPO = "application/problem+json"


class Problema(Exception):
    def __init__(self, estado: int, codigo: str, titulo: str, detalle: str = "") -> None:
        super().__init__(titulo)
        self.estado = estado
        self.codigo = codigo
        self.titulo = titulo
        self.detalle = detalle


def _respuesta(estado: int, codigo: str, titulo: str, **extra: Any) -> JSONResponse:
    cuerpo = {"type": f"urn:electric:{codigo}", "title": titulo, "status": estado, "codigo": codigo}
    cuerpo.update({k: v for k, v in extra.items() if v})
    return JSONResponse(cuerpo, status_code=estado, media_type=TIPO)


def registrar(app: FastAPI) -> None:
    @app.exception_handler(Problema)
    async def _problema(_: Request, error: Problema) -> JSONResponse:
        return _respuesta(error.estado, error.codigo, error.titulo, detail=error.detalle)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, error: RequestValidationError) -> JSONResponse:
        errores = [
            {"campo": ".".join(str(p) for p in e["loc"][1:]), "mensaje": e["msg"]}
            for e in error.errors()
        ]
        return _respuesta(
            422, "datos_invalidos", "Los datos enviados no son válidos", errores=errores
        )

    @app.exception_handler(HTTPException)
    async def _http(_: Request, error: HTTPException) -> JSONResponse:
        return _respuesta(error.status_code, "http", str(error.detail))
