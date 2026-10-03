"""Construcción de la aplicación FastAPI: routers, manejo de errores y frontend estático."""
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ....dominio.errores import ErrorDeDominio, ErrorDeValidacion, ErrorNoDisponible, ErrorNoEncontrado


def _estado_http(error: ErrorDeDominio) -> int:
    if isinstance(error, ErrorNoEncontrado):
        return 404
    if isinstance(error, ErrorNoDisponible):
        return 503
    if isinstance(error, ErrorDeValidacion):
        return 422
    return 400


def crear_app(routers: list[APIRouter], frontend: Path, al_arrancar: Callable[[], None] = lambda: None) -> FastAPI:
    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        al_arrancar()
        yield

    app = FastAPI(title="Habla con tu dinero — Reto Unicaja/UGR", lifespan=ciclo_de_vida)

    @app.exception_handler(ErrorDeDominio)
    async def errores_de_dominio(_peticion: Request, error: ErrorDeDominio):
        return JSONResponse({"detail": error.mensaje}, status_code=_estado_http(error))

    for router in routers:
        app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(frontend / "index.html")

    app.mount("/static", StaticFiles(directory=frontend), name="static")
    return app
