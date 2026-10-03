"""Ajustes persistidos en `data/ajustes.json` (gitignored, permisos 600).

Si el fichero no existe se parte del `.env`, así que una instalación configurada solo
con variables de entorno sigue funcionando. Se aplican en caliente, sin reiniciar.
"""
import json
import os
from dataclasses import asdict
from pathlib import Path

from ....dominio.ajustes import Ajustes, ConfigClave
from ....dominio.proveedores import OLLAMA

RUTA_AJUSTES = Path(__file__).resolve().parents[4] / "data" / "ajustes.json"


class AjustesJson:
    def __init__(self, ruta: Path = RUTA_AJUSTES):
        self._ruta = ruta

    def cargar(self) -> Ajustes:
        datos = self._desde_entorno()
        if self._ruta.exists():
            try:
                datos.update(json.loads(self._ruta.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass  # fichero corrupto: se ignora y se usan los valores del entorno
        return Ajustes(
            activo=datos["activo"],
            claves={p: ConfigClave(**cfg) for p, cfg in datos["claves"].items()},
            ollama_url=datos["ollama_url"],
            ollama_modelo=datos["ollama_modelo"],
            fallback_local=datos["fallback_local"],
        )

    def guardar(self, ajustes: Ajustes) -> None:
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        self._ruta.write_text(json.dumps(asdict(ajustes), indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            self._ruta.chmod(0o600)  # contiene claves API
        except OSError:
            pass

    @staticmethod
    def _desde_entorno() -> dict:
        claves = {}
        if os.getenv("GROQ_API_KEY"):
            claves["groq"] = {
                "api_key": os.getenv("GROQ_API_KEY"),
                "modelo": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                "modelo_respaldo": os.getenv("GROQ_MODEL_FALLBACK", "openai/gpt-oss-20b"),
                "modelos": [],
            }
        activo = OLLAMA if os.getenv("LLM_PROVIDER") == OLLAMA else next(iter(claves), None)
        return {
            "activo": activo,
            "claves": claves,
            "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
            "ollama_modelo": os.getenv("OLLAMA_MODEL", "qwen3:8b"),
            "fallback_local": True,
        }
