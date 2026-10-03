"""Acceso: login con contraseña, sesión por cookie y bloqueo temporal tras intentos fallidos."""
from ...dominio.acceso import EstadoIntentos
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

    def __call__(self, usuario: str, contrasena: str) -> tuple[str, Cliente]:
        usuario = usuario.strip().lower()
        ahora = self._reloj.ahora()
        estado = self._intentos.obtener(usuario)
        if estado.bloqueado(ahora):
            self._auditoria.registrar(None, "login_bloqueado", usuario, "cuenta bloqueada temporalmente")
            raise CuentaBloqueada(
                f"Demasiados intentos. Vuelve a probar en {estado.minutos_restantes(ahora)} min.",
                reintentar_en=estado.minutos_restantes(ahora) * 60,
            )

        encontrado = self._clientes.buscar_por_usuario(usuario)
        if encontrado is None:
            self._hasheador.gastar_tiempo(contrasena)
            valido = False
        else:
            valido = self._hasheador.verificar(contrasena, encontrado[1])

        if not valido:
            nuevo = estado.tras_fallo(ahora)
            self._intentos.guardar(usuario, nuevo)
            self._auditoria.registrar(
                encontrado[0].id if encontrado else None, "login_fallido", usuario, "credenciales incorrectas"
            )
            if nuevo.bloqueado(ahora):
                raise CuentaBloqueada(
                    f"Demasiados intentos. Cuenta bloqueada {nuevo.minutos_restantes(ahora)} min por seguridad.",
                    reintentar_en=nuevo.minutos_restantes(ahora) * 60,
                )
            raise CredencialesInvalidas(MENSAJE_CREDENCIALES)

        cliente = encontrado[0]
        self._intentos.guardar(usuario, EstadoIntentos())
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
