"""Estado de seguridad en memoria: intentos de login, operaciones pendientes y el móvil simulado."""
from ....dominio.acceso import EstadoIntentos
from ....dominio.operaciones import OperacionPendiente
from ....aplicacion.puertos.infraestructura import Reloj


class IntentosEnMemoria:
    def __init__(self):
        self._estados: dict[str, EstadoIntentos] = {}

    def obtener(self, usuario: str) -> EstadoIntentos:
        return self._estados.get(usuario, EstadoIntentos())

    def guardar(self, usuario: str, estado: EstadoIntentos) -> None:
        self._estados[usuario] = estado


class OperacionesEnMemoria:
    def __init__(self):
        self._operaciones: dict[str, OperacionPendiente] = {}

    def guardar(self, operacion: OperacionPendiente) -> None:
        self._operaciones[operacion.id] = operacion

    def obtener(self, id_operacion: str) -> OperacionPendiente | None:
        return self._operaciones.get(id_operacion)


class MovilSimulado:
    """El «teléfono» del cliente: recibe los SMS con el OTP. Es un canal aparte del chat."""

    def __init__(self, reloj: Reloj):
        self._reloj = reloj
        self._bandejas: dict[int, list[dict]] = {}

    def enviar(self, cliente_id: int, texto: str) -> None:
        self._bandejas.setdefault(cliente_id, []).append(
            {"remitente": "Unicaja", "texto": texto, "hora": self._reloj.ahora().strftime("%H:%M")}
        )

    def mensajes(self, cliente_id: int) -> list[dict]:
        return list(reversed(self._bandejas.get(cliente_id, [])[-10:]))
