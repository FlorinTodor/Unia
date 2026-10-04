"""Registro de uso de tokens en SQLite: sobrevive a los reinicios y permite ver el gasto por cliente y día."""
from datetime import date, datetime, timedelta

from ....dominio.proveedores import OLLAMA
from ....dominio.uso import Uso
from .conexion import BaseDeDatos


class UsoSqlite:
    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def registrar(self, cliente_id: int, proveedor: str, modelo: str, uso: Uso, momento: datetime) -> None:
        con = self._bd.abrir()
        try:
            with con:
                con.execute(
                    "INSERT INTO uso_ia (momento, cliente_id, proveedor, modelo, tokens_entrada, tokens_salida, estimado) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (momento.isoformat(timespec="seconds"), cliente_id, proveedor, modelo, uso.entrada, uso.salida, int(uso.estimado)),
                )
        finally:
            con.close()

    def tokens_del_dia(self, cliente_id: int, dia: date) -> int:
        """Tokens gastados en la nube (el modelo local es gratis y no cuenta aquí)."""
        return self._suma_del_dia(cliente_id, dia, "proveedor != ?")

    def tokens_locales_del_dia(self, cliente_id: int, dia: date) -> int:
        return self._suma_del_dia(cliente_id, dia, "proveedor = ?")

    def _suma_del_dia(self, cliente_id: int, dia: date, filtro_proveedor: str) -> int:
        con = self._bd.abrir(solo_lectura=True)
        try:
            return con.execute(
                "SELECT COALESCE(SUM(tokens_entrada + tokens_salida), 0) FROM uso_ia "
                f"WHERE {filtro_proveedor} AND cliente_id = ? AND momento >= ? AND momento < ?",
                (OLLAMA, cliente_id, dia.isoformat(), (dia + timedelta(days=1)).isoformat()),
            ).fetchone()[0]
        finally:
            con.close()

    def reiniciar_dia(self, cliente_id: int, dia: date) -> int:
        liberados = self.tokens_del_dia(cliente_id, dia)
        con = self._bd.abrir()
        try:
            with con:
                con.execute(
                    "DELETE FROM uso_ia WHERE cliente_id = ? AND momento >= ? AND momento < ?",
                    (cliente_id, dia.isoformat(), (dia + timedelta(days=1)).isoformat()),
                )
        finally:
            con.close()
        return liberados

    def ultimos(self, cliente_id: int, limite: int = 10) -> list[dict]:
        con = self._bd.abrir(solo_lectura=True)
        try:
            return [
                {"momento": f["momento"], "modelo": f["modelo"], "entrada": f["tokens_entrada"],
                 "salida": f["tokens_salida"], "estimado": bool(f["estimado"])}
                for f in con.execute(
                    "SELECT momento, modelo, tokens_entrada, tokens_salida, estimado FROM uso_ia "
                    "WHERE cliente_id = ? ORDER BY momento DESC, id DESC LIMIT ?", (cliente_id, limite),
                )
            ]
        finally:
            con.close()
