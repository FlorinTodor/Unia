"""Identificadores y códigos OTP criptográficamente aleatorios (módulo `secrets`, no `random`)."""
import secrets


class GeneradorCodigosSeguro:
    def nuevo_id(self) -> str:
        return secrets.token_urlsafe(12)

    def nuevo_codigo(self) -> str:
        return f"{secrets.randbelow(10**6):06d}"
