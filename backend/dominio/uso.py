"""Control del gasto de tokens de la IA: medición, presupuestos y reglas de límite."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .errores import ErrorDeValidacion, LimiteDeTokensExcedido, MensajeDemasiadoLargo


@dataclass(frozen=True)
class Uso:
    """Tokens consumidos en una llamada al modelo."""

    entrada: int = 0
    salida: int = 0
    estimado: bool = False  # True si el proveedor no informó y se calculó a partir del texto

    @property
    def total(self) -> int:
        return self.entrada + self.salida

    def __add__(self, otro: "Uso") -> "Uso":
        return Uso(self.entrada + otro.entrada, self.salida + otro.salida, self.estimado or otro.estimado)


@dataclass(frozen=True)
class PresupuestoUso:
    """Límites de uso de la IA. Los valores por defecto caben en el plan gratuito de Groq."""

    tokens_por_dia: int = 80_000  # por cliente
    tokens_por_turno: int = 30_000  # una pregunta, con todas sus rondas de herramientas
    max_caracteres_mensaje: int = 1_500
    max_tokens_respuesta: int = 4_096  # tope de salida por llamada (incluye el razonamiento de gpt-oss)
    peticiones_por_minuto: int = 20  # por cliente
    max_tokens_historial: int = 3_000  # lo que se reenvía de la conversación anterior
    max_caracteres_resultado: int = 6_000  # un resultado SQL no ocupa más que esto en el contexto


def estimar_tokens(texto: str) -> int:
    """Aproximación para el español: ~3,3 caracteres por token. Solo se usa si el proveedor no informa."""
    return -(-len(texto) * 10 // 33)


def validar_mensaje(texto: str, presupuesto: PresupuestoUso) -> str:
    texto = texto.strip()
    if not texto:
        raise ErrorDeValidacion("Escribe un mensaje.")
    if len(texto) > presupuesto.max_caracteres_mensaje:
        raise MensajeDemasiadoLargo(
            f"El mensaje es demasiado largo ({len(texto)} caracteres; máximo {presupuesto.max_caracteres_mensaje}). Resúmelo."
        )
    return texto


def segundos_hasta_medianoche(ahora: datetime) -> int:
    manana = (ahora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((manana - ahora).total_seconds()))


def comprobar_cuota_diaria(tokens_hoy: int, presupuesto: PresupuestoUso, ahora: datetime) -> None:
    if tokens_hoy >= presupuesto.tokens_por_dia:
        raise LimiteDeTokensExcedido(
            f"Has agotado tu uso diario del asistente ({presupuesto.tokens_por_dia:,} tokens). Se renueva a medianoche."
            .replace(",", "."),
            reintentar_en=segundos_hasta_medianoche(ahora),
        )
