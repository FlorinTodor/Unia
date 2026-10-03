"""Consulta NL→SQL aislada por cliente.

El SQL lo escribe el LLM, así que no se le puede confiar nada. Barreras, de fuera adentro:
1. El dominio ya ha validado que es un único SELECT (reglas.validar_consulta_solo_lectura).
2. Las filas del cliente se copian a una base de datos EN MEMORIA y la consulta se ejecuta ahí.
   Los datos de otros clientes, la tabla `clientes` (con los hashes de contraseña) y la
   auditoría sencillamente no existen en esa conexión: no hay nada que filtrar ni que saltarse.
3. Un *authorizer* de SQLite solo deja leer las tres tablas de la copia: deniega ATTACH (que
   permitiría abrir el fichero real), PRAGMA, sqlite_master y cualquier otra cosa.

(Primero se probó con vistas temporales + authorizer sobre la base real: una CTE con el mismo
nombre que la vista engañaba al authorizer. Por eso los datos ajenos no deben estar presentes.)
"""
import sqlite3

from ....dominio.errores import ConsultaNoPermitida
from ....dominio.modelos import ResultadoConsulta
from .conexion import BaseDeDatos

_TABLAS = {
    "movimientos": ("id, fecha, categoria, concepto, comercio, importe", "id INTEGER, fecha TEXT, categoria TEXT, concepto TEXT, comercio TEXT, importe REAL"),
    "cuenta": ("iban, titular, saldo", "iban TEXT, titular TEXT, saldo REAL"),
    "contactos_bizum": ("nombre, telefono", "nombre TEXT, telefono TEXT"),
}

_ACCIONES_PERMITIDAS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE, sqlite3.SQLITE_FUNCTION}


def _autorizador(accion, arg1, _arg2, _base, _origen):
    if accion in _ACCIONES_PERMITIDAS:
        return sqlite3.SQLITE_OK
    if accion == sqlite3.SQLITE_READ and arg1 in _TABLAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY  # ATTACH, PRAGMA, sqlite_master, escrituras...


class ConsultorMovimientosSqlite:
    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def _copiar_datos_del_cliente(self, cliente_id: int) -> sqlite3.Connection:
        copia = sqlite3.connect(":memory:")
        real = self._bd.abrir(solo_lectura=True)
        try:
            for tabla, (columnas, definicion) in _TABLAS.items():
                copia.execute(f"CREATE TABLE {tabla} ({definicion})")
                filas = real.execute(f"SELECT {columnas} FROM {tabla} WHERE cliente_id = ?", (cliente_id,)).fetchall()
                marcas = ",".join("?" * len(columnas.split(",")))
                copia.executemany(f"INSERT INTO {tabla} VALUES ({marcas})", [tuple(f) for f in filas])
        finally:
            real.close()
        return copia

    def ejecutar_select(self, cliente_id: int, sql: str, limite: int) -> ResultadoConsulta:
        if not isinstance(cliente_id, int) or isinstance(cliente_id, bool):
            raise TypeError("cliente_id debe ser un entero")
        con = self._copiar_datos_del_cliente(cliente_id)
        try:
            con.set_authorizer(_autorizador)
            cursor = con.execute(sql)
            columnas = [c[0] for c in cursor.description]
            filas = cursor.fetchmany(limite)
        except sqlite3.Error as e:
            raise ConsultaNoPermitida(f"Error SQL: {e}") from e
        finally:
            con.close()
        return ResultadoConsulta(columnas, [list(f) for f in filas], truncado=len(filas) == limite)
