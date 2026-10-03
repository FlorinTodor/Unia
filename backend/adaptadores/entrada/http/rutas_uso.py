"""Consumo de tokens de la IA del cliente."""
from collections.abc import Callable

from fastapi import APIRouter, Depends

from ....aplicacion.casos_uso.uso import ConsultarUso
from ....dominio.modelos import Cliente
from . import esquemas, presentadores


def crear_router(uso: ConsultarUso, cliente_actual: Callable[..., Cliente]) -> APIRouter:
    router = APIRouter(prefix="/api/uso", tags=["uso"], responses=esquemas.NO_AUTENTICADO)

    @router.get(
        "", response_model=esquemas.UsoOut, summary="Gasto de tokens de la IA",
        description=(
            "Tokens gastados hoy por el cliente frente a su límite diario, los topes por pregunta y por minuto, y las "
            "últimas llamadas al modelo. Si el proveedor no informa del gasto, se estima (`estimado: true`)."
        ),
    )
    def obtener_uso(cliente: Cliente = Depends(cliente_actual)):
        return presentadores.uso(uso(cliente))

    return router
