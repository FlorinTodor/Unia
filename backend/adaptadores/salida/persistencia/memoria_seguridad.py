"""Estado de seguridad en memoria: intentos de login, operaciones pendientes y el móvil simulado."""
import threading
from collections import OrderedDict
from datetime import datetime

from ....dominio.acceso import EstadoIntentos, ReservaIntento
from ....dominio.operaciones import OperacionPendiente
from ....aplicacion.puertos.infraestructura import Reloj


def _espacio(clave: str) -> str:
    return clave.split(":", 1)[0] if clave.startswith(("u:", "x:", "ip:")) else ""


class IntentosEnMemoria:
    """Intentos de login por usuario (y por origen). Acotado: probar millones de usuarios inventados no agota la memoria.

    Cada espacio de claves (`u:` cuentas reales, `x:` usuarios inventados, `ip:` orígenes) tiene su propio cupo: inundar uno
    no expulsa los contadores de los otros. Todo cambio va bajo un cerrojo (los logins corren en hilos distintos).
    """

    def __init__(self, maximo: int = 10_000):
        self._maximo = maximo
        # por espacio, dos diccionarios ordenados (contadores y bloqueos; el orden de inserción es el de antigüedad): al
        # llenarse el cupo se expulsa el más antiguo en O(1), sin recorrer todas las claves bajo el cerrojo
        self._estados: dict[str, tuple[OrderedDict[str, EstadoIntentos], OrderedDict[str, EstadoIntentos]]] = {}
        self._cerrojo = threading.Lock()

    def obtener(self, clave: str) -> EstadoIntentos:
        """Solo para inspección (tests): la producción pasa siempre por `reservar`/`devolver`."""
        with self._cerrojo:
            return self._leer(clave)

    def reservar(self, limites: dict[str, int], ahora: datetime, conservar_ventana: frozenset[str] = frozenset()) -> ReservaIntento:
        with self._cerrojo:
            previos = {k: self._leer(k) for k in limites}
            for clave, estado in previos.items():
                if estado.bloqueado(ahora):
                    return ReservaIntento(bloqueo=estado, clave_bloqueada=clave)
            provisionales = {k: previos[k].tras_fallo(ahora, tope, k in conservar_ventana) for k, tope in limites.items()}
            for k, estado in provisionales.items():
                self._poner(k, estado)
            return ReservaIntento(None, previos, provisionales)

    def devolver(self, reserva: ReservaIntento, reiniciar: str) -> None:
        with self._cerrojo:
            for clave, previo in reserva.previos.items():
                if clave == reiniciar:
                    self._poner(clave, EstadoIntentos())
                elif self._leer(clave) == reserva.provisionales[clave]:
                    self._poner(clave, previo)  # nadie más lo ha tocado: se deshace. Si no, se deja (sobrecuenta mínima)

    def __len__(self) -> int:
        with self._cerrojo:
            return sum(len(c) + len(b) for c, b in self._estados.values())

    def _leer(self, clave: str) -> EstadoIntentos:
        contadores, bloqueos = self._estados.get(_espacio(clave), (None, None))
        if contadores is None:
            return EstadoIntentos()
        return contadores.get(clave) or bloqueos.get(clave) or EstadoIntentos()

    def _poner(self, clave: str, estado: EstadoIntentos) -> None:
        contadores, bloqueos = self._estados.setdefault(_espacio(clave), (OrderedDict(), OrderedDict()))
        contadores.pop(clave, None)
        bloqueos.pop(clave, None)
        if estado == EstadoIntentos():
            return  # sin fallos ni bloqueo no hace falta recordar nada
        (bloqueos if estado.bloqueado_hasta is not None else contadores)[clave] = estado
        sobran = len(contadores) + len(bloqueos) - self._maximo
        for _ in range(max(0, sobran)):
            # primero los simples contadores de fallos (los más antiguos); los bloqueos activos, los últimos
            (contadores or bloqueos).popitem(last=False)


class OperacionesEnMemoria:
    def __init__(self):
        self._operaciones: dict[str, OperacionPendiente] = {}

    def guardar(self, operacion: OperacionPendiente) -> None:
        self._operaciones[operacion.id] = operacion

    def obtener(self, id_operacion: str) -> OperacionPendiente | None:
        return self._operaciones.get(id_operacion)


class MovilSimulado:
    """El «teléfono» del cliente: recibe los SMS con el OTP. Es un canal aparte del chat."""

    def __init__(self, reloj: Reloj):
        self._reloj = reloj
        self._bandejas: dict[int, list[dict]] = {}

    def enviar(self, cliente_id: int, texto: str) -> None:
        self._bandejas.setdefault(cliente_id, []).append(
            {"remitente": "Unicaja", "texto": texto, "hora": self._reloj.ahora().strftime("%H:%M")}
        )

    def mensajes(self, cliente_id: int) -> list[dict]:
        return list(reversed(self._bandejas.get(cliente_id, [])[-10:]))
