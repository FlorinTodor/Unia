"""Protocolo SSE del chat: traduce los eventos de la aplicación a `data: {tipo, dato}`."""
import json

from ....aplicacion.eventos import (
    Aviso,
    Delta,
    ErrorChat,
    EventoChat,
    Fin,
    Grafico,
    HerramientaEnUso,
    OperacionPorConfirmar,
    UsoConsumido,
)


def a_dict(evento: EventoChat) -> dict:
    if isinstance(evento, Delta):
        return {"tipo": "delta", "dato": evento.texto}
    if isinstance(evento, HerramientaEnUso):
        return {"tipo": "herramienta", "dato": evento.nombre, "etiqueta": evento.etiqueta}
    if isinstance(evento, Aviso):
        return {"tipo": "aviso", "dato": evento.texto}
    if isinstance(evento, Grafico):
        return {"tipo": "grafico", "dato": {"titulo": evento.titulo, "config": evento.config}}
    if isinstance(evento, OperacionPorConfirmar):
        return {
            "tipo": "operacion",
            "dato": {
                "id": evento.id, "destinatario": evento.destinatario, "importe": evento.importe,
                "concepto": evento.concepto, "alertas": list(evento.alertas), "caduca": evento.caduca,
            },
        }
    if isinstance(evento, UsoConsumido):
        return {
            "tipo": "uso",
            "dato": {"tokens_turno": evento.tokens_turno, "tokens_hoy": evento.tokens_hoy, "limite_dia": evento.limite_dia},
        }
    if isinstance(evento, Fin):
        return {"tipo": "fin", "dato": evento.texto}
    if isinstance(evento, ErrorChat):
        return {"tipo": "error", "dato": evento.mensaje}
    raise TypeError(f"Evento desconocido: {evento!r}")


def a_linea_sse(evento: EventoChat) -> str:
    return f"data: {json.dumps(a_dict(evento), ensure_ascii=False)}\n\n"
