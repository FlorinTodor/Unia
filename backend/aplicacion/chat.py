"""Servicio de chat: sesiones, compactación del historial y un turno de conversación."""
import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace

from ..dominio.errores import DemasiadasPeticiones, ErrorDeAccesoDenegado, ErrorDeDominio, TurnoEnCurso
from ..dominio.modelos import Cliente, Mensaje
from .agente import Agente
from .eventos import Aviso, Delta, ErrorChat, EventoChat, Fin, OperacionPorConfirmar
from .prompt import construir_system_prompt
from ..dominio.uso import MARCA_AUTOMATICA, PresupuestoUso, comprobar_cuota_diaria, estimar_tokens, validar_mensaje
from .puertos.infraestructura import Reloj, RepositorioSesiones
from .puertos.seguridad import RepositorioOperaciones
from .puertos.uso import LimitadorPeticiones, RegistroUso
from ..dominio.operaciones import EstadoOperacion
from ..dominio.reglas import euros
from .texto import limpiar_invisibles

MAX_MENSAJES_HISTORIAL = 40

log = logging.getLogger(__name__)


def compactar_historial(mensajes: list[Mensaje]) -> list[Mensaje]:
    """Elimina el tráfico de herramientas (resultados SQL, configs de gráficos) de los
    turnos anteriores al último, dejando solo el texto conversacional.

    Sin esto, cada petición reenvía miles de tokens de historial y agota el límite de
    tokens/minuto del proveedor (429 → reintentos → latencia).
    """
    def automatico(m: Mensaje) -> bool:
        return m.rol == "user" and (m.contenido or "").startswith(MARCA_AUTOMATICA)  # empujón interno del agente

    ultimo_turno = max(
        (i for i, m in enumerate(mensajes) if m.rol == "user" and not automatico(m)), default=len(mensajes)
    )
    compactados = []
    for i, m in enumerate(mensajes):
        if automatico(m) and i < ultimo_turno:
            continue  # el empujón de un turno viejo no es una pregunta del usuario: no se arrastra
        if i >= ultimo_turno or m.rol in ("system", "user"):
            compactados.append(m)
        elif m.rol == "assistant" and m.contenido:
            compactados.append(Mensaje.asistente(m.contenido))
        # tool y assistant sin texto (solo llamadas) se descartan
    return compactados


def _recortar(mensajes: list[Mensaje], max_tokens: int) -> list[Mensaje]:
    """Limita el historial conservando el system prompt y el último turno.

    Primero por número de mensajes y después por tokens estimados: lo que se reenvía de la
    conversación anterior se paga en cada petición.
    """
    if len(mensajes) > MAX_MENSAJES_HISTORIAL:
        mensajes = mensajes[:1] + mensajes[len(mensajes) - MAX_MENSAJES_HISTORIAL + 1:]
    ultimo_turno = max((i for i, m in enumerate(mensajes) if m.rol == "user"), default=len(mensajes))
    while ultimo_turno > 1 and sum(estimar_tokens(m.contenido or "") for m in mensajes[1:ultimo_turno]) > max_tokens:
        del mensajes[1]  # lo más antiguo primero
        ultimo_turno -= 1
    return mensajes


class _TurnoReservado:
    """Flujo de eventos de un turno que libera la reserva del cliente al terminar, fallar o descartarse.

    Un generador que nunca llega a arrancar (el cliente se desconecta antes del primer evento) no ejecuta su
    `finally`; por eso la liberación vive aquí y es idempotente (también en `close` y `__del__`).
    """

    def __init__(self, flujo: Iterator[EventoChat], liberar: Callable[[], None]):
        self._flujo = flujo
        self._liberar = liberar
        self._liberado = False

    def _soltar(self) -> None:
        if not self._liberado:
            self._liberado = True
            self._liberar()

    def __iter__(self):
        return self

    def __next__(self) -> EventoChat:
        try:
            return next(self._flujo)
        except BaseException:  # fin normal (StopIteration), error o cancelación: en todos se libera
            self._soltar()
            raise

    def close(self) -> None:
        try:
            self._flujo.close()
        finally:
            self._soltar()

    def __del__(self):
        self._soltar()


