"""Puertos de infraestructura general: sesiones, ajustes, reloj y sonda de proveedores."""
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from ...dominio.ajustes import Ajustes
from ...dominio.modelos import Mensaje


class RepositorioSesiones(Protocol):
    def obtener(self, id_sesion: str) -> list[Mensaje] | None: ...

    def guardar(self, id_sesion: str, mensajes: list[Mensaje]) -> None: ...


class RepositorioAjustes(Protocol):
    def cargar(self) -> Ajustes: ...

    def guardar(self, ajustes: Ajustes) -> None: ...


class Reloj(Protocol):
    def hoy(self) -> date: ...


# ------------------------------------------------------------------ sonda de proveedores

class ClaveRechazada(Exception):
    pass


class SinConexion(Exception):
    pass


class ListadoNoSoportado(Exception):
    """El proveedor no permite listar modelos: la clave se comprobará al chatear."""


@dataclass(frozen=True)
class EstadoOllama:
    ok: bool
    mensaje: str
    modelos: list[str]


class SondaProveedores(Protocol):
    def listar_modelos(self, proveedor: str, api_key: str | None = None) -> list[str]:
        """Modelos de chat de la cuenta. Sirve también para validar la clave (no gasta cuota).

        Lanza ClaveRechazada, SinConexion o ListadoNoSoportado.
        """
        ...

    def estado_ollama(self, url: str) -> EstadoOllama: ...
