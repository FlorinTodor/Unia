"""Reglas de acceso: bloqueo temporal tras varios intentos fallidos."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MAX_FALLOS = 5
# por origen: mucho más holgado porque varias personas comparten IP (NAT, wifi de la sala) y, sin proxy que ponga
# X-Forwarded-For, TODOS los clientes llegan como 127.0.0.1. Frena el rociado de usuarios sin dejar que 20 fallos
# de cualquiera bloqueen a todos (DECISIONES nº 17).
MAX_FALLOS_IP = 100
MINUTOS_BLOQUEO = 5
MINUTOS_VENTANA = 15  # los fallos sueltos caducan: el contador del origen no se reinicia al acertar, se desvanece


def clave_usuario(usuario: str) -> str:
    return f"u:{usuario}"  # espacios de nombres separados: un usuario llamado «ip:10.0.0.5» no bloquea esa IP


def clave_origen(origen: str) -> str:
    return f"ip:{origen}"


def clave_inexistente(usuario: str) -> str:
    # los usuarios inventados tienen su propio espacio (y cupo): inundarlo no expulsa el contador de una cuenta real
    return f"x:{usuario}"


@dataclass(frozen=True)
class EstadoIntentos:
    fallos: int = 0
    bloqueado_hasta: datetime | None = None
    desde: datetime | None = None  # primer fallo de la ventana en curso

    def bloqueado(self, ahora: datetime) -> bool:
        return self.bloqueado_hasta is not None and ahora < self.bloqueado_hasta

    def minutos_restantes(self, ahora: datetime) -> int:
        if not self.bloqueado(ahora):
            return 0
        return max(1, -(-int((self.bloqueado_hasta - ahora).total_seconds()) // 60))  # redondeo hacia arriba

    def tras_fallo(self, ahora: datetime, max_fallos: int = MAX_FALLOS, conservar_ventana: bool = False) -> "EstadoIntentos":
        """`conservar_ventana`: el bloqueo no reinicia la cuenta (límite por origen). Si se reiniciara, el tope real sería
        «max_fallos por bloqueo» (~100 cada 5 min) y no «por ventana» (100 cada 15 min)."""
        vigente = self.desde is None or ahora - self.desde <= timedelta(minutes=MINUTOS_VENTANA)
        fallos = (self.fallos if vigente else 0) + 1
        if fallos >= max_fallos:
            if conservar_ventana:
                return EstadoIntentos(fallos, ahora + timedelta(minutes=MINUTOS_BLOQUEO), self.desde if vigente and self.desde else ahora)
            return EstadoIntentos(0, ahora + timedelta(minutes=MINUTOS_BLOQUEO))
        return EstadoIntentos(fallos, self.bloqueado_hasta, self.desde if vigente and self.desde else ahora)


@dataclass(frozen=True)
class ReservaIntento:
    """Resultado de reservar un intento de login: o bien un bloqueo vigente (no se verifica nada) o los estados
    provisionales (con el fallo ya contado) junto a los anteriores, para devolver el intento si la contraseña era buena."""

    bloqueo: EstadoIntentos | None = None
    previos: dict[str, EstadoIntentos] = field(default_factory=dict)
    provisionales: dict[str, EstadoIntentos] = field(default_factory=dict)
    clave_bloqueada: str = ""  # qué clave (usuario u origen) tiene el bloqueo vigente
