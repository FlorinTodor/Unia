"""Adaptador de SondaProveedores: validar claves, listar modelos y comprobar Ollama."""
import httpx
from openai import APIConnectionError, APIStatusError, AuthenticationError, PermissionDeniedError

from ....aplicacion.puertos.infraestructura import ClaveRechazada, EstadoOllama, ListadoNoSoportado, SinConexion
from .clientes import FabricaClientes

# fragmentos de id de modelos que no sirven para chatear (voz, imagen, embeddings...)
_NO_CHAT = (
    "whisper", "tts", "transcribe", "audio", "realtime", "embed", "moderation", "guard",
    "dall-e", "image", "imagen", "veo", "aqa", "davinci", "babbage", "search", "playai",
    "orpheus", "distil", "ocr",
)


class SondaOpenAI:
    def __init__(self, clientes: FabricaClientes):
        self._clientes = clientes

    def listar_modelos(self, proveedor: str, api_key: str | None = None) -> list[str]:
        try:
            modelos = self._clientes.cliente(proveedor, api_key, timeout=10).models.list()
        except (AuthenticationError, PermissionDeniedError) as e:
            raise ClaveRechazada(str(e)) from e
        except APIConnectionError as e:
            raise SinConexion(str(e)) from e
        except APIStatusError as e:
            if e.status_code == 400:  # Gemini responde 400 «API key not valid»
                raise ClaveRechazada(str(e)) from e
            raise ListadoNoSoportado(str(e)) from e
        ids = {m.id.removeprefix("models/") for m in modelos.data}  # Gemini antepone "models/"
        return sorted(i for i in ids if not any(x in i.lower() for x in _NO_CHAT))

    def estado_ollama(self, url: str) -> EstadoOllama:
        base = url.rstrip("/").removesuffix("/v1")
        try:
            r = httpx.get(f"{base}/api/tags", timeout=3, follow_redirects=False)
            r.raise_for_status()
            modelos = sorted(m["name"] for m in r.json().get("models", []))
        except httpx.HTTPError:
            return EstadoOllama(False, "Ollama no responde. Arráncalo con «ollama serve».", [])
        except (ValueError, KeyError, TypeError, AttributeError):  # respuesta que no es el JSON de Ollama
            return EstadoOllama(False, "Ollama respondió algo inesperado.", [])
        if not modelos:
            return EstadoOllama(True, "Ollama funciona, pero no tiene modelos: «ollama pull qwen3:8b».", [])
        return EstadoOllama(True, f"Ollama en marcha · {len(modelos)} modelos instalados.", modelos)
