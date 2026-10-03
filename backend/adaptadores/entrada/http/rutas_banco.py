"""API bancaria ficticia (REST): saldo, contactos, Bizum y movimientos."""
from fastapi import APIRouter
from pydantic import BaseModel

from ....aplicacion.casos_uso.banco import ConsultarMovimientos, ConsultarSaldo, EnviarBizum, ListarContactos
from ....dominio.errores import ErrorDeDominio
from . import presentadores


class PeticionBizum(BaseModel):
    destinatario: str
    importe: float
    concepto: str = ""


def crear_router(
    saldo: ConsultarSaldo, contactos: ListarContactos, bizum: EnviarBizum, movimientos: ConsultarMovimientos
) -> APIRouter:
    router = APIRouter(prefix="/api/banco", tags=["banco"])

    @router.get("/saldo")
    def obtener_saldo():
        return presentadores.cuenta(saldo())

    @router.get("/contactos")
    def obtener_contactos():
        return [{"nombre": c.nombre, "telefono": c.telefono} for c in contactos()]

    @router.post("/bizum")
    def enviar_bizum(peticion: PeticionBizum):
        try:
            return presentadores.comprobante_bizum(bizum(peticion.destinatario, peticion.importe, peticion.concepto))
        except ErrorDeDominio as e:  # los rechazos de negocio son una respuesta válida, no un fallo HTTP
            return {"ok": False, "error": e.mensaje, **e.datos}

    @router.get("/movimientos")
    def obtener_movimientos(limite: int = 50):
        return presentadores.resultado_consulta(movimientos.ultimos(limite))

    return router
