"""Confirmación de operaciones con OTP y móvil simulado.

El código se valida AQUÍ, en un endpoint aparte: nunca pasa por el chat ni por el LLM.
"""
from collections.abc import Callable

from fastapi import APIRouter, Depends

from ....aplicacion.casos_uso.bizum import CancelarOperacion, ConfirmarOperacion
from ....aplicacion.casos_uso.movil import LeerMensajesMovil
from ....dominio.modelos import Cliente
from . import esquemas, presentadores


def crear_router(
    confirmar: ConfirmarOperacion,
    cancelar: CancelarOperacion,
    movil: LeerMensajesMovil,
    cliente_actual: Callable[..., Cliente],
) -> APIRouter:
    router = APIRouter(tags=["operaciones"], responses=esquemas.NO_AUTENTICADO)

    @router.post(
        "/operaciones/{id_operacion}/confirmar", response_model=esquemas.ComprobanteOut | esquemas.ComprobanteTarjetaOut,
        summary="Confirmar una operación con su código OTP",
        description=(
            "Si el código es correcto se ejecuta la operación (el Bizum o el desbloqueo de la tarjeta). El código vale 5 minutos, 3 intentos y un solo uso. "
            "Una operación de otro cliente responde 404, como si no existiera."
        ),
        responses={
            **esquemas.PETICION_INVALIDA, **esquemas.VALIDACION, **esquemas.NO_ENCONTRADO,
            **esquemas.CONFLICTO, **esquemas.CADUCADO, **esquemas.BLOQUEADO,
        },
    )
    def confirmar_operacion(id_operacion: str, peticion: esquemas.PeticionCodigo, cliente: Cliente = Depends(cliente_actual)):
        return presentadores.comprobante(confirmar(cliente, id_operacion, peticion.codigo))

    @router.post(
        "/operaciones/{id_operacion}/aprobar", response_model=esquemas.ComprobanteOut | esquemas.ComprobanteTarjetaOut,
        summary="Aprobar una operación con huella o Face ID (simulado)",
        description=(
            "Alternativa **accesible** al código: quien no puede leer o teclear el OTP (ceguera, motricidad) aprueba "
            "con un gesto desde el móvil, como en las apps bancarias reales. Mismas condiciones que el código: la "
            "operación debe ser del cliente, estar pendiente y no haber caducado. Tampoco pasa nunca por el LLM."
        ),
        responses={**esquemas.NO_ENCONTRADO, **esquemas.CONFLICTO, **esquemas.CADUCADO},
    )
    def aprobar_operacion(id_operacion: str, cliente: Cliente = Depends(cliente_actual)):
        return presentadores.comprobante(confirmar.aprobar(cliente, id_operacion))

    @router.post(
        "/operaciones/{id_operacion}/cancelar", response_model=esquemas.OkOut, summary="Cancelar una operación pendiente",
        responses={**esquemas.NO_ENCONTRADO, **esquemas.CONFLICTO},
    )
    def cancelar_operacion(id_operacion: str, cliente: Cliente = Depends(cliente_actual)):
        cancelar(cliente, id_operacion)
        return {"ok": True}

    @router.get(
        "/movil/mensajes", response_model=list[esquemas.SmsOut], summary="SMS del móvil simulado",
        description="Los 10 más recientes. Es el único canal por el que viaja el código OTP.",
    )
    def mensajes_movil(cliente: Cliente = Depends(cliente_actual)):
        return movil(cliente)

    return router
