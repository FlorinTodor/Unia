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

    @property
    def nombre(self) -> str:
        return self.esquema.nombre


class RegistroHerramientas:
    def __init__(self, herramientas: Sequence[Herramienta]):
        self._por_nombre = {h.nombre: h for h in herramientas}
        if len(self._por_nombre) != len(herramientas):
            raise ValueError("Hay herramientas con el mismo nombre")

    def esquemas(self) -> list[EsquemaHerramienta]:
        return [h.esquema for h in self._por_nombre.values()]

    def etiqueta(self, nombre: str) -> str:
        herramienta = self._por_nombre.get(nombre)
        return herramienta.etiqueta if herramienta else nombre

    def riesgo(self, nombre: str) -> Riesgo | None:
        herramienta = self._por_nombre.get(nombre)
        return herramienta.riesgo if herramienta else None

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