class ServicioChat:
    def __init__(
        self,
        agente: Agente,
        sesiones: RepositorioSesiones,
        reloj: Reloj,
        registro_uso: RegistroUso,
        limitador: LimitadorPeticiones,
        presupuesto: PresupuestoUso,
        operaciones: RepositorioOperaciones,
    ):
        self._agente = agente
        self._sesiones = sesiones
        self._reloj = reloj
        self._registro_uso = registro_uso
        self._limitador = limitador
        self._presupuesto = presupuesto
        self._operaciones = operaciones
        self._en_curso: set[int] = set()  # clientes con un turno respondiéndose: solo uno a la vez
        self._en_curso_guarda = threading.Lock()
        self._seguimiento: dict[str, list[str]] = {}  # sesión → operaciones por confirmar cuyo resultado aún no se ha contado

    def enviar(self, cliente: Cliente, id_sesion: str, texto: str) -> Iterator[EventoChat]:
        """Comprueba los límites de uso y devuelve el flujo de eventos del turno.

        Las comprobaciones se hacen AQUÍ (no dentro del generador) para que un rechazo llegue al cliente
        como un error HTTP con su código (413, 429...) antes de abrir el streaming.
        """
        if cliente.es_admin:
            raise ErrorDeAccesoDenegado("El perfil de administración no tiene cuenta: entra con un cliente para usar el chat.")
        texto = validar_mensaje(limpiar_invisibles(texto), self._presupuesto)  # sin invisibles que disfracen «[auto]»
        # Un solo turno a la vez por cliente: el gasto de tokens se anota al terminar, así que N peticiones en
        # paralelo pasaban todas la comprobación del tope diario antes de que ninguna lo gastara.
        with self._en_curso_guarda:
            if cliente.id in self._en_curso:
                raise TurnoEnCurso("Aún estoy respondiendo a tu pregunta anterior. Espera a que termine.", reintentar_en=2)
            self._en_curso.add(cliente.id)
        try:
            espera = self._limitador.permitir(cliente.id, self._reloj.ahora())
            if espera:
                raise DemasiadasPeticiones(f"Vas demasiado rápido. Espera {espera} s y vuelve a escribir.", reintentar_en=espera)
            if not self._agente.tiene_respaldo_local():  # con IA local el límite de la nube no bloquea: el agente la usa
                comprobar_cuota_diaria(
                    self._registro_uso.tokens_del_dia(cliente.id, self._reloj.hoy()), self._presupuesto, self._reloj.ahora()
                )
        except BaseException:
            self._liberar(cliente.id)
            raise
        return _TurnoReservado(self._turno(cliente, id_sesion, texto), lambda: self._liberar(cliente.id))

    def _liberar(self, cliente_id: int) -> None:
        # SIN cerrojo: se llama desde `__del__`, que el recolector puede disparar en un hilo que ya tiene el cerrojo
        # (un `threading.Lock` no es reentrante: interbloqueo). `set.discard` es atómico y no pisa a `add`/`in`.
        self._en_curso.discard(cliente_id)

    def _turno(self, cliente: Cliente, id_sesion: str, texto: str) -> Iterator[EventoChat]:
        # la sesión de chat pertenece al cliente autenticado: otro cliente no puede leerla aunque conozca el id
        clave = f"{cliente.id}:{id_sesion}"
        mensajes = self._sesiones.obtener(clave)
        if mensajes is None:
            mensajes = [Mensaje.sistema(construir_system_prompt(self._reloj.hoy(), cliente.nombre))]
        mensajes = _recortar(compactar_historial(mensajes), self._presupuesto.max_tokens_historial)
        mensajes.extend(self._avisos_de_operaciones(clave))
        mensajes.append(Mensaje.usuario(texto))

        try:
            for evento in self._agente.responder(mensajes, cliente):
                if isinstance(evento, OperacionPorConfirmar):
                    self._seguimiento.setdefault(clave, []).append(evento.id)
                yield self._sanear(evento)
        except ErrorDeDominio as e:
            yield ErrorChat(e.mensaje)
        except Exception:  # noqa: BLE001 — el cliente recibe un mensaje genérico; el detalle va al log
            log.exception("Error inesperado en el turno de chat")
            yield ErrorChat("Ha ocurrido un error inesperado. Inténtalo de nuevo en unos segundos.")
        finally:
            self._sesiones.guardar(clave, mensajes)

    def _avisos_de_operaciones(self, clave: str) -> list[Mensaje]:
        """Cuenta al modelo cómo terminaron las operaciones que el cliente confirmó (o no) fuera del chat.

        Sin esto el modelo sigue diciendo «está pendiente de confirmación» cuando ya se envió, o al revés.
        """
        avisos, pendientes = [], []
        for id_operacion in self._seguimiento.pop(clave, []):
            operacion = self._operaciones.obtener(id_operacion)
            if operacion is None:
                continue
            if operacion.estado == EstadoOperacion.PENDIENTE:
                pendientes.append(id_operacion)  # sigue esperando: se mirará en el próximo turno
                continue
            resultado = {
                EstadoOperacion.CONFIRMADA: "CONFIRMADA por el cliente: el dinero YA se ha enviado",
                EstadoOperacion.CANCELADA: "CANCELADA: no se ha enviado nada",
                EstadoOperacion.CADUCADA: "CADUCADA: no se ha enviado nada",
                EstadoOperacion.BLOQUEADA: "BLOQUEADA por demasiados códigos erróneos: no se ha enviado nada",
            }[operacion.estado]
            avisos.append(Mensaje.usuario(
                f"{MARCA_AUTOMATICA} Resultado del Bizum de {euros(operacion.importe)} a {operacion.destinatario}: {resultado}."
            ))
        if pendientes:
            self._seguimiento[clave] = pendientes
        return avisos

    @staticmethod
    def _sanear(evento: EventoChat) -> EventoChat:
        # los modelos a veces cuelan caracteres invisibles (p. ej. "202​​2026")
        if isinstance(evento, (Delta, Fin)):
            return replace(evento, texto=limpiar_invisibles(evento.texto))
        if isinstance(evento, Aviso):
            return replace(evento, texto=limpiar_invisibles(evento.texto))
        return evento
