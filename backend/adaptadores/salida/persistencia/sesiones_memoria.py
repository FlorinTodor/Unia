"""Sesiones de chat en memoria (se pierden al reiniciar el servidor)."""
from ....dominio.modelos import Mensaje


class SesionesEnMemoria:
    def __init__(self):
        self._sesiones: dict[str, list[Mensaje]] = {}

    def obtener(self, id_sesion: str) -> list[Mensaje] | None:
        return self._sesiones.get(id_sesion)

    def guardar(self, id_sesion: str, mensajes: list[Mensaje]) -> None:
        self._sesiones[id_sesion] = mensajes
