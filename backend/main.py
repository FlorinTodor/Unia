"""Punto de entrada: `uvicorn backend.main:app`."""
from .composicion import crear_aplicacion

app = crear_aplicacion()
