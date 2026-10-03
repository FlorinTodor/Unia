"""Fábrica de clientes OpenAI-compatible: todos los proveedores comparten API, solo cambia la URL."""
from openai import OpenAI

from ....aplicacion.puertos.infraestructura import RepositorioAjustes
from ....dominio.proveedores import OLLAMA

BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1/",
    "mistral": "https://api.mistral.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "cerebras": "https://api.cerebras.ai/v1",
}


class FabricaClientes:
    """Crea un cliente por llamada leyendo los ajustes en ese momento (cambios en caliente)."""

    def __init__(self, ajustes: RepositorioAjustes):
        self._ajustes = ajustes

    def cliente(self, proveedor: str, api_key: str | None = None, timeout: float | None = None) -> OpenAI:
        """max_retries=0: ante un 429 preferimos caer al siguiente eslabón de la cadena
        al instante en lugar de esperar reintentos con backoff."""
        ajustes = self._ajustes.cargar()
        if proveedor == OLLAMA:
            return OpenAI(base_url=ajustes.ollama_url, api_key="ollama", max_retries=0)  # no valida la clave
        configurada = ajustes.claves.get(proveedor)
        clave = api_key or (configurada.api_key if configurada else None) or "sin-clave"
        extra: dict = {"timeout": timeout} if timeout else {}
        if proveedor == "anthropic":
            # su capa compatible acepta Bearer en el chat, pero /models exige x-api-key
            extra["default_headers"] = {"x-api-key": clave, "anthropic-version": "2023-06-01"}
        return OpenAI(base_url=BASE_URLS[proveedor], api_key=clave, max_retries=0, **extra)
