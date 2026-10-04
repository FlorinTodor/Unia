"""API bancaria ficticia (REST): saldo, contactos, Bizum y movimientos del cliente autenticado."""
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query

from ....aplicacion.casos_uso.banco import ConsultarMovimientos, ConsultarSaldo, ListarContactos
from ....aplicacion.casos_uso.bizum import SolicitarBizum
from ....aplicacion.casos_uso.tarjetas import ConsultarTarjetas
from ....dominio.modelos import Cliente
from . import esquemas, presentadores


def crear_router(
    saldo: ConsultarSaldo,
    contactos: ListarContactos,
    bizum: SolicitarBizum,
    movimientos: ConsultarMovimientos,
    tarjetas: ConsultarTarjetas,
    cliente_actual: Callable[..., Cliente],
) -> APIRouter:
    router = APIRouter(prefix="/api/banco", tags=["banco"], responses=esquemas.NO_AUTENTICADO)

    @router.get("/saldo", response_model=esquemas.CuentaOut, summary="Saldo de la cuenta")
    def obtener_saldo(cliente: Cliente = Depends(cliente_actual)):
        return presentadores.cuenta(saldo(cliente))

    @router.get("/contactos", response_model=list[esquemas.ContactoOut], summary="Contactos Bizum del cliente")
    def obtener_contactos(cliente: Cliente = Depends(cliente_actual)):
        return [{"nombre": c.nombre, "telefono": c.telefono} for c in contactos(cliente)]

    @router.get("/tarjetas", response_model=list[esquemas.TarjetaOut], summary="Tarjetas del cliente y su estado")
    def obtener_tarjetas(cliente: Cliente = Depends(cliente_actual)):
        return [presentadores.tarjeta(t) for t in tarjetas(cliente)]

    @router.post(
        "/bizum", response_model=esquemas.BizumPendienteOut, summary="Iniciar un Bizum (pendiente de código OTP)",
        description=(
            "**No mueve dinero.** Valida el importe, el contacto, el saldo y el tope diario, crea una operación "
            "pendiente y envía un código de 6 dígitos al móvil simulado (`GET /movil/mensajes`). Para ejecutarla "
            "hay que llamar a `POST /operaciones/{id}/confirmar` con ese código."
        ),
        responses={
            **esquemas.VALIDACION, **esquemas.NO_ENCONTRADO,
            409: {"model": esquemas.ErrorOut, "description": "Saldo insuficiente o tope diario superado."},
        },
    )
    def solicitar_bizum(peticion: esquemas.PeticionBizum, cliente: Cliente = Depends(cliente_actual)):
        operacion = bizum(cliente, peticion.destinatario, peticion.importe, peticion.concepto)
        return {"ok": True, "estado": "pendiente_de_confirmacion", "operacion": presentadores.operacion_pendiente(operacion)}

    @router.get(
        "/movimientos", response_model=esquemas.ConsultaOut, summary="Últimos movimientos",
        description="Más recientes primero. Máximo 60 filas.",
    )
    def obtener_movimientos(
        limite: int = Query(50, ge=1, le=60, description="Cuántos movimientos devolver."),
        cliente: Cliente = Depends(cliente_actual),
    ):
        return presentadores.resultado_consulta(movimientos.ultimos(cliente, limite))

    return router
