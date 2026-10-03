"""Registro de auditoría en SQLite: quién hizo qué, cuándo y con qué resultado."""
from ....aplicacion.puertos.infraestructura import Reloj
from .conexion import BaseDeDatos


class AuditoriaSqlite:
    def __init__(self, bd: BaseDeDatos, reloj: Reloj):
        self._bd = bd
        self._reloj = reloj

    def registrar(self, cliente_id: int | None, accion: str, detalle: str, resultado: str) -> None:
        con = self._bd.abrir()
        try:
            with con:
                con.execute(
                    "INSERT INTO auditoria (momento, cliente_id, accion, detalle, resultado) VALUES (?,?,?,?,?)",
                    (self._reloj.ahora().isoformat(timespec="seconds"), cliente_id, accion, detalle, resultado),
                )
        finally:
            con.close()

    def ultimos(self, cliente_id: int, limite: int = 20) -> list[dict]:
        con = self._bd.abrir(solo_lectura=True)
        try:
            return [
                dict(f) for f in con.execute(
                    "SELECT momento, accion, detalle, resultado FROM auditoria WHERE cliente_id = ? "
                    "ORDER BY id DESC LIMIT ?", (cliente_id, limite),
                )
            ]
        finally:
            con.close()
