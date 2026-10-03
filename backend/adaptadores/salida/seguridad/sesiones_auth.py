"""Sesiones autenticadas en memoria. El token es opaco y aleatorio; solo se guarda su huella."""
import hashlib
import secrets
from datetime import timedelta

from ....aplicacion.puertos.infraestructura import Reloj

HORAS_SESION = 8


def _huella(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SesionesAutenticadasEnMemoria:
    def __init__(self, reloj: Reloj):
        self._reloj = reloj
        self._sesiones: dict[str, tuple[int, object]] = {}

    def crear(self, cliente_id: int) -> str:
        token = secrets.token_urlsafe(32)
        self._sesiones[_huella(token)] = (cliente_id, self._reloj.ahora() + timedelta(hours=HORAS_SESION))
        return token

    def cliente_de(self, token: str) -> int | None:
        entrada = self._sesiones.get(_huella(token))
        if entrada is None:
            return None
        cliente_id, caduca = entrada
        if self._reloj.ahora() >= caduca:
            self._sesiones.pop(_huella(token), None)
            return None
        return cliente_id

    def cerrar(self, token: str) -> None:
        self._sesiones.pop(_huella(token), None)
