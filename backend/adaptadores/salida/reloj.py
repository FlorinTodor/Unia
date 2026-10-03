"""Reloj del sistema."""
from datetime import date, datetime


class RelojSistema:
    def hoy(self) -> date:
        return date.today()

    def ahora(self) -> datetime:
        return datetime.now()
