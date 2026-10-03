"""Dobles de prueba en memoria: implementan los puertos sin red ni base de datos."""
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date

from backend.aplicacion.puertos.infraestructura import EstadoOllama
from backend.aplicacion.puertos.llm import DeltaTexto, EsquemaHerramienta, PeticionHerramientas
from backend.dominio.ajustes import Ajustes, ConfigClave
from backend.dominio.modelos import Contacto, Cuenta, LlamadaHerramienta, Mensaje, Movimiento, ResultadoConsulta
from backend.dominio.proveedores import ModeloRef


class RelojFijo:
    def __init__(self, hoy: date = date(2026, 10, 3)):
        self._hoy = hoy

    def hoy(self) -> date:
        return self._hoy


class CuentaEnMemoria:
    def __init__(self, saldo: float = 500.0):
        self.cuenta = Cuenta("ES00", "Alex García", saldo)
        self.movimientos: list[Movimiento] = []

    def obtener(self) -> Cuenta:
        return self.cuenta

    def registrar_movimiento(self, movimiento: Movimiento) -> Cuenta:
        self.movimientos.append(movimiento)
        self.cuenta = replace(self.cuenta, saldo=round(self.cuenta.saldo + movimiento.importe, 2))
        return self.cuenta


class ContactosEnMemoria:
    def __init__(self):
        self.contactos = [Contacto("María López", "600111222"), Contacto("Pablo Ruiz", "611333444")]

    def listar(self) -> list[Contacto]:
        return list(self.contactos)

    def buscar(self, nombre_o_telefono: str) -> Contacto | None:
        return next(
            (c for c in self.contactos if nombre_o_telefono.lower() in c.nombre.lower() or c.telefono == nombre_o_telefono),
            None,
        )


class ConsultorFalso:
    def __init__(self):
        self.consultas: list[tuple[str, int]] = []

    def ejecutar_select(self, sql: str, limite: int) -> ResultadoConsulta:
        self.consultas.append((sql, limite))
        return ResultadoConsulta(["total"], [[42.0]], truncado=False)


class AjustesEnMemoria:
    def __init__(self, ajustes: Ajustes | None = None):
        self.ajustes = ajustes or Ajustes(
            activo="groq", claves={"groq": ConfigClave("gsk_x", "modelo-a", "modelo-b", ["modelo-a", "modelo-b"])},
            fallback_local=False,
        )

    def cargar(self) -> Ajustes:
        return self.ajustes

    def guardar(self, ajustes: Ajustes) -> None:
        self.ajustes = ajustes


class SondaFalsa:
    def __init__(self, modelos: list[str] | None = None, error: Exception | None = None):
        self.modelos = modelos if modelos is not None else ["m1", "m2"]
        self.error = error

    def listar_modelos(self, proveedor: str, api_key: str | None = None) -> list[str]:
        if self.error:
            raise self.error
        return self.modelos

    def estado_ollama(self, url: str) -> EstadoOllama:
        return EstadoOllama(True, "ok", [])


class LLMGuionizado:
    """LLM de mentira: cada llamada a `completar` consume un paso del guion.

    Un paso es una lista de eventos, o una excepción que se lanza al empezar.
    """

    def __init__(self, *pasos):
        self.pasos = list(pasos)
        self.llamadas: list[tuple[ModeloRef, list[Mensaje], Sequence[EsquemaHerramienta] | None]] = []

    def completar(self, modelo, mensajes, herramientas) -> Iterator:
        self.llamadas.append((modelo, list(mensajes), herramientas))
        paso = self.pasos.pop(0)
        if isinstance(paso, Exception):
            raise paso
        yield from paso


def texto(*trozos: str) -> list:
    return [DeltaTexto(t) for t in trozos]


def llamada(nombre: str, argumentos: str = "{}", id: str = "c1") -> list:
    return [PeticionHerramientas((LlamadaHerramienta(id, nombre, argumentos),))]
