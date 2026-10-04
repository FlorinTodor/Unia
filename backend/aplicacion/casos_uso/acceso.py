"""Acceso: login con contraseña, sesión por cookie y bloqueo temporal tras intentos fallidos."""
import threading
from datetime import datetime

from ...dominio.acceso import MAX_FALLOS, MAX_FALLOS_IP, clave_inexistente, clave_origen, clave_usuario
from ...dominio.errores import CredencialesInvalidas, CuentaBloqueada, NoAutenticado
from ...dominio.modelos import Cliente
from ..puertos.infraestructura import Reloj
from ..puertos.seguridad import (
    Auditoria,
    Hasheador,
    RegistroIntentos,
    RepositorioClientes,
    SesionesAutenticadas,
)

# mismo mensaje para «usuario inexistente» y «contraseña errónea»: no se revela qué usuarios existen
MENSAJE_CREDENCIALES = "Usuario o contraseña incorrectos."


class IniciarSesion:
    def __init__(
        self,
        clientes: RepositorioClientes,
        hasheador: Hasheador,
        sesiones: SesionesAutenticadas,
        intentos: RegistroIntentos,
        reloj: Reloj,
        auditoria: Auditoria,
    ):
        self._clientes = clientes
        self._hasheador = hasheador
        self._sesiones = sesiones
        self._intentos = intentos
        self._reloj = reloj
        self._auditoria = auditoria
        # clave → fin del bloqueo ya auditado: contra una cuenta bloqueada se puede insistir miles de veces y cada
        # petición llenaba la auditoría; se registra una sola vez por clave y bloqueo
        self._bloqueos_auditados: dict[str, datetime] = {}
        self._cerrojo_auditoria = threading.Lock()

    def _auditar_bloqueo(self, usuario: str, clave: str, hasta: datetime, ahora: datetime) -> None:
        with self._cerrojo_auditoria:
            for k in [k for k, fin in self._bloqueos_auditados.items() if fin <= ahora]:
                del self._bloqueos_auditados[k]  # caducados: el siguiente bloqueo de esa clave vuelve a registrarse
            if self._bloqueos_auditados.get(clave) == hasta:
                return
            self._bloqueos_auditados[clave] = hasta
        self._auditoria.registrar(None, "login_bloqueado", usuario, "cuenta u origen bloqueados temporalmente")

    def __call__(self, usuario: str, contrasena: str, origen: str | None = None) -> tuple[str, Cliente]:
        usuario = usuario.strip().lower()
        ahora = self._reloj.ahora()
        encontrado = self._clientes.buscar_por_usuario(usuario)
        k_usuario = clave_usuario(usuario) if encontrado else clave_inexistente(usuario)
        k_origen = clave_origen(origen) if origen else None
        # El intento se RESERVA antes de verificar (scrypt tarda ~0,1 s): si se leyera el contador antes y se guardara
        # después, 40 peticiones en paralelo pasarían todas por scrypt antes de que saltara el bloqueo. La reserva cuenta
        # un fallo provisional en cada clave y se devuelve si la contraseña resulta correcta.
        limites = {k_usuario: MAX_FALLOS}
        if k_origen:  # adivinar contraseñas de muchos usuarios desde un mismo sitio también se frena
            limites[k_origen] = MAX_FALLOS_IP
        reserva = self._intentos.reservar(limites, ahora, frozenset({k_origen}) if k_origen else frozenset())
        if reserva.bloqueo is not None:
            bloqueo = reserva.bloqueo
            self._auditar_bloqueo(usuario, reserva.clave_bloqueada, bloqueo.bloqueado_hasta, ahora)
            raise CuentaBloqueada(
                f"Demasiados intentos. Vuelve a probar en {bloqueo.minutos_restantes(ahora)} min.",
                reintentar_en=bloqueo.minutos_restantes(ahora) * 60,
            )

        if encontrado is None:
            self._hasheador.gastar_tiempo(contrasena)
            valido = False
        else:
            valido = self._hasheador.verificar(contrasena, encontrado[1])

        if not valido:
            nuevo = reserva.provisionales[k_usuario]
            por_origen = False
            if k_origen and not nuevo.bloqueado(ahora):
                nuevo, por_origen = reserva.provisionales[k_origen], True
            self._auditoria.registrar(
                encontrado[0].id if encontrado else None, "login_fallido", usuario, "credenciales incorrectas"
            )
            if nuevo.bloqueado(ahora):
                # si lo bloqueado es el origen, la cuenta de este usuario no tiene nada: el mensaje no lo sugiere
                texto = (
                    f"Demasiados intentos. Vuelve a probar en {nuevo.minutos_restantes(ahora)} min." if por_origen
                    else f"Demasiados intentos. Cuenta bloqueada {nuevo.minutos_restantes(ahora)} min por seguridad."
                )
                raise CuentaBloqueada(
                    texto,
                    reintentar_en=nuevo.minutos_restantes(ahora) * 60,
                )
            raise CredencialesInvalidas(MENSAJE_CREDENCIALES)

        cliente = encontrado[0]
        # solo se reinicia el contador del usuario: el del origen caduca por ventana (se le devuelve el intento reservado).
        # Si un acierto lo borrara, un atacante con una cuenta propia lo reiniciaría a voluntad.
        self._intentos.devolver(reserva, k_usuario)
        self._auditoria.registrar(cliente.id, "login_ok", usuario, "ok")
        return self._sesiones.crear(cliente.id), cliente


class IdentificarCliente:
    """Resuelve el cliente de una sesión; es lo que protege cada endpoint."""

    def __init__(self, sesiones: SesionesAutenticadas, clientes: RepositorioClientes):
        self._sesiones = sesiones
        self._clientes = clientes

    def __call__(self, token: str | None) -> Cliente:
        cliente_id = self._sesiones.cliente_de(token) if token else None
        cliente = self._clientes.obtener(cliente_id) if cliente_id is not None else None
        if cliente is None:
            raise NoAutenticado("Inicia sesión para continuar.")
        return cliente


class CerrarSesion:
    def __init__(self, sesiones: SesionesAutenticadas, auditoria: Auditoria):
        self._sesiones = sesiones
        self._auditoria = auditoria

    def __call__(self, token: str | None, cliente: Cliente | None = None) -> None:
        if token:
            self._sesiones.cerrar(token)
        if cliente:
            self._auditoria.registrar(cliente.id, "logout", cliente.usuario, "ok")
