"""Caso de uso: preparar un gráfico que el LLM ha diseñado (sin plantillas)."""
import json

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
