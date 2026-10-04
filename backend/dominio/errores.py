"""Errores de negocio. Todos llevan un mensaje ya legible para el usuario.

Cada categoría se traduce a un código HTTP en el adaptador de entrada (`errores_http.py`), y a un
`{"ok": False, "error": ...}` cuando el que pregunta es el LLM (herramientas).

    categoría              HTTP   cuándo
    ErrorDeValidacion      422    la petición incumple una regla (importe, código mal formado...)
    ErrorDeAutenticacion   401    sin sesión o credenciales incorrectas
    ErrorDeAccesoDenegado  403    hay sesión pero no se permite (origen no permitido)
    ErrorNoEncontrado      404    el recurso no existe (o es de otro cliente)
    ErrorDeConflicto       409    choca con el estado actual (saldo, tope diario, operación ya procesada)
    ErrorCaducado          410    el recurso existió pero ya no vale (código OTP caducado)
    ErrorCargaExcesiva     413    entrada demasiado grande (mensaje, audio)
    ErrorTipoNoSoportado   415    formato no aceptado
    ErrorBloqueado         423    bloqueado por seguridad (demasiados intentos con el código)
    ErrorLimiteExcedido    429    demasiadas peticiones, cuota de uso o login bloqueado (con Retry-After)
    ErrorProveedorExterno  502    falla un servicio externo (IA, voz)
    ErrorNoDisponible      503    falta algo para poder atender (sin motor de IA, sin clave de voz)
    ErrorTiempoAgotado     504    un servicio externo no responde a tiempo
    ErrorDeDominio         400    solo si alguien lanza la base sin categoría (el test lo impide)
"""


class ErrorDeDominio(Exception):
    """Base de los errores esperables (reglas incumplidas, datos no encontrados...)."""

    def __init__(self, mensaje: str, **datos):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.datos = datos  # contexto útil para el LLM y para el cliente (p. ej. contactos disponibles)


class ErrorDeValidacion(ErrorDeDominio):
    """La petición no cumple una regla (importe, SQL no permitido, entrada vacía...)."""


class ErrorNoEncontrado(ErrorDeDominio):
    """El recurso pedido no existe."""


class ErrorNoDisponible(ErrorDeDominio):
    """Un servicio necesario no está disponible (voz sin configurar, sin motor de IA...)."""


class ErrorDeAutenticacion(ErrorDeDominio):
    """No hay sesión válida o las credenciales no son correctas."""


class ErrorDeAccesoDenegado(ErrorDeDominio):
    """Hay sesión, pero la petición no está permitida (p. ej. viene de otro origen)."""


class ErrorDeConflicto(ErrorDeDominio):
    """La petición es válida pero choca con el estado actual de los datos."""


class ErrorCaducado(ErrorDeDominio):
    """El recurso existió pero ya no es válido."""


class ErrorCargaExcesiva(ErrorDeDominio):
    """La entrada supera el tamaño permitido."""


class ErrorTipoNoSoportado(ErrorDeDominio):
    """El formato de la entrada no se acepta."""


class ErrorBloqueado(ErrorDeDominio):
    """Bloqueado por seguridad: no se puede reintentar."""


class ErrorLimiteExcedido(ErrorDeDominio):
    """Se superó un límite de uso. `reintentar_en` son los segundos tras los que se puede volver a intentar."""

    def __init__(self, mensaje: str, reintentar_en: int | None = None, **datos):
        super().__init__(mensaje, **datos)
        self.reintentar_en = reintentar_en


class ErrorProveedorExterno(ErrorDeDominio):
    """Falla un servicio externo (proveedor de IA, voz)."""


class ErrorTiempoAgotado(ErrorProveedorExterno):
    """Un servicio externo no responde a tiempo."""


# ------------------------------------------------------------------ banca

class ImporteInvalido(ErrorDeValidacion):
    pass


class LimiteBizumExcedido(ErrorDeValidacion):
    pass


class SaldoInsuficiente(ErrorDeConflicto):
    pass


class ConsultaNoPermitida(ErrorDeValidacion):
    pass


class ContactoNoEncontrado(ErrorNoEncontrado):
    pass


class ContactoAmbiguo(ErrorDeConflicto):
    """El nombre escrito coincide con varios contactos: hay que elegir (no se adivina)."""


# ------------------------------------------------------------------ tarjetas

class TarjetaNoEncontrada(ErrorNoEncontrado):
    pass


class _ConflictoDeTarjetas(ErrorDeConflicto):
    """Conflicto que afecta a una o varias tarjetas (`tarjetas`: las implicadas, para mostrarlas al cliente)."""

    def __init__(self, mensaje: str, tarjetas: tuple = (), **datos):
        super().__init__(mensaje, **datos)
        self.tarjetas = tarjetas


class TarjetaAmbigua(_ConflictoDeTarjetas):
    """Lo escrito encaja con varias tarjetas: hay que elegir (no se adivina cuál bloquear)."""


class TarjetaYaBloqueada(_ConflictoDeTarjetas):
    pass


class TarjetaYaActiva(_ConflictoDeTarjetas):
    pass


# ------------------------------------------------------------------ acceso

class NoAutenticado(ErrorDeAutenticacion):
    pass


class CredencialesInvalidas(ErrorDeAutenticacion):
    pass


class CuentaBloqueada(ErrorLimiteExcedido):
    """Demasiados intentos fallidos de login: bloqueo temporal (429 con Retry-After)."""


# ------------------------------------------------------------------ operaciones con OTP

class LimiteDiarioExcedido(ErrorDeConflicto):
    pass


class OperacionNoEncontrada(ErrorNoEncontrado):
    pass


class OperacionCaducada(ErrorCaducado):
    pass


class CodigoIncorrecto(ErrorDeValidacion):
    pass


class OperacionBloqueada(ErrorBloqueado):
    """Se agotaron los intentos del código: la operación queda cancelada."""


class OperacionYaProcesada(ErrorDeConflicto):
    pass


# ------------------------------------------------------------------ uso del asistente

class MensajeDemasiadoLargo(ErrorCargaExcesiva):
    pass


class AudioDemasiadoGrande(ErrorCargaExcesiva):
    pass


class DemasiadasPeticiones(ErrorLimiteExcedido):
    pass


class LimiteDeTokensExcedido(ErrorLimiteExcedido):
    pass


class TurnoEnCurso(ErrorLimiteExcedido):
    """El cliente ya tiene una pregunta respondiéndose: solo se atiende una a la vez (429)."""


# Los que un caso de uso trata como «la regla de negocio no lo permite» (se audita y se propaga tal cual).
ERRORES_DE_REGLA = (ErrorDeValidacion, ErrorDeConflicto, ErrorCaducado, ErrorBloqueado)
