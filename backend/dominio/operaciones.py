"""Operaciones que exigen confirmación con un código de un solo uso (OTP), como la SCA de la PSD2.

El LLM solo puede *solicitar* una operación; ejecutarla exige un código que viaja por otro
canal (el móvil del cliente) y se valida fuera del agente. El dominio decide si el código vale.
"""
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from .errores import (
    CodigoIncorrecto,
    OperacionBloqueada,
    OperacionCaducada,
    OperacionYaProcesada,
)

MINUTOS_CADUCIDAD = 5
MAX_INTENTOS_CODIGO = 3


class EstadoOperacion(str, Enum):
    PENDIENTE = "pendiente"
    CONFIRMADA = "confirmada"
    CANCELADA = "cancelada"
    CADUCADA = "caducada"
    BLOQUEADA = "bloqueada"


def huella_codigo(id_operacion: str, codigo: str) -> str:
    """El código nunca se guarda en claro: solo su huella, ligada a la operación."""
    return hashlib.sha256(f"{id_operacion}:{codigo}".encode()).hexdigest()


@dataclass
class OperacionPendiente:
    id: str
    cliente_id: int
    destinatario: str
    telefono: str
    importe: float
    concepto: str
    huella: str
    creada: datetime
    caduca: datetime
    alertas: tuple[str, ...] = ()
    intentos_restantes: int = MAX_INTENTOS_CODIGO
    estado: EstadoOperacion = field(default=EstadoOperacion.PENDIENTE)

    @staticmethod
    def nueva(id: str, cliente_id: int, destinatario: str, telefono: str, importe: float, concepto: str,
              codigo: str, ahora: datetime, alertas: tuple[str, ...] = ()) -> "OperacionPendiente":
        return OperacionPendiente(
            id, cliente_id, destinatario, telefono, importe, concepto, huella_codigo(id, codigo),
            ahora, ahora + timedelta(minutes=MINUTOS_CADUCIDAD), alertas,
        )

    def verificar(self, codigo: str, ahora: datetime) -> None:
        """Comprueba el código. Si vale, la operación pasa a CONFIRMADA; si no, lanza un error de dominio.

        Muta la operación (intentos, estado): quien la llame debe guardarla después.
        """
        if self.estado != EstadoOperacion.PENDIENTE:
            raise OperacionYaProcesada(f"Esta operación ya está {self.estado.value}.")
        if ahora >= self.caduca:
            self.estado = EstadoOperacion.CADUCADA
            raise OperacionCaducada("El código ha caducado. Pide la operación de nuevo.")
        if not hmac.compare_digest(huella_codigo(self.id, codigo.strip()), self.huella):
            self.intentos_restantes -= 1
            if self.intentos_restantes <= 0:
                self.estado = EstadoOperacion.BLOQUEADA
                raise OperacionBloqueada("Demasiados intentos: la operación se ha cancelado por seguridad.")
            quedan = self.intentos_restantes
            raise CodigoIncorrecto(f"Código incorrecto. Te {'queda' if quedan == 1 else 'quedan'} {quedan} {'intento' if quedan == 1 else 'intentos'}.")
        self.estado = EstadoOperacion.CONFIRMADA

    def aprobar(self, ahora: datetime) -> None:
        """Aprobación sin teclear el código (huella o Face ID en el móvil): alternativa accesible al OTP.

        Mismas condiciones que el código: la operación debe estar pendiente y no haber caducado.
        """
        if self.estado != EstadoOperacion.PENDIENTE:
            raise OperacionYaProcesada(f"Esta operación ya está {self.estado.value}.")
        if ahora >= self.caduca:
            self.estado = EstadoOperacion.CADUCADA
            raise OperacionCaducada("La aprobación ha caducado. Pide la operación de nuevo.")
        self.estado = EstadoOperacion.CONFIRMADA

    def cancelar(self) -> None:
        if self.estado != EstadoOperacion.PENDIENTE:
            raise OperacionYaProcesada(f"Esta operación ya está {self.estado.value}.")
        self.estado = EstadoOperacion.CANCELADA
