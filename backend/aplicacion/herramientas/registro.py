"""Registro de herramientas: añadir una herramienta = escribir un módulo y registrarla.

El agente solo conoce este registro; no sabe qué herramientas existen ni qué hacen.
"""
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from ...dominio.errores import ErrorDeDominio
from ...dominio.modelos import Cliente
from ..eventos import EventoChat
from ..puertos.llm import EsquemaHerramienta


class Riesgo(str, Enum):
    LECTURA = "lectura"      # solo consulta datos
    PROTECCION = "proteccion"  # cambia el estado solo en la dirección segura (bloquear una tarjeta): sin OTP, pero auditado
    ESCRITURA = "escritura"  # modifica el estado del banco: debe devolver una operación pendiente de OTP, nunca ejecutar


@dataclass(frozen=True)
class ResultadoHerramienta:
    datos: dict  # lo que se le devuelve al LLM
    eventos: tuple[EventoChat, ...] = field(default_factory=tuple)  # lo que se muestra al usuario
    # Si la herramienta ya sabe qué decir (p. ej. «he preparado el Bizum, confírmalo en la tarjeta»), el turno termina con
    # este texto y NO se vuelve a llamar al modelo: es instantáneo, no gasta tokens y no puede desfasarse ni inventar nada.
    respuesta_final: str | None = None


@dataclass(frozen=True)
class Herramienta:
    esquema: EsquemaHerramienta
    ejecutar: Callable[[dict, Cliente], ResultadoHerramienta]  # (argumentos del LLM, cliente autenticado)
    etiqueta: str  # estado en pantalla mientras se ejecuta
    riesgo: Riesgo = Riesgo.LECTURA
    # Red de seguridad para el modelo pequeño (opcional). `orden_directa(pregunta)` devuelve los argumentos si la pregunta es
    # una orden inequívoca de esta herramienta (o None). Si el modelo no la llama, el agente le da un empujón (`aviso_orden`)
    # y, si aun así no la llama, la ejecuta el servidor. Solo para herramientas cuya ejecución sea segura (PROTECCION) o
    # que dejen una operación pendiente de OTP: el servidor nunca mueve dinero por su cuenta.
    orden_directa: Callable[[str], dict | None] | None = None
    aviso_orden: str = ""
    # Si existe, la herramienta solo se ejecuta cuando la última pregunta del usuario cumple esta condición (recibe esa
    # pregunta y el último mensaje del asistente antes de ella, por si es la respuesta a una aclaración): un modelo
    # engañado o un modelo local que llama solo («a mi madre le han robado la tarjeta») no bloquea nada sin una orden clara.
    # La comprueba el servidor para cualquier llamada, sea del modelo o del gancho `orden_directa`.
    pregunta_valida: Callable[[str, str], bool] | None = None
    # Lo que se contesta, sin volver al modelo, cuando `pregunta_valida` rechaza la llamada
    rechazo_final: str = ""

    @property
    def nombre(self) -> str:
        return self.esquema.nombre


@dataclass(frozen=True)
class OrdenDirecta:
    nombre: str
    argumentos: dict
    aviso: str


class RegistroHerramientas:
    def __init__(self, herramientas: Sequence[Herramienta]):
        self._por_nombre = {h.nombre: h for h in herramientas}
        if len(self._por_nombre) != len(herramientas):
            raise ValueError("Hay herramientas con el mismo nombre")
        for h in herramientas:
            if h.orden_directa is None:
                continue
            # el servidor ejecutará estas herramientas por su cuenta: solo si no pueden hacer daño
            if not h.aviso_orden.strip():
                raise ValueError(f"La herramienta {h.nombre} tiene orden_directa pero no aviso_orden: el modelo no recibiría el empujón")
            # PROTECCION (solo cambia hacia lo seguro) o ESCRITURA, que por contrato solo deja una operación pendiente de OTP
            # (lo comprueba tests/test_seguridad_chat.py); una herramienta de LECTURA no necesita empujón de este tipo
            if h.riesgo not in (Riesgo.PROTECCION, Riesgo.ESCRITURA):
                raise ValueError(f"La herramienta {h.nombre} con orden_directa debe ser de PROTECCION o crear una operación con OTP")

    def esquemas(self) -> list[EsquemaHerramienta]:
        return [h.esquema for h in self._por_nombre.values()]

    def etiqueta(self, nombre: str) -> str:
        herramienta = self._por_nombre.get(nombre)
        return herramienta.etiqueta if herramienta else nombre

    def riesgo(self, nombre: str) -> Riesgo | None:
        herramienta = self._por_nombre.get(nombre)
        return herramienta.riesgo if herramienta else None

    def permite(self, nombre: str, pregunta: str, anterior: str = "") -> bool:
        """¿La última pregunta del usuario justifica llamar a esta herramienta? (ver `Herramienta.pregunta_valida`)."""
        herramienta = self._por_nombre.get(nombre)
        return herramienta is None or herramienta.pregunta_valida is None or herramienta.pregunta_valida(pregunta, anterior)

    def rechazo_final(self, nombre: str) -> str:
        herramienta = self._por_nombre.get(nombre)
        return herramienta.rechazo_final if herramienta else ""

    def orden_directa(self, pregunta: str) -> OrdenDirecta | None:
        """La herramienta que, según su propia regla, debía llamarse para esta pregunta (ver `Herramienta.orden_directa`)."""
        for h in self._por_nombre.values():
            if h.orden_directa and (argumentos := h.orden_directa(pregunta)) is not None:
                return OrdenDirecta(h.nombre, argumentos, h.aviso_orden)
        return None

    def ejecutar(self, nombre: str, argumentos_json: str, cliente: Cliente) -> ResultadoHerramienta:
        """Ejecuta una herramienta pedida por el LLM. Nunca lanza errores de negocio:
        se los devuelve al modelo como `{"ok": False, "error": ...}` para que se explique."""
        herramienta = self._por_nombre.get(nombre)
        if herramienta is None:
            return ResultadoHerramienta({"ok": False, "error": f"Herramienta desconocida: {nombre}"})
        try:
            args = json.loads(argumentos_json or "{}")
        except json.JSONDecodeError:
            args = {}
        try:
            return herramienta.ejecutar(args, cliente)
        except ErrorDeDominio as e:
            return ResultadoHerramienta({"ok": False, "error": e.mensaje, **e.datos})
