"""Entidades del negocio bancario y de la conversación."""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal


@dataclass(frozen=True)
class Cliente:
    """Persona autenticada. Todo acceso a datos y toda herramienta del agente se hace en su nombre."""

    id: int
    usuario: str
    nombre: str
    telefono: str  # al que se envían los códigos OTP
    es_admin: bool = False  # administra la configuración de la IA; no es un cliente con cuenta


@dataclass(frozen=True)
class Cuenta:
    iban: str
    titular: str
    saldo: float


@dataclass(frozen=True)
class Contacto:
    nombre: str
    telefono: str


@dataclass(frozen=True)
class Movimiento:
    fecha: date
    categoria: str
    concepto: str
    comercio: str
    importe: float  # negativo = gasto, positivo = ingreso


@dataclass(frozen=True)
class ResultadoConsulta:
    """Filas devueltas por una consulta de solo lectura."""

    columnas: list[str]
    filas: list[list]
    truncado: bool


@dataclass(frozen=True)
class ComprobanteBizum:
    destinatario: str
    telefono: str
    importe: float
    concepto: str
    nuevo_saldo: float


@dataclass(frozen=True)
class Tarjeta:
    """Tarjeta ficticia del cliente. Solo se guardan los 4 últimos dígitos: el número completo no existe en el sistema."""

    id: int
    marca: str  # «Visa», «Mastercard»
    tipo: str  # «débito» o «crédito»
    ultimos4: str
    bloqueada: bool = False
    bloqueada_el: datetime | None = None

    @property
    def etiqueta(self) -> str:
        return f"{self.marca} {self.tipo} ••{self.ultimos4}"

    @property
    def estado(self) -> str:
        return "bloqueada" if self.bloqueada else "activa"


@dataclass(frozen=True)
class ComprobanteTarjeta:
    """Resultado de confirmar el desbloqueo de una tarjeta (la operación pendiente de OTP)."""

    tarjeta: Tarjeta


# ------------------------------------------------------------------ conversación

Rol = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class LlamadaHerramienta:
    """Petición del LLM de ejecutar una herramienta. `argumentos` es JSON en bruto."""

    id: str
    nombre: str
    argumentos: str


@dataclass(frozen=True)
class Mensaje:
    rol: Rol
    contenido: str | None = None
    llamadas: tuple[LlamadaHerramienta, ...] = field(default_factory=tuple)  # solo rol "assistant"
    id_llamada: str | None = None  # solo rol "tool": a qué llamada responde

    @staticmethod
    def sistema(texto: str) -> "Mensaje":
        return Mensaje("system", texto)

    @staticmethod
    def usuario(texto: str) -> "Mensaje":
        return Mensaje("user", texto)

    @staticmethod
    def asistente(texto: str | None, llamadas: tuple[LlamadaHerramienta, ...] = ()) -> "Mensaje":
        return Mensaje("assistant", texto, llamadas)

    @staticmethod
    def resultado_herramienta(id_llamada: str, contenido: str) -> "Mensaje":
        return Mensaje("tool", contenido, id_llamada=id_llamada)
