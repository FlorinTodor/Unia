"""Reglas de negocio puras: sin base de datos, sin red, sin framework."""
import re

from .errores import (
    ConsultaNoPermitida,
    ImporteInvalido,
    LimiteBizumExcedido,
    LimiteDiarioExcedido,
    SaldoInsuficiente,
)

TOPE_BIZUM = 1000.0  # € por operación
TOPE_DIARIO_BIZUM = 1500.0  # € por cliente y día
UMBRAL_IMPORTE_ALTO = 300.0  # a partir de aquí se avisa al cliente en la confirmación
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


def euros(importe: float) -> str:
    """1234.5 → «1.234,50 €»."""
    return f"{importe:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def validar_tope_diario(enviado_hoy: float, importe: float) -> None:
    if enviado_hoy + importe > TOPE_DIARIO_BIZUM:
        restante = max(TOPE_DIARIO_BIZUM - enviado_hoy, 0)
        raise LimiteDiarioExcedido(
            f"Superarías el límite diario de Bizum ({euros(TOPE_DIARIO_BIZUM)}). "
            f"Hoy aún puedes enviar {euros(restante)}."
        )


def alertas_bizum(importe: float, envios_previos_al_destinatario: int) -> tuple[str, ...]:
    """Avisos que se muestran al cliente junto al código (no bloquean la operación)."""
    alertas = []
    if envios_previos_al_destinatario == 0:
        alertas.append("Es la primera vez que envías un Bizum a este contacto.")
    if importe >= UMBRAL_IMPORTE_ALTO:
        alertas.append(f"Importe alto: {euros(importe)}.")
    return tuple(alertas)


def validar_saldo_suficiente(saldo: float, importe: float) -> None:
    if saldo < importe:
        raise SaldoInsuficiente(f"Saldo insuficiente ({euros(saldo)}) para enviar {euros(importe)}.")


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
