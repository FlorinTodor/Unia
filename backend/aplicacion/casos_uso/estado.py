"""Caso de uso: estado general del sistema para la cabecera de la interfaz."""
from dataclasses import dataclass

from ...dominio.proveedores import ModeloRef
from ..puertos.infraestructura import RepositorioAjustes
from ..puertos.voz import Sintetizador


@dataclass(frozen=True)
class EstadoSistema:
    cadena: list[ModeloRef]
    configurado: bool
    voz_entrada: bool
    voz_servidor: bool

    @property
    def principal(self) -> ModeloRef | None:
        return self.cadena[0] if self.cadena else None


class ConsultarEstado:
    def __init__(self, ajustes: RepositorioAjustes, sintetizador: Sintetizador):
        self._ajustes = ajustes
        self._sintetizador = sintetizador

    def __call__(self) -> EstadoSistema:
        ajustes = self._ajustes.cargar()
        return EstadoSistema(
            cadena=ajustes.cadena_llm(),
            configurado=ajustes.configurado,
            voz_entrada=ajustes.transcripcion() is not None,
            voz_servidor=self._sintetizador.disponible(),
        )
