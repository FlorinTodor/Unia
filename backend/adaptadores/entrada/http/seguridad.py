"""Autenticación en la entrada HTTP: sesión por cookie `HttpOnly` + `SameSite=Strict`."""
from collections.abc import Callable

from fastapi import Response, Security
from fastapi.security import APIKeyCookie

from ....aplicacion.casos_uso.acceso import IdentificarCliente
from ....dominio.modelos import Cliente

COOKIE_SESION = "sesion"
SEGUNDOS_SESION = 8 * 3600

# declara el esquema en OpenAPI: Swagger muestra el candado y envía la cookie de la sesión iniciada
_ESQUEMA_COOKIE = APIKeyCookie(
    name=COOKIE_SESION, auto_error=False, description="Sesión iniciada con `POST /auth/login` (la pone el servidor)."
)


def crear_dependencia(identificar: IdentificarCliente) -> Callable[..., Cliente]:
    """Dependencia de FastAPI: devuelve el cliente de la cookie o lanza NoAutenticado (→ 401)."""

    def cliente_actual(token: str | None = Security(_ESQUEMA_COOKIE)) -> Cliente:
        return identificar(token)

    return cliente_actual


def poner_cookie(respuesta: Response, token: str, segura: bool) -> None:
    respuesta.set_cookie(
        COOKIE_SESION, token, max_age=SEGUNDOS_SESION, httponly=True,  # inaccesible para JavaScript
        samesite="strict",  # no viaja en peticiones iniciadas desde otros sitios (anti-CSRF)
        secure=segura, path="/",
    )


def borrar_cookie(respuesta: Response) -> None:
    respuesta.delete_cookie(COOKIE_SESION, path="/")
