"""Puertos de seguridad: identidad, contraseñas, sesiones, OTP y auditoría."""
from datetime import datetime
from typing import Protocol

from ...dominio.acceso import EstadoIntentos, ReservaIntento
from ...dominio.modelos import Cliente
from ...dominio.operaciones import OperacionPendiente


class RepositorioClientes(Protocol):
    def buscar_por_usuario(self, usuario: str) -> tuple[Cliente, str] | None:
        """Devuelve (cliente, hash de la contraseña) o None."""
        ...

    def obtener(self, cliente_id: int) -> Cliente | None: ...

    def listar(self) -> list[Cliente]:
        """Los clientes con cuenta (sin los administradores)."""
        ...


class Hasheador(Protocol):
    def hashear(self, contrasena: str) -> str: ...

    def verificar(self, contrasena: str, hash_guardado: str) -> bool: ...

    def gastar_tiempo(self, contrasena: str) -> None:
        """Mismo coste que verificar, para que un usuario inexistente no se distinga por el tiempo."""
        ...


class SesionesAutenticadas(Protocol):
    def crear(self, cliente_id: int) -> str:
        """Devuelve el token opaco que viajará en la cookie."""
        ...

    def cliente_de(self, token: str) -> int | None: ...

    def cerrar(self, token: str) -> None: ...


class RegistroIntentos(Protocol):
    def reservar(self, limites: dict[str, int], ahora: datetime, conservar_ventana: frozenset[str] = frozenset()) -> ReservaIntento:
        """Comprueba el bloqueo y cuenta un fallo provisional en cada clave, EN UN SOLO PASO atómico (antes de verificar
        la contraseña): así los intentos en paralelo no pueden pasar todos por scrypt antes de que salte el bloqueo."""
        ...

    def devolver(self, reserva: ReservaIntento, reiniciar: str) -> None:
        """La contraseña era correcta: se borra el contador de `reiniciar` y se devuelve el intento a las demás claves."""
        ...


class RepositorioOperaciones(Protocol):
    def guardar(self, operacion: OperacionPendiente) -> None: ...

    def obtener(self, id_operacion: str) -> OperacionPendiente | None: ...

    def pendientes_de(self, cliente_id: int) -> list[OperacionPendiente]:
        """Las operaciones de ESE cliente que siguen pendientes de confirmar (de cualquier tipo)."""
        ...


class GeneradorCodigos(Protocol):
    def nuevo_id(self) -> str: ...

    def nuevo_codigo(self) -> str:
        """Código OTP de 6 dígitos criptográficamente aleatorio."""
        ...


class CanalOTP(Protocol):
    def enviar(self, cliente_id: int, texto: str) -> None:
        """Entrega un mensaje al móvil del cliente (SMS simulado). Es el ÚNICO camino del código."""
        ...


class BandejaMovil(Protocol):
    def mensajes(self, cliente_id: int) -> list[dict]: ...


class Auditoria(Protocol):
    def registrar(self, cliente_id: int | None, accion: str, detalle: str, resultado: str) -> None: ...

    def ultimos(self, cliente_id: int, limite: int = 20) -> list[dict]: ...
