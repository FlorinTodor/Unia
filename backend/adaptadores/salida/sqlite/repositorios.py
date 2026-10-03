"""Implementaciones SQLite de los puertos bancarios."""
import sqlite3

from ....dominio.errores import ConsultaNoPermitida
from ....dominio.modelos import Contacto, Cuenta, Movimiento, ResultadoConsulta
from .conexion import BaseDeDatos


class RepositorioCuentaSqlite:
    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def obtener(self) -> Cuenta:
        con = self._bd.abrir(solo_lectura=True)
        try:
            fila = con.execute("SELECT iban, titular, saldo FROM cuenta").fetchone()
        finally:
            con.close()
        return Cuenta(fila["iban"], fila["titular"], round(fila["saldo"], 2))

    def registrar_movimiento(self, movimiento: Movimiento) -> Cuenta:
        con = self._bd.abrir()
        try:
            with con:  # una sola transacción: el movimiento y el saldo cambian juntos
                con.execute(
                    "INSERT INTO movimientos (fecha, categoria, concepto, comercio, importe) VALUES (?,?,?,?,?)",
                    (movimiento.fecha.isoformat(), movimiento.categoria, movimiento.concepto,
                     movimiento.comercio, movimiento.importe),
                )
                con.execute("UPDATE cuenta SET saldo = saldo + ?", (movimiento.importe,))
            fila = con.execute("SELECT iban, titular, saldo FROM cuenta").fetchone()
        finally:
            con.close()
        return Cuenta(fila["iban"], fila["titular"], round(fila["saldo"], 2))


class RepositorioContactosSqlite:
    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def listar(self) -> list[Contacto]:
        con = self._bd.abrir(solo_lectura=True)
        try:
            return [Contacto(f["nombre"], f["telefono"]) for f in con.execute("SELECT nombre, telefono FROM contactos_bizum")]
        finally:
            con.close()

    def buscar(self, nombre_o_telefono: str) -> Contacto | None:
        con = self._bd.abrir(solo_lectura=True)
        try:
            fila = con.execute(
                "SELECT nombre, telefono FROM contactos_bizum WHERE nombre LIKE ? OR telefono = ?",
                (f"%{nombre_o_telefono}%", nombre_o_telefono),
            ).fetchone()
        finally:
            con.close()
        return Contacto(fila["nombre"], fila["telefono"]) if fila else None


class ConsultorMovimientosSqlite:
    """Ejecuta SELECT sobre una conexión de solo lectura (segunda barrera tras la validación del dominio)."""

    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def ejecutar_select(self, sql: str, limite: int) -> ResultadoConsulta:
        con = self._bd.abrir(solo_lectura=True)
        try:
            cursor = con.execute(sql)
            columnas = [c[0] for c in cursor.description]
            filas = cursor.fetchmany(limite)
        except sqlite3.Error as e:
            raise ConsultaNoPermitida(f"Error SQL: {e}") from e
        finally:
            con.close()
        return ResultadoConsulta(columnas, [list(f) for f in filas], truncado=len(filas) == limite)
