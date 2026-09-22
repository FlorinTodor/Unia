"""Configuración y selección de proveedor LLM.

Todos los proveedores exponen API compatible con OpenAI, por lo que basta
con cambiar base_url + api_key + modelo para alternar entre ellos.

Los valores se leen de `ajustes.cargar()` en cada llamada: lo que el usuario
cambia en el panel ⚙️ se aplica al siguiente mensaje, sin reiniciar.
"""
import os

from openai import OpenAI

from . import ajustes

# Proveedores en la nube que se pueden configurar desde el panel ⚙️.
# `modelos` son sugerencias iniciales; al validar la clave se sustituyen por
# la lista real que devuelve el proveedor.
CATALOGO = {
    "groq": {
        "nombre": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "url_claves": "https://console.groq.com/keys",
        "prefijo": "gsk_...",
        "nota": "Gratis y el más rápido. Recomendado: también activa la voz (Whisper).",
        # Llama 3.3 70B fue retirado de Groq en 2026; límite: 8.000 tokens/min POR MODELO
        "modelo": "openai/gpt-oss-120b",
        "modelo_respaldo": "openai/gpt-oss-20b",
    },
    "gemini": {
        "nombre": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "url_claves": "https://aistudio.google.com/apikey",
        "prefijo": "AIza...",
        "nota": "Capa gratuita con límites diarios bajos en los modelos grandes.",
        "modelo": "gemini-2.5-flash",
        "modelo_respaldo": "gemini-2.5-flash-lite",
    },
    "openai": {
        "nombre": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "url_claves": "https://platform.openai.com/api-keys",
        "prefijo": "sk-...",
        "nota": "De pago. También activa la voz (Whisper).",
        "modelo": "gpt-4.1-mini",
        "modelo_respaldo": "gpt-4.1-nano",
    },
    "anthropic": {
        "nombre": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com/v1/",
        "url_claves": "https://console.anthropic.com/settings/keys",
        "prefijo": "sk-ant-...",
        "nota": "De pago.",
        "modelo": "claude-haiku-4-5",
        "modelo_respaldo": "claude-sonnet-5",
    },
    "mistral": {
        "nombre": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "url_claves": "https://console.mistral.ai/api-keys",
        "prefijo": "",
        "nota": "Plan gratuito «Experiment» con límites por minuto.",
        "modelo": "mistral-small-latest",
        "modelo_respaldo": "mistral-medium-latest",
    },
    "openrouter": {
        "nombre": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "url_claves": "https://openrouter.ai/keys",
        "prefijo": "sk-or-...",
        "nota": "Muchos modelos con una sola clave; los «:free» tienen 50 peticiones/día.",
        "modelo": "meta-llama/llama-3.3-70b-instruct:free",
        "modelo_respaldo": "openai/gpt-oss-120b:free",
    },
    "cerebras": {
        "nombre": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "url_claves": "https://cloud.cerebras.ai",
        "prefijo": "csk-...",
        "nota": "Muy rápido; la API requiere tener la facturación activada.",
        "modelo": "gpt-oss-120b",
        "modelo_respaldo": "llama-3.3-70b",
    },
}

# proveedores con Whisper, en orden de preferencia: (proveedor, modelo)
PROVEEDORES_STT = (
    ("groq", os.getenv("MODELO_STT", "whisper-large-v3-turbo")),
    ("openai", "whisper-1"),
)


def cliente_para(proveedor: str, api_key: str | None = None, timeout: float | None = None) -> OpenAI:
    """Cliente OpenAI-compatible para un proveedor.

    max_retries=0: ante un 429 preferimos caer al siguiente eslabón de la
    cadena al instante en lugar de esperar reintentos con backoff.
    """
    a = ajustes.cargar()
    if proveedor == "ollama":
        return OpenAI(base_url=a["ollama_url"], api_key="ollama", max_retries=0)  # no valida la clave
    clave = api_key or a["claves"].get(proveedor, {}).get("api_key") or "sin-clave"
    extra = {"timeout": timeout} if timeout else {}
    if proveedor == "anthropic":
        # su capa compatible acepta Bearer en el chat, pero /models exige x-api-key
        extra["default_headers"] = {"x-api-key": clave, "anthropic-version": "2023-06-01"}
    return OpenAI(base_url=CATALOGO[proveedor]["base_url"], api_key=clave, max_retries=0, **extra)


def cadena_llm() -> list[tuple[str, str]]:
    """Cadena de fallback [(proveedor, modelo), ...] en orden de preferencia.

    Clave activa (principal → respaldo) → resto de claves → Ollama local.
    En los proveedores gratuitos los límites de tokens/día son POR MODELO,
    así que el modelo de respaldo de la misma clave es un fallback real.
    Con la IA local activa no se usa la nube: el usuario la eligió por privacidad.
    """
    a = ajustes.cargar()
    if a["activo"] == "ollama":
        return [("ollama", a["ollama_modelo"])]
    orden = sorted(a["claves"], key=lambda p: p != a["activo"])  # la activa primero
    cadena = []
    for proveedor in orden:
        cfg = a["claves"][proveedor]
        for modelo in (cfg.get("modelo"), cfg.get("modelo_respaldo")):
            if modelo and (proveedor, modelo) not in cadena:
                cadena.append((proveedor, modelo))
    if a["fallback_local"]:
        cadena.append(("ollama", a["ollama_modelo"]))
    return cadena


def get_cliente_stt() -> tuple[OpenAI, str] | None:
    """Whisper con la primera clave que lo ofrezca (Groq gratis, u OpenAI)."""
    claves = ajustes.cargar()["claves"]
    for proveedor, modelo in PROVEEDORES_STT:
        if proveedor in claves:
            return cliente_para(proveedor), modelo
    return None
