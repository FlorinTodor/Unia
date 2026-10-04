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
import time

from ....dominio.errores import ConsultaNoPermitida
from ....dominio.modelos import ResultadoConsulta
from .conexion import BaseDeDatos

_TABLAS = {
    "movimientos": ("id, fecha, categoria, concepto, comercio, importe", "id INTEGER, fecha TEXT, categoria TEXT, concepto TEXT, comercio TEXT, importe REAL"),
    "cuenta": ("iban, titular, saldo", "iban TEXT, titular TEXT, saldo REAL"),
    "contactos_bizum": ("nombre, telefono", "nombre TEXT, telefono TEXT"),
}

SEGUNDOS_MAXIMOS_CONSULTA = 2.0  # una consulta del LLM (p. ej. un producto cartesiano) no puede bloquear el servidor

_ACCIONES_PERMITIDAS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}

# Funciones que fabrican datos de la nada (`length(randomblob(900000000))` reservaría ~900 MB) o formatean con
# anchos arbitrarios (`printf('%1000000000d', 1)`): el LLM no las necesita para consultar movimientos.
_FUNCIONES_PROHIBIDAS = frozenset({
    "randomblob", "zeroblob", "printf", "format",
    # superficie de la propia SQLite que el LLM no necesita: registrar tokenizadores (puntero crudo), cargar extensiones
    # e inspeccionar cómo se compiló
    "fts3_tokenizer", "load_extension", "sqlite_compileoption_get", "sqlite_compileoption_used",
})
MAX_BYTES_VALOR = 4_000  # SQLITE_LIMIT_LENGTH: tamaño máximo de una cadena o blob (un movimiento no se acerca)
MAX_COLUMNAS = 32  # SQLITE_LIMIT_COLUMN: `hex(hex(..))` × 50 columnas × 60 filas llegaba a cientos de MB
MAX_BYTES_RESPUESTA = 200_000  # tope del conjunto de filas: se lee fila a fila y se aborta al pasarlo
MAX_CARACTERES_SQL = 10_000  # SQLITE_LIMIT_SQL_LENGTH


def _autorizador(accion, arg1, arg2, _base, _origen):
    if accion == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or "").lower() in _FUNCIONES_PROHIBIDAS else sqlite3.SQLITE_OK
    if accion in _ACCIONES_PERMITIDAS:
        return sqlite3.SQLITE_OK
    if accion == sqlite3.SQLITE_READ:
        # en la conexión solo existen las tres tablas de la copia (y ATTACH está denegado): lo único que hay que vetar
        # es el catálogo interno. Las CTE también aparecen como lectura (con su nombre), de ahí que no baste la lista.
        return sqlite3.SQLITE_DENY if (arg1 or "").lower().startswith("sqlite_") else sqlite3.SQLITE_OK
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
            if hasattr(con, "setconfig"):  # Python 3.12+; fts3_tokenizer permite leer/escribir punteros si está activo
                try:
                    con.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_FTS3_TOKENIZER, False)
                except (AttributeError, sqlite3.Error):
                    pass  # la constante o el ajuste no existen en esta SQLite: el autorizador ya veta la función
            con.set_authorizer(_autorizador)
            con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_BYTES_VALOR)  # tras la copia de datos, que no se ve afectada
            con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_CARACTERES_SQL)
            con.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, MAX_COLUMNAS)
            limite_de_tiempo = time.monotonic() + SEGUNDOS_MAXIMOS_CONSULTA
            # el manejador se invoca cada 10.000 instrucciones de la VM; devolver 1 aborta la consulta
            con.set_progress_handler(lambda: 1 if time.monotonic() > limite_de_tiempo else 0, 10_000)
            cursor = con.execute(sql)
            columnas = [c[0] for c in cursor.description]
            filas = []
            bytes_leidos = 0
            while len(filas) < limite and (fila := cursor.fetchone()) is not None:
                bytes_leidos += sum(len(v) if isinstance(v, (str, bytes)) else 8 for v in fila)
                if bytes_leidos > MAX_BYTES_RESPUESTA:
                    raise ConsultaNoPermitida("El resultado es demasiado grande: pide menos columnas o filas.")
                filas.append(fila)
        except sqlite3.Error as e:
            if "interrupted" in str(e):
                raise ConsultaNoPermitida("La consulta tarda demasiado: simplifícala (sin cruces ni recursión sin límite).") from e
            raise ConsultaNoPermitida(f"Error SQL: {e}") from e
        finally:
            con.close()
        return ResultadoConsulta(columnas, [list(f) for f in filas], truncado=len(filas) == limite)
