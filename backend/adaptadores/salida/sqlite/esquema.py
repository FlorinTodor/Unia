"""Esquema de la base de datos (varios clientes) y carga inicial con datos ficticios."""
from datetime import date, timedelta

from ....aplicacion.puertos.infraestructura import Reloj
from ....aplicacion.puertos.seguridad import Hasheador
from .conexion import BaseDeDatos
from .generador import generar_movimientos
from .perfiles import PERFILES

VERSION_ESQUEMA = 2  # súbela al cambiar el esquema o el historial: la base se regenera sola
ANOS_HISTORIAL = 2  # para poder comparar «este año» con «el año pasado»

DDL = """
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    telefono TEXT NOT NULL,
    hash_contrasena TEXT NOT NULL
);
CREATE TABLE cuenta (
    iban TEXT PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    titular TEXT NOT NULL,
    saldo REAL NOT NULL
);
CREATE TABLE movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    fecha TEXT NOT NULL,          -- YYYY-MM-DD
    categoria TEXT NOT NULL,
    concepto TEXT NOT NULL,
    comercio TEXT NOT NULL,
    importe REAL NOT NULL         -- negativo = gasto, positivo = ingreso
);
CREATE INDEX idx_movimientos_cliente ON movimientos(cliente_id, fecha);
CREATE TABLE contactos_bizum (
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    nombre TEXT NOT NULL,
    telefono TEXT NOT NULL,
    PRIMARY KEY (cliente_id, nombre)
);
CREATE TABLE auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    momento TEXT NOT NULL,
    cliente_id INTEGER,
    accion TEXT NOT NULL,
    detalle TEXT NOT NULL,
    resultado TEXT NOT NULL
);
"""

# Tablas añadidas después de la versión 2: IF NOT EXISTS para crearlas también en bases ya existentes
# sin regenerarlas (regenerar borraría los Bizum hechos desde el chat).
DDL_COMPLEMENTARIO = """
CREATE TABLE IF NOT EXISTS uso_ia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    momento TEXT NOT NULL,           -- ISO 8601
    cliente_id INTEGER NOT NULL,
    proveedor TEXT NOT NULL,
    modelo TEXT NOT NULL,
    tokens_entrada INTEGER NOT NULL,
    tokens_salida INTEGER NOT NULL,
    estimado INTEGER NOT NULL        -- 1 si el proveedor no informó y se calculó
);
CREATE INDEX IF NOT EXISTS idx_uso_cliente ON uso_ia(cliente_id, momento);
"""


def _esquema_actual(bd: BaseDeDatos) -> bool:
    con = bd.abrir(solo_lectura=True)
    try:
        tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        version = con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()
    return version == VERSION_ESQUEMA and {"clientes", "cuenta", "movimientos", "contactos_bizum", "auditoria"} <= tablas


def _crear_tablas_complementarias(bd: BaseDeDatos) -> None:
    con = bd.abrir()
    try:
        con.executescript(DDL_COMPLEMENTARIO)
    finally:
        con.close()


def inicializar(bd: BaseDeDatos, reloj: Reloj, hasheador: Hasheador, forzar: bool = False) -> None:
    """Crea y puebla la base de datos si no existe o tiene un esquema antiguo.

    `forzar` la regenera siempre (borra los Bizum hechos desde el chat). Si ya existe, solo
    desplaza las fechas para que el último movimiento sea de hoy.
    """
    bd.ruta.parent.mkdir(parents=True, exist_ok=True)
    if bd.ruta.exists() and not forzar and _esquema_actual(bd):
        _crear_tablas_complementarias(bd)
        desplazar_fechas(bd, reloj)
        return
    bd.ruta.unlink(missing_ok=True)

    hoy = reloj.hoy()
    con = bd.abrir()
    con.executescript(DDL + DDL_COMPLEMENTARIO)
    con.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
    for cliente_id, perfil in enumerate(PERFILES, start=1):
        movs = generar_movimientos(perfil, hoy - timedelta(days=365 * ANOS_HISTORIAL), hoy)
        con.execute(
            "INSERT INTO clientes (id, usuario, nombre, telefono, hash_contrasena) VALUES (?,?,?,?,?)",
            (cliente_id, perfil.usuario, perfil.nombre, perfil.telefono, hasheador.hashear(perfil.contrasena)),
        )
        con.executemany(
            "INSERT INTO movimientos (cliente_id, fecha, categoria, concepto, comercio, importe) VALUES (?,?,?,?,?,?)",
            [(cliente_id, m.fecha.isoformat(), m.categoria, m.concepto, m.comercio, m.importe) for m in movs],
        )
        con.execute(
            "INSERT INTO cuenta (iban, cliente_id, titular, saldo) VALUES (?,?,?,?)",
            (perfil.iban, cliente_id, perfil.nombre, perfil.saldo_actual),
        )
        con.executemany(
            "INSERT INTO contactos_bizum (cliente_id, nombre, telefono) VALUES (?,?,?)",
            [(cliente_id, c.nombre, c.telefono) for c in perfil.contactos],
        )
    con.commit()
    con.close()


def desplazar_fechas(bd: BaseDeDatos, reloj: Reloj) -> int:
    """Adelanta todos los movimientos los días necesarios para que el último sea de hoy.

    Así el «último mes» de la demo siempre es el actual, sea cual sea el día en que se arranque.
    Devuelve los días desplazados (0 si no hacía falta).
    """
    con = bd.abrir()
    try:
        ultima = con.execute("SELECT MAX(fecha) FROM movimientos").fetchone()[0]
        if ultima is None:
            return 0
        dias = (reloj.hoy() - date.fromisoformat(ultima)).days
        if dias <= 0:
            return 0
        with con:
            con.execute("UPDATE movimientos SET fecha = date(fecha, ?)", (f"+{dias} days",))
        return dias
    finally:
        con.close()

