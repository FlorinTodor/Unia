"""Adaptador Transcriptor: Whisper vía API OpenAI-compatible (Groq u OpenAI)."""
from ....aplicacion.puertos.infraestructura import RepositorioAjustes
from ....dominio.errores import ErrorNoDisponible
from ..llm.clientes import FabricaClientes


class TranscriptorWhisper:
    def __init__(self, ajustes: RepositorioAjustes, clientes: FabricaClientes):
        self._ajustes = ajustes
        self._clientes = clientes

    def transcribir(self, audio: bytes, nombre_fichero: str) -> str:
        eslabon = self._ajustes.cargar().transcripcion()
        if eslabon is None:
            raise ErrorNoDisponible("No hay ninguna clave con voz (Groq u OpenAI).")
        transcripcion = self._clientes.cliente(eslabon.proveedor).audio.transcriptions.create(
            model=eslabon.modelo,
            file=(nombre_fichero, audio),
            language="es",
            temperature=0.0,
            # sesga la transcripción hacia el dominio de la app y reduce alucinaciones
            prompt="Consulta a un asistente bancario en español: saldo, movimientos, gastos, Bizum, gráficos.",
        )
        return transcripcion.text
