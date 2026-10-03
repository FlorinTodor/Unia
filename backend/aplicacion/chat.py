"""Servicio de chat: sesiones, compactación del historial y un turno de conversación."""
import logging
from collections.abc import Iterator
from dataclasses import replace

from ..dominio.errores import ErrorDeDominio
from ..dominio.modelos import Mensaje
from .agente import Agente
from .casos_uso.banco import ConsultarSaldo
from .eventos import Aviso, Delta, ErrorChat, EventoChat, Fin
from .prompt import construir_system_prompt
from .puertos.infraestructura import Reloj, RepositorioSesiones
from .texto import limpiar_invisibles

MAX_MENSAJES_HISTORIAL = 40

log = logging.getLogger(__name__)


def compactar_historial(mensajes: list[Mensaje]) -> list[Mensaje]:
    """Elimina el tráfico de herramientas (resultados SQL, configs de gráficos) de los
    turnos anteriores al último, dejando solo el texto conversacional.

    Sin esto, cada petición reenvía miles de tokens de historial y agota el límite de
    tokens/minuto del proveedor (429 → reintentos → latencia).
    """
    ultimo_turno = max((i for i, m in enumerate(mensajes) if m.rol == "user"), default=len(mensajes))
    compactados = []
    for i, m in enumerate(mensajes):
        if i >= ultimo_turno or m.rol in ("system", "user"):
            compactados.append(m)
        elif m.rol == "assistant" and m.contenido:
            compactados.append(Mensaje.asistente(m.contenido))
        # tool y assistant sin texto (solo llamadas) se descartan
    return compactados


def _recortar(mensajes: list[Mensaje]) -> list[Mensaje]:
    """Limita el historial conservando el system prompt."""
    if len(mensajes) <= MAX_MENSAJES_HISTORIAL:
        return mensajes
    return mensajes[:1] + mensajes[len(mensajes) - MAX_MENSAJES_HISTORIAL + 1:]


class ServicioChat:
    def __init__(self, agente: Agente, sesiones: RepositorioSesiones, saldo: ConsultarSaldo, reloj: Reloj):
        self._agente = agente
        self._sesiones = sesiones
        self._saldo = saldo
        self._reloj = reloj

    def enviar(self, id_sesion: str, texto: str) -> Iterator[EventoChat]:
        mensajes = self._sesiones.obtener(id_sesion)
        if mensajes is None:
            prompt = construir_system_prompt(self._reloj.hoy(), self._saldo().titular)
            mensajes = [Mensaje.sistema(prompt)]
        mensajes = _recortar(compactar_historial(mensajes))
        mensajes.append(Mensaje.usuario(texto))

        try:
            for evento in self._agente.responder(mensajes):
                yield self._sanear(evento)
        except ErrorDeDominio as e:
            yield ErrorChat(e.mensaje)
        except Exception:  # noqa: BLE001 — el cliente recibe un mensaje genérico; el detalle va al log
            log.exception("Error inesperado en el turno de chat")
            yield ErrorChat("Ha ocurrido un error inesperado. Inténtalo de nuevo en unos segundos.")
        finally:
            self._sesiones.guardar(id_sesion, mensajes)

    @staticmethod
    def _sanear(evento: EventoChat) -> EventoChat:
        # los modelos a veces cuelan caracteres invisibles (p. ej. "202​​2026")
        if isinstance(evento, (Delta, Fin)):
            return replace(evento, texto=limpiar_invisibles(evento.texto))
        if isinstance(evento, Aviso):
            return replace(evento, texto=limpiar_invisibles(evento.texto))
        return evento
