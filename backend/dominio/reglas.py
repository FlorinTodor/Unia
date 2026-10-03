"""Reglas de negocio puras: sin base de datos, sin red, sin framework."""
import re

from .errores import ConsultaNoPermitida, ImporteInvalido, LimiteBizumExcedido, SaldoInsuficiente

TOPE_BIZUM = 1000.0  # € por operación
LIMITE_FILAS_CONSULTA = 60

_PALABRAS_PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|pragma|create|replace|vacuum|reindex)\b",
    re.IGNORECASE,
)


def validar_importe_bizum(importe: float) -> float:
    """Comprueba el importe de un Bizum y lo devuelve redondeado a céntimos."""
    if importe <= 0:
        raise ImporteInvalido("El importe debe ser mayor que 0.")
    if importe > TOPE_BIZUM:
        raise LimiteBizumExcedido("Bizum permite un máximo de 1.000 € por operación.")
    return round(importe, 2)


def validar_saldo_suficiente(saldo: float, importe: float) -> None:
    if saldo < importe:
        raise SaldoInsuficiente(f"Saldo insuficiente ({saldo:.2f} €) para enviar {importe:.2f} €.")


def validar_consulta_solo_lectura(sql: str) -> str:
    """Valida el SQL que escribe el LLM y lo devuelve limpio.

    Primera barrera (lista blanca de forma + lista negra de palabras). La segunda
    es del adaptador: abre la base de datos en modo solo lectura.
    """
    limpia = sql.strip().rstrip(";").strip()
    if ";" in limpia:
        raise ConsultaNoPermitida("Solo se permite una única sentencia SQL.")
    if not limpia.lower().startswith(("select", "with")):
        raise ConsultaNoPermitida("Solo se permiten consultas SELECT.")
    if _PALABRAS_PROHIBIDAS.search(limpia):
        raise ConsultaNoPermitida("La consulta contiene palabras no permitidas.")
    return limpia
