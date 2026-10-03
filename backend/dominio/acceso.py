"""Reglas de acceso: bloqueo temporal tras varios intentos fallidos."""
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_FALLOS = 5
MINUTOS_BLOQUEO = 5


@dataclass(frozen=True)
class EstadoIntentos:
    fallos: int = 0
    bloqueado_hasta: datetime | None = None

    def bloqueado(self, ahora: datetime) -> bool:
        return self.bloqueado_hasta is not None and ahora < self.bloqueado_hasta

    def minutos_restantes(self, ahora: datetime) -> int:
        if not self.bloqueado(ahora):
            return 0
        return max(1, -(-int((self.bloqueado_hasta - ahora).total_seconds()) // 60))  # redondeo hacia arriba

    def tras_fallo(self, ahora: datetime) -> "EstadoIntentos":
        fallos = self.fallos + 1
        if fallos >= MAX_FALLOS:
            return EstadoIntentos(0, ahora + timedelta(minutes=MINUTOS_BLOQUEO))
        return EstadoIntentos(fallos, self.bloqueado_hasta)
