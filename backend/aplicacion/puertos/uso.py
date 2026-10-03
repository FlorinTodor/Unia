"""Puertos del control de uso: contabilidad de tokens y limitador de peticiones."""
from datetime import date, datetime
from typing import Protocol

from ...dominio.uso import Uso


class RegistroUso(Protocol):
    def registrar(self, cliente_id: int, proveedor: str, modelo: str, uso: Uso, momento: datetime) -> None: ...

    def tokens_del_dia(self, cliente_id: int, dia: date) -> int:
        """Tokens de modelos en la nube; los del modelo local (Ollama) son gratis y no cuentan."""
        ...

    def ultimos(self, cliente_id: int, limite: int = 10) -> list[dict]: ...


class LimitadorPeticiones(Protocol):
    def permitir(self, cliente_id: int, ahora: datetime) -> int | None:
        """Cuenta la petición y devuelve None si pasa, o los segundos de espera si se excede el límite."""
        ...
