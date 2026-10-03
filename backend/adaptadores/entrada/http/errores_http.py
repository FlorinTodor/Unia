"""Traducción de errores a respuestas HTTP: un solo lugar, con todos los casos.

Cuerpo de TODA respuesta de error: `{"detail": "mensaje legible", ...datos opcionales}`.
"""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as ErrorHttpStarlette

from ....dominio.errores import (
    ErrorBloqueado,
    ErrorCaducado,
    ErrorCargaExcesiva,
    ErrorDeAccesoDenegado,
    ErrorDeAutenticacion,
    ErrorDeConflicto,
    ErrorDeDominio,
    ErrorDeValidacion,
    ErrorLimiteExcedido,
    ErrorNoDisponible,
    ErrorNoEncontrado,
    ErrorProveedorExterno,
    ErrorTiempoAgotado,
    ErrorTipoNoSoportado,
)

log = logging.getLogger(__name__)

# categoría → código HTTP. Se recorre la jerarquía de la clase: gana la más específica.
ESTADOS: dict[type[ErrorDeDominio], int] = {
    ErrorDeValidacion: 422,
    ErrorDeAutenticacion: 401,
    ErrorDeAccesoDenegado: 403,
    ErrorNoEncontrado: 404,
    ErrorDeConflicto: 409,
    ErrorCaducado: 410,
    ErrorCargaExcesiva: 413,
    ErrorTipoNoSoportado: 415,
    ErrorBloqueado: 423,
    ErrorLimiteExcedido: 429,
    ErrorProveedorExterno: 502,
    ErrorTiempoAgotado: 504,
    ErrorNoDisponible: 503,
}
ESTADO_POR_DEFECTO = 400  # solo para ErrorDeDominio sin categoría; tests/test_errores_http.py impide que ocurra

TEXTOS_HTTP = {
    404: "No existe ese recurso.",
    405: "Método no permitido para este recurso.",
    406: "Formato de respuesta no disponible.",
    413: "La petición es demasiado grande.",
    415: "Formato de contenido no soportado.",
}


def estado_http(error: ErrorDeDominio) -> int:
    for clase in type(error).__mro__:
        if clase in ESTADOS:
            return ESTADOS[clase]
    return ESTADO_POR_DEFECTO


def _respuesta(estado: int, detalle: str, cabeceras: dict | None = None, **extra) -> JSONResponse:
    return JSONResponse({"detail": detalle, **extra}, status_code=estado, headers=cabeceras)


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorDeDominio)
    async def errores_de_dominio(_peticion: Request, error: ErrorDeDominio):
        cabeceras = None
        if isinstance(error, ErrorLimiteExcedido) and error.reintentar_en:
            cabeceras = {"Retry-After": str(error.reintentar_en)}
        return _respuesta(estado_http(error), error.mensaje, cabeceras, **error.datos)

    @app.exception_handler(RequestValidationError)
    async def peticion_invalida(_peticion: Request, error: RequestValidationError):
        errores = error.errors()
        campos = [{"campo": ".".join(str(x) for x in e["loc"][1:]) or e["loc"][0], "motivo": e["msg"]} for e in errores]
        json_roto = any(e["type"] == "json_invalid" for e in errores)
        sin_cuerpo = all(e["loc"] == ("body",) for e in errores)  # no hay cuerpo JSON (o no es un objeto)
        if json_roto or sin_cuerpo:
            return _respuesta(400, "La petición no es un JSON válido o está vacía.", errores=campos)
        nombres = ", ".join(sorted({c["campo"] for c in campos}))
        return _respuesta(422, f"Datos no válidos: revisa {nombres}.", errores=campos)

    @app.exception_handler(ErrorHttpStarlette)
    async def errores_http(_peticion: Request, error: ErrorHttpStarlette):
        return _respuesta(error.status_code, TEXTOS_HTTP.get(error.status_code, str(error.detail)), getattr(error, "headers", None))

    @app.exception_handler(Exception)
    async def error_inesperado(peticion: Request, error: Exception):
        referencia = uuid.uuid4().hex[:10]
        log.error("Error inesperado [%s] %s %s", referencia, peticion.method, peticion.url.path, exc_info=error)
        return _respuesta(500, f"Error interno del servidor. Referencia: {referencia}.")
