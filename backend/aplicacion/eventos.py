"""Eventos que la aplicación emite durante un turno de chat (los adaptadores los traducen a SSE)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Delta:
    texto: str  # fragmento de la respuesta en streaming


@dataclass(frozen=True)
class HerramientaEnUso:
    nombre: str
    etiqueta: str  # texto legible: «Consultando saldo…»


@dataclass(frozen=True)
class Aviso:
    texto: str  # nota persistente (p. ej. cambio de proveedor)


@dataclass(frozen=True)
class Grafico:
    titulo: str
    config: dict  # configuración Chart.js completa


@dataclass(frozen=True)
class Fin:
    texto: str  # respuesta completa


@dataclass(frozen=True)
class ErrorChat:
    mensaje: str


EventoChat = Delta | HerramientaEnUso | Aviso | Grafico | Fin | ErrorChat
