"""Login, sesión actual y logout."""
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request, Response

from ....aplicacion.casos_uso.acceso import CerrarSesion, IniciarSesion
from ....dominio.modelos import Cliente
from . import esquemas, presentadores, seguridad


CABECERAS_DE_PROXY = ("x-forwarded-for", "x-real-ip", "forwarded")
ORIGEN_NO_FIABLE = "origen-no-fiable"


def origen_de(solicitud: Request, proxy_de_confianza: bool = False) -> str | None:
    """IP de origen para el límite de login.

    Uvicorn (`proxy_headers` activo por defecto) sustituye `scope["client"]` por el `X-Forwarded-For` que llegue desde
    127.0.0.1, así que sin un proxy propio cualquiera podría falsificar su IP y esquivar (o cargarse) el límite. Si la
    petición trae cabeceras de proxy y no se ha declarado `PROXY_DE_CONFIANZA=1`, el origen no es fiable y todas esas
    peticiones comparten un único contador: falsificar la cabecera no da un contador nuevo.
    """
    if not proxy_de_confianza and any(c in solicitud.headers for c in CABECERAS_DE_PROXY):
        return ORIGEN_NO_FIABLE
    return solicitud.client.host if solicitud.client else None


def crear_router(
    iniciar: IniciarSesion, cerrar: CerrarSesion, cliente_actual: Callable[..., Cliente], cookie_segura: bool | None,
    proxy_de_confianza: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.post(
        "/login", response_model=esquemas.ClienteOut, summary="Iniciar sesión",
        description=(
            "Comprueba usuario y contraseña (scrypt) y deja una cookie `sesion` `HttpOnly` y `SameSite=Strict`. "
            "Tras 5 intentos fallidos el usuario (o 100 en 15 minutos desde un mismo origen) queda bloqueado 5 minutos. El mensaje de error es el mismo "
            "para un usuario inexistente y para una contraseña errónea."
        ),
        responses={
            401: {"model": esquemas.ErrorOut, "description": "Usuario o contraseña incorrectos."},
            429: {"model": esquemas.ErrorOut, "description": "Demasiados intentos: cuenta bloqueada temporalmente."},
        },
    )
    def login(peticion: esquemas.PeticionLogin, respuesta: Response, solicitud: Request):
        origen = origen_de(solicitud, proxy_de_confianza)
        token, cliente = iniciar(peticion.usuario, peticion.contrasena, origen)
        seguridad.poner_cookie(respuesta, token, seguridad.cookie_segura(solicitud, cookie_segura))
        return presentadores.cliente(cliente)

    @router.get(
        "/yo", response_model=esquemas.ClienteOut, summary="Cliente de la sesión actual",
        responses=esquemas.NO_AUTENTICADO,
    )
    def yo(cliente: Cliente = Depends(cliente_actual)):
        return presentadores.cliente(cliente)

    @router.post("/logout", response_model=esquemas.OkOut, summary="Cerrar sesión",
                 description="Invalida la sesión en el servidor y borra la cookie. Es idempotente.")
    def logout(peticion: Request, respuesta: Response):
        token = peticion.cookies.get(seguridad.COOKIE_SESION)
        try:
            cliente = cliente_actual(token)
        except Exception:  # sin sesión válida: el logout es igualmente correcto
            cliente = None
        cerrar(token, cliente)
        seguridad.borrar_cookie(respuesta)
        return {"ok": True}

    return router
