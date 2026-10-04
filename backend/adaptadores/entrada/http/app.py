"""Construcción de la aplicación FastAPI: routers, manejo de errores, cabeceras de seguridad y frontend."""
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import cookie_parser

from ....aplicacion.casos_uso.acceso import IdentificarCliente
from ....aplicacion.casos_uso.voz import MAX_BYTES_AUDIO
from ....dominio.errores import NoAutenticado
from .errores_http import registrar_manejadores
from .seguridad import COOKIE_SESION

# Solo código propio: Chart.js, marked y DOMPurify se sirven desde /static/vendor (versiones fijadas), sin CDN
# ni scripts o estilos en línea.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
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

MAX_BYTES_CUERPO = 64 * 1024  # ninguna petición JSON legítima se acerca; /stt sube audio y tiene su propio tope
RUTAS_CON_CUERPO_GRANDE = ("/stt",)
MAX_BYTES_SUBIDA_AUDIO = MAX_BYTES_AUDIO + 64 * 1024  # el audio más la cabecera multipart


CABECERAS_SEGURIDAD = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",  # el navegador lo ignora por http
    "Cache-Control": "no-store",  # nada sensible se queda en la caché del navegador
}


def _token_de_la_cookie(cabecera: bytes) -> str | None:
    """El valor de la cookie `sesion` (por nombre exacto: `xsesion=1` no cuenta), o None.

    Se usa el mismo parser que Starlette para las rutas (última cookie repetida gana, comillas fuera): si el middleware
    y la dependencia leyeran cookies distintas, uno validaría una sesión y la otra usaría otra."""
    return cookie_parser(cabecera.decode("latin-1")).get(COOKIE_SESION) or None


class LimiteSubidaAudio:
    """Middleware ASGI de `/stt`: se decide ANTES de que nadie lea el cuerpo.

    Sin sesión válida → 401 (el token se valida de verdad con `IdentificarCliente`, no basta con que haya cookie);
    sin Content-Length (chunked) o por encima del tope → 413; y además se cuentan los bytes que llegan de verdad por si
    la cabecera mintiera. Sus respuestas llevan las cabeceras de seguridad, porque este middleware va por fuera del
    que las añade. (Ver incidencias 63 y 72.)
    """

    def __init__(self, app, identificar: IdentificarCliente):
        self._app = app
        self._identificar = identificar

    @staticmethod
    def _rechazo(detalle: str, codigo: int) -> JSONResponse:
        return JSONResponse({"detail": detalle}, status_code=codigo, headers=CABECERAS_SEGURIDAD)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/stt":
            return await self._app(scope, receive, send)
        cabeceras = {k.lower(): v for k, v in scope["headers"]}
        token = _token_de_la_cookie(cabeceras.get(b"cookie", b""))
        try:
            await run_in_threadpool(self._identificar, token)  # consulta SQLite: fuera del bucle de eventos
        except NoAutenticado as e:
            return await self._rechazo(e.mensaje, 401)(scope, receive, send)
        largo = cabeceras.get(b"content-length", b"")
        if not largo.isdigit() or b"transfer-encoding" in cabeceras or int(largo) > MAX_BYTES_SUBIDA_AUDIO:
            return await self._rechazo("El audio es demasiado grande.", 413)(scope, receive, send)
        recibidos = 0

        async def recibir():
            nonlocal recibidos
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                recibidos += len(mensaje.get("body", b""))
                if recibidos > MAX_BYTES_SUBIDA_AUDIO:  # cuerpo mayor que el declarado: se corta
                    return {"type": "http.request", "body": b"", "more_body": False}
            return mensaje

        await self._app(scope, recibir, send)

DESCRIPCION_API = """API de Unia, el asistente bancario conversacional de Unicaja (Reto Unicaja · UGR: «Habla con tu dinero»).

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
    {"name": "admin", "description": "Solo el perfil admin: gasto de tokens por cliente y su reinicio (pruebas y demos)."},
]


def crear_app(
    routers: list[APIRouter], frontend: Path, identificar: IdentificarCliente,
    al_arrancar: Callable[[], None] = lambda: None, documentar: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        al_arrancar()
        yield

    # por defecto no se publica el mapa de la API (/docs, /redoc, /openapi.json); se activa con DOCS_API=1
    app = FastAPI(
        title="Unia · API", version="1.0.0", description=DESCRIPCION_API, openapi_tags=ETIQUETAS,
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
        if peticion.method in ("POST", "PUT", "PATCH") and peticion.url.path not in RUTAS_CON_CUERPO_GRANDE:
            largo = peticion.headers.get("content-length")
            # sin Content-Length (chunked) no se puede acotar antes de leerlo: se rechaza
            if (largo is None and "transfer-encoding" in peticion.headers) or (largo and largo.isdigit() and int(largo) > MAX_BYTES_CUERPO):
                return JSONResponse({"detail": "La petición es demasiado grande."}, status_code=413)
        respuesta = await siguiente(peticion)
        en_docs = documentar and peticion.url.path in RUTAS_DOCS
        respuesta.headers["Content-Security-Policy"] = CSP_DOCS if en_docs else CSP
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["X-Frame-Options"] = "DENY"
        respuesta.headers["Referrer-Policy"] = "no-referrer"
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"  # el navegador lo ignora por http
        if peticion.url.path.startswith("/static"):
            # se guarda, pero el navegador pregunta siempre si cambió (ETag): así no sirve JS ni CSS viejos tras una actualización
            respuesta.headers["Cache-Control"] = "no-cache"
        else:
            respuesta.headers["Cache-Control"] = "no-store"  # nada sensible se queda en la caché del navegador
        return respuesta

    app.add_middleware(LimiteSubidaAudio, identificar=identificar)
    for router in routers:
        app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(frontend / "index.html")

    app.mount("/static", StaticFiles(directory=frontend), name="static")
    return app
