"""Puerto del modelo de lenguaje: la aplicación no sabe qué proveedor ni qué SDK hay detrás."""
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from ...dominio.modelos import LlamadaHerramienta, Mensaje
from ...dominio.proveedores import ModeloRef


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


EventoLLM = DeltaTexto | PeticionHerramientas


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
    ) -> Iterator[EventoLLM]:
        """Una llamada en streaming. Emite DeltaTexto y, al final, PeticionHerramientas si procede."""
        ...
