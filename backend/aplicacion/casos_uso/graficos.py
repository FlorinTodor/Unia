"""Caso de uso: preparar un gráfico que el LLM ha diseñado (sin plantillas)."""
import json
import re

from ...dominio.errores import ErrorDeValidacion
from ..eventos import Grafico


def preparar_grafico(titulo: str, config: object) -> Grafico:
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            raise ErrorDeValidacion("config no es JSON válido") from None
    if not isinstance(config, dict) or "type" not in config or "data" not in config:
        raise ErrorDeValidacion("config debe incluir 'type' y 'data'")
    return Grafico(titulo or "Gráfico", config)


_RE_BLOQUE_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extraer_grafico_del_texto(texto: str) -> tuple[str, Grafico | None]:
    """Red de seguridad: a veces el modelo escribe la config Chart.js como bloque ```json en la
    respuesta en vez de llamar a `generar_grafico`. Si el bloque es una config válida se
    convierte en gráfico y se quita del texto; si no, el texto queda intacto."""
    for m in _RE_BLOQUE_JSON.finditer(texto):
        try:
            config = json.loads(m.group(1))
            grafico = preparar_grafico(_titulo(config), config)
        except (json.JSONDecodeError, ErrorDeValidacion):
            continue
        limpio = (texto[: m.start()] + texto[m.end():]).strip()
        return limpio, grafico
    return texto, None


def _titulo(config: dict) -> str:
    titulo = config.get("options", {}).get("plugins", {}).get("title", {}).get("text") if isinstance(config, dict) else None
    return titulo if isinstance(titulo, str) and titulo else "Gráfico"
