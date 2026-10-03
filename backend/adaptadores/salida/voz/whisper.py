"""Adaptador Transcriptor: Whisper vía API OpenAI-compatible (Groq u OpenAI)."""
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)

from ....aplicacion.puertos.infraestructura import RepositorioAjustes
from ....dominio.errores import ErrorLimiteExcedido, ErrorNoDisponible, ErrorProveedorExterno, ErrorTiempoAgotado
from ..llm.clientes import FabricaClientes


class TranscriptorWhisper:
    def __init__(self, ajustes: RepositorioAjustes, clientes: FabricaClientes):
        self._ajustes = ajustes
        self._clientes = clientes

    def transcribir(self, audio: bytes, nombre_fichero: str) -> str:
        eslabon = self._ajustes.cargar().transcripcion()
        if eslabon is None:
            raise ErrorNoDisponible("No hay ninguna clave con voz (Groq u OpenAI).")
        try:
            transcripcion = self._clientes.cliente(eslabon.proveedor).audio.transcriptions.create(
                model=eslabon.modelo,
                file=(nombre_fichero, audio),
                language="es",
                temperature=0.0,
                # sesga la transcripción hacia el dominio de la app y reduce alucinaciones
                prompt="Consulta a un asistente bancario en español: saldo, movimientos, gastos, Bizum, gráficos.",
            )
        except (AuthenticationError, PermissionDeniedError) as e:
            raise ErrorNoDisponible("La clave de voz no es válida: revísala en ⚙️ Ajustes.") from e
        except RateLimitError as e:
            raise ErrorLimiteExcedido("El servicio de voz ha alcanzado su límite. Prueba en unos segundos.", reintentar_en=15) from e
        except APITimeoutError as e:
            raise ErrorTiempoAgotado("El servicio de voz no ha respondido a tiempo. Inténtalo de nuevo.") from e
        except (APIConnectionError, APIError) as e:
            raise ErrorProveedorExterno("El servicio de voz no está disponible ahora mismo.") from e
        return transcripcion.text
