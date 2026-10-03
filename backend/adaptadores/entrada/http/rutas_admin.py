"""Administración (solo perfil admin): gasto de tokens por cliente y reinicio del día, para pruebas y demos."""
from collections.abc import Callable

from fastapi import APIRouter, Depends

from ....aplicacion.casos_uso.uso import AdministrarUso
from ....dominio.modelos import Cliente
from . import esquemas, seguridad


def crear_router(uso: AdministrarUso, cliente_actual: Callable[..., Cliente]) -> APIRouter:
    admin_actual = seguridad.exigir_admin(cliente_actual)
    router = APIRouter(
        prefix="/api/admin", tags=["admin"],
        responses={**esquemas.NO_AUTENTICADO, 403: {"model": esquemas.ErrorOut, "description": "Solo el administrador."}},
    )

    @router.get("/uso", response_model=list[esquemas.UsoClienteOut], summary="Gasto de tokens de hoy por cliente")
    def listar(_: Cliente = Depends(admin_actual)):
        return [vars(u) for u in uso.listar()]

    @router.post(
        "/uso/{usuario}/reiniciar", response_model=esquemas.UsoClienteOut, summary="Reiniciar los tokens de hoy de un cliente",
        description="Borra el gasto de hoy de ese cliente (queda auditado). Pensado para pruebas y demos.",
        responses=esquemas.NO_ENCONTRADO,
    )
    def reiniciar(usuario: str, admin: Cliente = Depends(admin_actual)):
        return vars(uso.reiniciar(admin, usuario))

    return router
