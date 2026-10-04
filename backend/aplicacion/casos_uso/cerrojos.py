"""Cerrojo por cliente compartido por confirmar, cancelar y bloquear."""
import threading


class CerrojosPorCliente:
    """Un cerrojo por cliente para serializar las operaciones que cambian el estado de sus Bizum y de sus tarjetas.

    Confirmar, cancelar y bloquear una tarjeta DEBEN compartir la MISMA instancia (si no, una cancelación pisaba una confirmación en curso y el
    dinero salía con la operación marcada como cancelada): por eso es un parámetro obligatorio y lo crea
    `composicion.py` una sola vez, sin instancia global escondida.
    """

    def __init__(self):
        self._cerrojos: dict[int, threading.Lock] = {}
        self._guarda = threading.Lock()

    def de(self, cliente_id: int) -> threading.Lock:
        with self._guarda:
            return self._cerrojos.setdefault(cliente_id, threading.Lock())
