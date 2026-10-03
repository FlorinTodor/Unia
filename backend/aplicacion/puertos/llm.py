"""Puerto del modelo de lenguaje: la aplicación no sabe qué proveedor ni qué SDK hay detrás."""
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from ...dominio.modelos import LlamadaHerramienta, Mensaje
from ...dominio.proveedores import ModeloRef
from ...dominio.uso import Uso


@dataclass(frozen=True)
class EsquemaHerramienta:
    """Cómo se le describe una herramienta al LLM (nombre, para qué sirve, parámetros JSON Schema)."""

    nombre: str
    descripcion: str
    parametros: dict


# ------------------------------------------------------------------ eventos del stream

@dataclass(frozen=True)
class DeltaTexto:
    texto: str


@dataclass(frozen=True)
class PeticionHerramientas:
    """Al terminar el stream: las herramientas que el modelo quiere ejecutar."""

    llamadas: tuple[LlamadaHerramienta, ...]


@dataclass(frozen=True)
class UsoTokens:
    """Tokens que ha costado la llamada (siempre se emite al terminar el stream)."""

    uso: Uso


EventoLLM = DeltaTexto | PeticionHerramientas | UsoTokens


# ------------------------------------------------------------------ errores del puerto

class ErrorProveedor(Exception):
    """El proveedor falló. Los adaptadores traducen aquí los errores de su SDK."""


class ProveedorNoUtilizable(ErrorProveedor):
    """Este eslabón no sirve ahora: hay que pasar al siguiente de la cadena."""


class ClaveInvalida(ProveedorNoUtilizable):
    pass


class ModeloNoEncontrado(ProveedorNoUtilizable):
    pass


class CuotaAgotada(ProveedorNoUtilizable):
    pass


class LimitePorMinuto(CuotaAgotada):
    """Se superó el límite de tokens/peticiones por minuto: pasa solo en unos segundos."""

    def __init__(self, mensaje: str, espera: float | None = None):
        super().__init__(mensaje)
        self.espera = espera  # segundos que indica el proveedor, si los indica


class ProveedorInaccesible(ProveedorNoUtilizable):
    """Sin conexión o error 5xx."""


class GeneracionFallida(ErrorProveedor):
    """Fallo esporádico del modelo (p. ej. JSON de herramienta inválido): se reintenta."""


class ProveedorLLM(Protocol):
    def completar(
        self,
        modelo: ModeloRef,
        mensajes: Sequence[Mensaje],
        herramientas: Sequence[EsquemaHerramienta] | None,
        max_tokens: int | None = None,
    ) -> Iterator[EventoLLM]:
        """Una llamada en streaming. Emite DeltaTexto, PeticionHerramientas si procede y, al final, UsoTokens.

        `max_tokens` limita lo que puede generar el modelo en esta llamada.
        """
        ...
