"""Adaptador Sintetizador compuesto: una voz principal y otra de reserva si la principal falla o no está."""
import logging

log = logging.getLogger(__name__)


class SintetizadorConReserva:
    """Habla con la principal (OmniVoice); si no está instalada, no hay GPU o falla una frase, usa la reserva (Piper)."""

    def __init__(self, principal, reserva):
        self._principal = principal
        self._reserva = reserva

    def disponible(self) -> bool:
        return self._principal.disponible() or self._reserva.disponible()

    def precargar(self) -> None:
        if self._principal.disponible():
            try:
                self._principal.precargar()
                return
            except Exception:  # sin memoria de GPU, pesos corruptos…: la app arranca igual, con la reserva
                log.exception("No se pudo cargar la voz principal; se usará la de reserva")
        if self._reserva.disponible():
            self._reserva.precargar()

    def sintetizar(self, texto: str) -> bytes:
        if self._principal.disponible():
            try:
                return self._principal.sintetizar(texto)
            except Exception:
                log.exception("Falló la voz principal; se usa la de reserva")
        return self._reserva.sintetizar(texto)
