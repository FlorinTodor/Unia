"""Puertos de seguridad: identidad, contraseñas, sesiones, OTP y auditoría."""
from datetime import datetime
from typing import Protocol

from ...dominio.acceso import EstadoIntentos
from ...dominio.modelos import Cliente
from ...dominio.operaciones import OperacionPendiente


class RepositorioClientes(Protocol):
    def buscar_por_usuario(self, usuario: str) -> tuple[Cliente, str] | None:
        """Devuelve (cliente, hash de la contraseña) o None."""
        ...

    def obtener(self, cliente_id: int) -> Cliente | None: ...


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
    def obtener(self, usuario: str) -> EstadoIntentos: ...

    def guardar(self, usuario: str, estado: EstadoIntentos) -> None: ...


class RepositorioOperaciones(Protocol):
    def guardar(self, operacion: OperacionPendiente) -> None: ...

    def obtener(self, id_operacion: str) -> OperacionPendiente | None: ...


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
