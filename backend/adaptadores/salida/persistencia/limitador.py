"""Limitador de peticiones por cliente: ventana deslizante de un minuto, en memoria."""
from collections import defaultdict, deque
from datetime import datetime, timedelta


class LimitadorEnMemoria:
    def __init__(self, peticiones_por_minuto: int):
        self._max = peticiones_por_minuto
        self._marcas: dict[int, deque[datetime]] = defaultdict(deque)

    def permitir(self, cliente_id: int, ahora: datetime) -> int | None:
        marcas = self._marcas[cliente_id]
        while marcas and ahora - marcas[0] >= timedelta(minutes=1):
            marcas.popleft()
        if len(marcas) >= self._max:
            return max(1, int((marcas[0] + timedelta(minutes=1) - ahora).total_seconds()) + 1)
        marcas.append(ahora)
        return None
