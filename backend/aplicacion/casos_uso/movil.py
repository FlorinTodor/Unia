"""El móvil simulado del cliente: donde llegan los códigos OTP (canal distinto al chat)."""
from ...dominio.modelos import Cliente
from ..puertos.seguridad import BandejaMovil


class LeerMensajesMovil:
    def __init__(self, bandeja: BandejaMovil):
        self._bandeja = bandeja

    def __call__(self, cliente: Cliente) -> list[dict]:
        return self._bandeja.mensajes(cliente.id)
