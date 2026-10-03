"""Construcción de la aplicación FastAPI: routers, manejo de errores, cabeceras de seguridad y frontend."""
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .errores_http import registrar_manejadores

# Solo se admite código propio y las tres librerías pinneadas de jsDelivr; sin scripts ni estilos en línea.
CSP = (
    "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self'; "
    "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


# Swagger UI y ReDoc cargan scripts y estilos de jsDelivr y arrancan con un script en línea:
# solo se permite en sus rutas y solo si se activa con DOCS_API=1.
CSP_DOCS = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "worker-src blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)
RUTAS_DOCS = ("/docs", "/redoc", "/openapi.json")

DESCRIPCION_API = """API del asistente bancario conversacional «Habla con tu dinero» (Reto Unicaja · UGR).

**Autenticación.** Todo menos el login exige la cookie de sesión `sesion` (`HttpOnly`, `SameSite=Strict`).
En Swagger: ejecuta `POST /auth/login` con una cuenta de demostración y las demás peticiones usarán la cookie.

**Seguridad.** El asistente (LLM) nunca mueve dinero: un Bizum solo se ejecuta tras confirmar el código OTP
que llega al móvil simulado, por `POST /operaciones/{id}/confirmar`.

**Errores.** Los fallos de negocio devuelven `{"detail": "mensaje legible"}` con 401, 404, 422, 429 o 503."""

ETIQUETAS = [
    {"name": "auth", "description": "Login con contraseña, sesión por cookie y bloqueo temporal tras intentos fallidos."},
    {"name": "chat", "description": "Conversación con el asistente (streaming SSE)."},
    {"name": "voz", "description": "Transcripción (Whisper) y síntesis (Piper)."},
    {"name": "banco", "description": "API bancaria ficticia: saldo, contactos, movimientos e inicio de Bizum."},
    {"name": "operaciones", "description": "Confirmación de operaciones con código OTP y móvil simulado."},
    {"name": "ajustes", "description": "Claves API, modelos y IA local. Las claves nunca salen del servidor."},
    {"name": "estado", "description": "Modelo en uso y disponibilidad de la voz."},
    {"name": "uso", "description": "Gasto de tokens de la IA frente a los límites por cliente."},
]


def crear_app(
    routers: list[APIRouter], frontend: Path, al_arrancar: Callable[[], None] = lambda: None, documentar: bool = False
) -> FastAPI:
    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        al_arrancar()
        yield

    # por defecto no se publica el mapa de la API (/docs, /redoc, /openapi.json); se activa con DOCS_API=1
    app = FastAPI(
        title="Habla con tu dinero", version="1.0.0", description=DESCRIPCION_API, openapi_tags=ETIQUETAS,
        lifespan=ciclo_de_vida,
        docs_url="/docs" if documentar else None,
        redoc_url="/redoc" if documentar else None,
        openapi_url="/openapi.json" if documentar else None,
    )

    registrar_manejadores(app)

    @app.middleware("http")
    async def cabeceras_de_seguridad(peticion: Request, siguiente):
        # defensa en profundidad sobre SameSite=Strict: una escritura que declara venir de otro sitio se rechaza
        origen = peticion.headers.get("origin")
        if origen and peticion.method not in ("GET", "HEAD", "OPTIONS") and urlsplit(origen).netloc != peticion.url.netloc:
            return JSONResponse({"detail": "Origen no permitido."}, status_code=403)
        respuesta = await siguiente(peticion)
        en_docs = documentar and peticion.url.path in RUTAS_DOCS
        respuesta.headers["Content-Security-Policy"] = CSP_DOCS if en_docs else CSP
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["X-Frame-Options"] = "DENY"
        respuesta.headers["Referrer-Policy"] = "no-referrer"
        if not peticion.url.path.startswith("/static"):
            respuesta.headers["Cache-Control"] = "no-store"  # nada sensible se queda en la caché del navegador
        return respuesta

    for router in routers:
        app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(frontend / "index.html")

    app.mount("/static", StaticFiles(directory=frontend), name="static")
    return app
