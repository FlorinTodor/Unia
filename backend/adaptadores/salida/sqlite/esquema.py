"""Esquema de la base de datos y carga inicial con datos ficticios."""
from datetime import timedelta

from ....aplicacion.puertos.infraestructura import Reloj
from .conexion import BaseDeDatos
from .generador import CONTACTOS, IBAN, SALDO_INICIAL, TITULAR, generar_movimientos

DDL = """
CREATE TABLE cuenta (
    iban TEXT PRIMARY KEY,
    titular TEXT NOT NULL,
    saldo REAL NOT NULL
);
CREATE TABLE movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,          -- YYYY-MM-DD
    categoria TEXT NOT NULL,
    concepto TEXT NOT NULL,
    comercio TEXT NOT NULL,
    importe REAL NOT NULL         -- negativo = gasto, positivo = ingreso
);
CREATE TABLE contactos_bizum (
    nombre TEXT PRIMARY KEY,
    telefono TEXT NOT NULL
);
"""


def inicializar(bd: BaseDeDatos, reloj: Reloj, forzar: bool = False) -> None:
    """Crea y puebla la base de datos si no existe (`forzar` la regenera: borra los Bizum hechos)."""
    bd.ruta.parent.mkdir(parents=True, exist_ok=True)
    if bd.ruta.exists() and not forzar:
        return
    bd.ruta.unlink(missing_ok=True)

    hoy = reloj.hoy()
    movs = generar_movimientos(hoy - timedelta(days=365), hoy)
    con = bd.abrir()
    con.executescript(DDL)
    con.executemany(
        "INSERT INTO movimientos (fecha, categoria, concepto, comercio, importe) VALUES (?,?,?,?,?)",
        [(m.fecha.isoformat(), m.categoria, m.concepto, m.comercio, m.importe) for m in movs],
    )
    saldo = SALDO_INICIAL + sum(m.importe for m in movs)
    con.execute("INSERT INTO cuenta (iban, titular, saldo) VALUES (?,?,?)", (IBAN, TITULAR, round(saldo, 2)))
    con.executemany("INSERT INTO contactos_bizum (nombre, telefono) VALUES (?,?)", [(c.nombre, c.telefono) for c in CONTACTOS])
    con.commit()
    con.close()
