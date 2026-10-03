"""Registro de uso de tokens en SQLite: sobrevive a los reinicios y permite ver el gasto por cliente y día."""
from datetime import date, datetime

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
        con = self._bd.abrir(solo_lectura=True)
        try:
            return con.execute(
                "SELECT COALESCE(SUM(tokens_entrada + tokens_salida), 0) FROM uso_ia WHERE proveedor != 'ollama' AND cliente_id = ? AND momento >= ? AND momento < ?",
                (cliente_id, dia.isoformat(), (dia.fromordinal(dia.toordinal() + 1)).isoformat()),
            ).fetchone()[0]
        finally:
            con.close()

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
