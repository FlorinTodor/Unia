"""Acceso a la base de datos SQLite (data/banco.db)."""
import sqlite3
from pathlib import Path

RUTA_DATOS = Path(__file__).resolve().parents[4] / "data"
RUTA_DB = RUTA_DATOS / "banco.db"


class BaseDeDatos:
    def __init__(self, ruta: Path = RUTA_DB):
        self.ruta = ruta

    def abrir(self, solo_lectura: bool = False) -> sqlite3.Connection:
        if solo_lectura:
            con = sqlite3.connect(f"file:{self.ruta}?mode=ro", uri=True)
        else:
            con = sqlite3.connect(self.ruta)
        con.row_factory = sqlite3.Row
        return con
