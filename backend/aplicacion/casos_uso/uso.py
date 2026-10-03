"""Consulta del gasto de tokens del cliente (medidor de la interfaz y endpoint `/api/uso`)."""
from dataclasses import dataclass

from ...dominio.modelos import Cliente
from ...dominio.uso import PresupuestoUso
from ..puertos.infraestructura import Reloj
from ..puertos.uso import RegistroUso


@dataclass(frozen=True)
class ResumenUso:
    tokens_hoy: int
    limite_dia: int
    por_turno: int
    peticiones_por_minuto: int
    max_caracteres_mensaje: int
    ultimos: list[dict]

    @property
    def restante(self) -> int:
        return max(0, self.limite_dia - self.tokens_hoy)

    @property
    def porcentaje(self) -> float:
        return round(min(100.0, 100 * self.tokens_hoy / self.limite_dia), 1) if self.limite_dia else 0.0


class ConsultarUso:
    def __init__(self, registro: RegistroUso, presupuesto: PresupuestoUso, reloj: Reloj):
        self._registro = registro
        self._presupuesto = presupuesto
        self._reloj = reloj

    def __call__(self, cliente: Cliente) -> ResumenUso:
        p = self._presupuesto
        return ResumenUso(
            self._registro.tokens_del_dia(cliente.id, self._reloj.hoy()), p.tokens_por_dia, p.tokens_por_turno,
            p.peticiones_por_minuto, p.max_caracteres_mensaje, self._registro.ultimos(cliente.id),
        )
