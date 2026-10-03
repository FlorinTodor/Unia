"""Puertos de voz: transcribir (voz → texto) y sintetizar (texto → voz)."""
from typing import Protocol


class Transcriptor(Protocol):
    def transcribir(self, audio: bytes, nombre_fichero: str) -> str: ...


class Sintetizador(Protocol):
    def disponible(self) -> bool: ...

    def sintetizar(self, texto: str) -> bytes:
        """Devuelve audio WAV."""
        ...
