"""Puertos de salida del dominio bancario. TODOS reciben el `cliente_id`: la separación de datos
entre clientes la garantiza quien implementa el puerto, no quien lo llama."""
from datetime import date
from typing import Protocol

from ...dominio.modelos import Contacto, Cuenta, Movimiento, ResultadoConsulta, Tarjeta


class RepositorioCuenta(Protocol):
    def obtener(self, cliente_id: int) -> Cuenta: ...

    def registrar_movimiento(self, cliente_id: int, movimiento: Movimiento) -> Cuenta:
        """Guarda el movimiento y ajusta el saldo (atómico). Devuelve la cuenta actualizada."""
        ...

    def bizum_enviado_el(self, cliente_id: int, dia: date) -> float:
        """Total (positivo) enviado por Bizum ese día."""
        ...

    def envios_bizum_a(self, cliente_id: int, nombre: str) -> int:
        """Cuántos Bizum ha enviado ya este cliente a ese contacto."""
        ...


class RepositorioContactos(Protocol):
    def listar(self, cliente_id: int) -> list[Contacto]: ...

    def buscar(self, cliente_id: int, nombre_o_telefono: str) -> Contacto | None: ...


class ConsultorMovimientos(Protocol):
    def ejecutar_select(self, cliente_id: int, sql: str, limite: int) -> ResultadoConsulta:
        """Ejecuta una consulta YA validada. La implementación debe ser de solo lectura y
        mostrar únicamente los datos de ese cliente (aunque el SQL intente otra cosa)."""
        ...


class RepositorioTarjetas(Protocol):
    def listar(self, cliente_id: int) -> list[Tarjeta]: ...

    def guardar_estado(self, cliente_id: int, tarjeta: Tarjeta) -> None:
        """Persiste `bloqueada` y `bloqueada_el` como una TRANSICIÓN atómica: solo cambia si la tarjeta de ESE cliente está
        ahora en el estado contrario. Si no es suya, `TarjetaNoEncontrada`; si ya estaba así (otro hilo se adelantó),
        `TarjetaYaBloqueada` / `TarjetaYaActiva`."""
        ...
