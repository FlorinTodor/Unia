"""API bancaria ficticia (REST).

Simula los servicios del banco que el asistente consume mediante sus
herramientas: saldo, transferencias Bizum, contactos y movimientos.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from . import db

router = APIRouter(prefix="/api/banco", tags=["banco"])


class PeticionBizum(BaseModel):
    destinatario: str
    importe: float
    concepto: str = ""


@router.get("/saldo")
def saldo():
    return db.obtener_saldo()


@router.get("/contactos")
def contactos():
    return db.listar_contactos()


@router.post("/bizum")
def bizum(peticion: PeticionBizum):
    return db.transferir_bizum(peticion.destinatario, peticion.importe, peticion.concepto)


@router.get("/movimientos")
def movimientos(limite: int = 50):
    return db.ejecutar_select(
        f"SELECT fecha, categoria, concepto, comercio, importe FROM movimientos ORDER BY fecha DESC LIMIT {int(limite)}"
    )
