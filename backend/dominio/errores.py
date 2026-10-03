"""Errores de negocio. Todos llevan un mensaje ya legible para el usuario.

Cada categoría se traduce a un código HTTP en el adaptador de entrada, y a un
`{"ok": False, "error": ...}` cuando el que pregunta es el LLM (herramientas).
"""


class ErrorDeDominio(Exception):
    """Base de los errores esperables (reglas incumplidas, datos no encontrados...)."""

    def __init__(self, mensaje: str, **datos):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.datos = datos  # contexto útil para el LLM (p. ej. contactos disponibles)


class ErrorDeValidacion(ErrorDeDominio):
    """La petición no cumple una regla (importe, SQL no permitido, entrada vacía...)."""


class ErrorNoEncontrado(ErrorDeDominio):
    """El recurso pedido no existe."""


class ErrorNoDisponible(ErrorDeDominio):
    """Un servicio necesario no está disponible (voz sin configurar, sin motor de IA...)."""


# ------------------------------------------------------------------ banca

class ImporteInvalido(ErrorDeValidacion):
    pass


class LimiteBizumExcedido(ErrorDeValidacion):
    pass


class SaldoInsuficiente(ErrorDeValidacion):
    pass


class ConsultaNoPermitida(ErrorDeValidacion):
    pass


class ContactoNoEncontrado(ErrorNoEncontrado):
    pass
