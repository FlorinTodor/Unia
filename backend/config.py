"""Configuración y selección de proveedor LLM.

Todos los proveedores exponen API compatible con OpenAI, por lo que basta
con cambiar base_url + api_key + modelo para alternar entre ellos.
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PROVEEDORES = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": os.getenv("GROQ_API_KEY", ""),
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "api_key": os.getenv("CEREBRAS_API_KEY", ""),
        "model": os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"),
    },
    "ollama": {
        "base_url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
        "api_key": "ollama",  # Ollama no valida la clave
        "model": os.getenv("OLLAMA_MODEL", "qwen3:8b"),
    },
}

PROVEEDOR_ACTIVO = os.getenv("LLM_PROVIDER", "groq")

MODELO_STT = os.getenv("MODELO_STT", "whisper-large-v3-turbo")


def cliente_para(proveedor: str) -> OpenAI:
    """Cliente OpenAI-compatible para un proveedor.

    max_retries=0: ante un 429 preferimos caer al siguiente eslabón de la
    cadena al instante en lugar de esperar reintentos con backoff.
    """
    cfg = PROVEEDORES[proveedor]
    return OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"] or "sin-clave", max_retries=0)


def get_cliente_llm(proveedor: str | None = None) -> tuple[OpenAI, str]:
    """Devuelve (cliente, nombre_modelo) del proveedor indicado (o el activo)."""
    nombre = proveedor or PROVEEDOR_ACTIVO
    return cliente_para(nombre), PROVEEDORES[nombre]["model"]


def cadena_llm() -> list[tuple[str, str]]:
    """Cadena de fallback [(proveedor, modelo), ...] en orden de preferencia.

    En Groq los límites de tokens/día son POR MODELO, así que un segundo
    modelo del mismo proveedor es un fallback real con cuota independiente.
    """
    cadena = [(PROVEEDOR_ACTIVO, PROVEEDORES[PROVEEDOR_ACTIVO]["model"])]
    if PROVEEDOR_ACTIVO == "groq":
        cadena.append(("groq", os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-120b")))
    if PROVEEDOR_ACTIVO != "cerebras" and PROVEEDORES["cerebras"]["api_key"]:
        cadena.append(("cerebras", PROVEEDORES["cerebras"]["model"]))
    if PROVEEDOR_ACTIVO != "ollama":
        cadena.append(("ollama", PROVEEDORES["ollama"]["model"]))
    return cadena


def get_cliente_stt() -> OpenAI | None:
    """Whisper se sirve siempre desde Groq (gratuito con la misma clave)."""
    clave = os.getenv("GROQ_API_KEY", "")
    if not clave:
        return None
    return OpenAI(base_url=PROVEEDORES["groq"]["base_url"], api_key=clave)
