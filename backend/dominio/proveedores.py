"""Proveedores de IA soportados y su catálogo (datos de negocio, no de infraestructura).

Las URL base y los detalles de conexión viven en el adaptador `salida/llm`.
"""
from dataclasses import dataclass

OLLAMA = "ollama"


@dataclass(frozen=True)
class Proveedor:
    id: str
    nombre: str
    url_claves: str
    prefijo: str
    nota: str
    modelo: str
    modelo_respaldo: str


@dataclass(frozen=True)
class ModeloRef:
    """Un eslabón de la cadena de fallback: qué modelo de qué proveedor."""

    proveedor: str
    modelo: str


_PROVEEDORES = (
    Proveedor(
        "groq", "Groq", "https://console.groq.com/keys", "gsk_...",
        "Gratis y el más rápido. Recomendado: también activa la voz (Whisper).",
        # Llama 3.3 70B fue retirado de Groq en 2026; límite: 8.000 tokens/min POR MODELO
        "openai/gpt-oss-120b", "openai/gpt-oss-20b",
    ),
    Proveedor(
        "gemini", "Google Gemini", "https://aistudio.google.com/apikey", "AIza...",
        "Capa gratuita con límites diarios bajos en los modelos grandes.",
        "gemini-2.5-flash", "gemini-2.5-flash-lite",
    ),
    Proveedor(
        "openai", "OpenAI", "https://platform.openai.com/api-keys", "sk-...",
        "De pago. También activa la voz (Whisper).",
        "gpt-4.1-mini", "gpt-4.1-nano",
    ),
    Proveedor(
        "anthropic", "Anthropic (Claude)", "https://console.anthropic.com/settings/keys", "sk-ant-...",
        "De pago.",
        "claude-haiku-4-5", "claude-sonnet-5",
    ),
    Proveedor(
        "mistral", "Mistral AI", "https://console.mistral.ai/api-keys", "",
        "Plan gratuito «Experiment» con límites por minuto.",
        "mistral-small-latest", "mistral-medium-latest",
    ),
    Proveedor(
        "openrouter", "OpenRouter", "https://openrouter.ai/keys", "sk-or-...",
        "Muchos modelos con una sola clave; los «:free» tienen 50 peticiones/día.",
        "meta-llama/llama-3.3-70b-instruct:free", "openai/gpt-oss-120b:free",
    ),
    Proveedor(
        "cerebras", "Cerebras", "https://cloud.cerebras.ai", "csk-...",
        "Muy rápido; la API requiere tener la facturación activada.",
        "gpt-oss-120b", "llama-3.3-70b",
    ),
)

CATALOGO: dict[str, Proveedor] = {p.id: p for p in _PROVEEDORES}

# proveedores con Whisper, en orden de preferencia: (proveedor, modelo de transcripción)
PROVEEDORES_STT = (("groq", "whisper-large-v3-turbo"), ("openai", "whisper-1"))


def nombre_proveedor(proveedor: str) -> str:
    return CATALOGO[proveedor].nombre if proveedor in CATALOGO else "IA local"
