"""Ajustes editables desde la interfaz (panel ⚙️): claves API, modelos y IA local.

Se guardan en `data/ajustes.json` (gitignored, permisos 600) y se aplican en
caliente, sin reiniciar el servidor. Si el fichero no existe se parte del
`.env`, así que una instalación configurada solo con variables sigue igual.

Estructura:
    activo          id del proveedor en uso ("groq", "openai"... u "ollama"); None = sin configurar
    claves          {proveedor: {api_key, modelo, modelo_respaldo, modelos}}
    ollama_url, ollama_modelo
    fallback_local  usar Ollama como último eslabón si fallan las claves
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RUTA_AJUSTES = Path(__file__).resolve().parent.parent / "data" / "ajustes.json"


def _desde_entorno() -> dict:
    claves = {}
    if os.getenv("GROQ_API_KEY"):
        claves["groq"] = {
            "api_key": os.getenv("GROQ_API_KEY"),
            "modelo": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "modelo_respaldo": os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b"),
            "modelos": [],
        }
    if os.getenv("LLM_PROVIDER") == "ollama":
        activo = "ollama"
    else:
        activo = next(iter(claves), None)
    return {
        "activo": activo,
        "claves": claves,
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
        "ollama_modelo": os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        "fallback_local": True,
    }


def cargar() -> dict:
    if RUTA_AJUSTES.exists():
        try:
            return {**_desde_entorno(), **json.loads(RUTA_AJUSTES.read_text(encoding="utf-8"))}
        except (OSError, json.JSONDecodeError):
            pass  # fichero corrupto: se ignora y se usan los valores del entorno
    return _desde_entorno()


def guardar(ajustes: dict) -> None:
    RUTA_AJUSTES.parent.mkdir(parents=True, exist_ok=True)
    RUTA_AJUSTES.write_text(json.dumps(ajustes, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        RUTA_AJUSTES.chmod(0o600)  # contiene claves API
    except OSError:
        pass


def enmascarar(clave: str) -> str:
    return "••••" + clave[-4:] if len(clave) > 8 else "••••"
