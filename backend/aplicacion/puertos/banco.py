"""Puertos de salida del dominio bancario: cómo la aplicación pide y guarda datos."""
from typing import Protocol

from ...dominio.modelos import Contacto, Cuenta, Movimiento, ResultadoConsulta


class RepositorioCuenta(Protocol):
    def obtener(self) -> Cuenta: ...

    def registrar_movimiento(self, movimiento: Movimiento) -> Cuenta:
        """Guarda el movimiento y ajusta el saldo (atómico). Devuelve la cuenta actualizada."""
        ...


class RepositorioContactos(Protocol):
    def listar(self) -> list[Contacto]: ...

    def buscar(self, nombre_o_telefono: str) -> Contacto | None: ...


class ConsultorMovimientos(Protocol):
    def ejecutar_select(self, sql: str, limite: int) -> ResultadoConsulta:
        """Ejecuta una consulta YA validada. La implementación debe ser de solo lectura."""
        ...
