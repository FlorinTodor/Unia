"""Puertos del control de uso: contabilidad de tokens y limitador de peticiones."""
from datetime import date, datetime
from typing import Protocol

from ...dominio.uso import Uso


class RegistroUso(Protocol):
    def registrar(self, cliente_id: int, proveedor: str, modelo: str, uso: Uso, momento: datetime) -> None: ...

    def tokens_del_dia(self, cliente_id: int, dia: date) -> int:
        """Tokens de modelos en la nube; los del modelo local (Ollama) son gratis y no cuentan."""
        ...

    def tokens_locales_del_dia(self, cliente_id: int, dia: date) -> int:
        """Tokens del modelo local (Ollama): no cuentan para el límite de la nube, pero tienen su propio tope."""
        ...

    def ultimos(self, cliente_id: int, limite: int = 10) -> list[dict]: ...

    def reiniciar_dia(self, cliente_id: int, dia: date) -> int:
        """Borra el gasto de ese día (solo para pruebas y demos). Devuelve los tokens liberados."""
        ...


class LimitadorPeticiones(Protocol):
    def permitir(self, cliente_id: int, ahora: datetime) -> int | None:
        """Cuenta la petición y devuelve None si pasa, o los segundos de espera si se excede el límite."""
        ...
