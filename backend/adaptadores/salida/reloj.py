"""Reloj del sistema."""
from datetime import date


class RelojSistema:
    def hoy(self) -> date:
        return date.today()
