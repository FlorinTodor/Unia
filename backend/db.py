"""Base de datos SQLite con datos bancarios ficticios.

Los movimientos se generan proceduralmente con patrones realistas de un
usuario español (nómina, alquiler, suscripciones, supermercados, Bizum...).
Semilla fija para que la demo sea reproducible.
"""
import random
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

RUTA_DATOS = Path(__file__).resolve().parent.parent / "data"
RUTA_DB = RUTA_DATOS / "banco.db"

TITULAR = "Alex García"
IBAN = "ES21 2103 0000 1122 3344 5566"

_PALABRAS_PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|pragma|create|replace|vacuum|reindex)\b",
    re.IGNORECASE,
)


def _conexion(solo_lectura: bool = False) -> sqlite3.Connection:
    if solo_lectura:
        con = sqlite3.connect(f"file:{RUTA_DB}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(RUTA_DB)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------- generación

SUPERMERCADOS = ["Mercadona", "Carrefour", "Lidl", "Dia", "Alcampo"]
RESTAURANTES = ["Bar Manolo", "La Trattoria", "Sushi Go", "Burger King", "100 Montaditos", "El Rincón de Ana"]
GASOLINERAS = ["Repsol", "Cepsa", "BP"]
TIENDAS_ROPA = ["Zara", "Primark", "Decathlon", "Pull&Bear"]
OCIO = ["Cine Kinépolis", "Bolera Ozone", "Entradas.com", "Steam"]
FARMACIAS = ["Farmacia Central", "Farmacia San Juan"]
CONTACTOS = [
    ("María López", "600111222"),
    ("Pablo Ruiz", "611333444"),
    ("Lucía Fernández", "622555666"),
    ("Javi Moreno", "633777888"),
]


def _generar_movimientos(desde: date, hasta: date) -> list[tuple[str, str, str, str, float]]:
    """Devuelve tuplas (fecha, categoria, concepto, comercio, importe)."""
    rng = random.Random(42)
    movs: list[tuple[str, str, str, str, float]] = []

    def add(d: date, cat: str, concepto: str, comercio: str, importe: float):
        # nunca generar movimientos fuera del rango (p. ej. recibos con fecha futura)
        if not (desde <= d <= hasta):
            return
        movs.append((d.isoformat(), cat, concepto, comercio, round(importe, 2)))

    # Mensuales fijos
    mes = date(desde.year, desde.month, 1)
    while mes <= hasta:
        def dia(n):
            return mes.replace(day=n)

        if dia(1) >= desde:
            add(dia(1), "Nómina", "Nómina Tecnosur SL", "Tecnosur SL", 1850.00)
            add(dia(2), "Vivienda", "Alquiler piso c/ Recogidas", "Inmobiliaria Genil", -650.00)
        if dia(5) <= hasta and dia(5) >= desde:
            add(dia(5), "Suscripciones", "Fibra + móvil", "Digi", -34.90)
            add(dia(3), "Deporte", "Cuota mensual gimnasio", "Basic-Fit", -29.90)
            add(dia(10), "Vivienda", "Factura electricidad", "Endesa", -round(rng.uniform(42, 78), 2))
            add(dia(15), "Suscripciones", "Netflix", "Netflix", -12.99)
            add(dia(20), "Suscripciones", "Spotify Premium", "Spotify", -10.99)
            if mes.month % 2 == 0:
                add(dia(12), "Vivienda", "Factura agua", "Emasagra", -round(rng.uniform(25, 38), 2))
        # siguiente mes
        mes = (mes.replace(day=28) + timedelta(days=5)).replace(day=1)

    # Variables día a día
    d = desde
    while d <= hasta:
        if rng.random() < 0.30:
            add(d, "Supermercado", "Compra alimentación", rng.choice(SUPERMERCADOS), -rng.uniform(8, 70))
        if d.weekday() >= 4 and rng.random() < 0.35:
            add(d, "Restaurantes", "Comida/cena fuera", rng.choice(RESTAURANTES), -rng.uniform(9, 55))
        if rng.random() < 0.07:
            add(d, "Transporte", "Combustible", rng.choice(GASOLINERAS), -rng.uniform(30, 65))
        if rng.random() < 0.04:
            add(d, "Ropa", "Compra ropa/deporte", rng.choice(TIENDAS_ROPA), -rng.uniform(12, 75))
        if rng.random() < 0.06:
            add(d, "Ocio", "Ocio y entretenimiento", rng.choice(OCIO), -rng.uniform(6, 40))
        if rng.random() < 0.04:
            add(d, "Salud", "Farmacia", rng.choice(FARMACIAS), -rng.uniform(4, 28))
        if rng.random() < 0.04:
            add(d, "Compras online", "Pedido online", "Amazon", -rng.uniform(9, 90))
        if rng.random() < 0.08:
            nombre, _tel = rng.choice(CONTACTOS)
            if rng.random() < 0.55:
                add(d, "Bizum", f"Bizum enviado a {nombre}", "Bizum", -rng.uniform(5, 60))
            else:
                add(d, "Bizum", f"Bizum recibido de {nombre}", "Bizum", rng.uniform(5, 60))
        d += timedelta(days=1)

    movs.sort(key=lambda m: m[0])
    return movs


def inicializar(forzar: bool = False) -> None:
    """Crea y puebla la base de datos si no existe."""
    RUTA_DATOS.mkdir(exist_ok=True)
    if RUTA_DB.exists() and not forzar:
        return
    if RUTA_DB.exists():
        RUTA_DB.unlink()

    con = _conexion()
    con.executescript(
        """
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
    )

    hoy = date.today()
    movs = _generar_movimientos(hoy - timedelta(days=365), hoy)
    con.executemany(
        "INSERT INTO movimientos (fecha, categoria, concepto, comercio, importe) VALUES (?,?,?,?,?)",
        movs,
    )
    saldo_inicial = 1200.00
    saldo = saldo_inicial + sum(m[4] for m in movs)
    con.execute("INSERT INTO cuenta (iban, titular, saldo) VALUES (?,?,?)", (IBAN, TITULAR, round(saldo, 2)))
    con.executemany("INSERT INTO contactos_bizum (nombre, telefono) VALUES (?,?)", CONTACTOS)
    con.commit()
    con.close()


# ---------------------------------------------------------------- operaciones

def obtener_saldo() -> dict:
    con = _conexion(solo_lectura=True)
    fila = con.execute("SELECT iban, titular, saldo FROM cuenta").fetchone()
    con.close()
    return {"iban": fila["iban"], "titular": fila["titular"], "saldo": round(fila["saldo"], 2)}


def listar_contactos() -> list[dict]:
    con = _conexion(solo_lectura=True)
    filas = con.execute("SELECT nombre, telefono FROM contactos_bizum").fetchall()
    con.close()
    return [dict(f) for f in filas]


def transferir_bizum(destinatario: str, importe: float, concepto: str = "") -> dict:
    if importe <= 0:
        return {"ok": False, "error": "El importe debe ser mayor que 0."}
    if importe > 1000:
        return {"ok": False, "error": "Bizum permite un máximo de 1.000 € por operación."}

    con = _conexion()
    contacto = con.execute(
        "SELECT nombre, telefono FROM contactos_bizum WHERE nombre LIKE ? OR telefono = ?",
        (f"%{destinatario}%", destinatario),
    ).fetchone()
    if contacto is None:
        disponibles = [c["nombre"] for c in listar_contactos()]
        con.close()
        return {"ok": False, "error": f"No encuentro el contacto '{destinatario}'.", "contactos_disponibles": disponibles}

    saldo = con.execute("SELECT saldo FROM cuenta").fetchone()["saldo"]
    if saldo < importe:
        con.close()
        return {"ok": False, "error": f"Saldo insuficiente ({saldo:.2f} €) para enviar {importe:.2f} €."}

    detalle = f"Bizum enviado a {contacto['nombre']}" + (f" — {concepto}" if concepto else "")
    con.execute(
        "INSERT INTO movimientos (fecha, categoria, concepto, comercio, importe) VALUES (?,?,?,?,?)",
        (date.today().isoformat(), "Bizum", detalle, "Bizum", -round(importe, 2)),
    )
    con.execute("UPDATE cuenta SET saldo = saldo - ?", (round(importe, 2),))
    con.commit()
    nuevo_saldo = con.execute("SELECT saldo FROM cuenta").fetchone()["saldo"]
    con.close()
    return {
        "ok": True,
        "destinatario": contacto["nombre"],
        "telefono": contacto["telefono"],
        "importe": round(importe, 2),
        "concepto": concepto,
        "nuevo_saldo": round(nuevo_saldo, 2),
    }


def ejecutar_select(sql: str, limite: int = 60) -> dict:
    """Ejecuta una consulta de solo lectura generada por el LLM, con validación."""
    limpia = sql.strip().rstrip(";").strip()
    if ";" in limpia:
        return {"ok": False, "error": "Solo se permite una única sentencia SQL."}
    if not limpia.lower().startswith(("select", "with")):
        return {"ok": False, "error": "Solo se permiten consultas SELECT."}
    if _PALABRAS_PROHIBIDAS.search(limpia):
        return {"ok": False, "error": "La consulta contiene palabras no permitidas."}

    try:
        con = _conexion(solo_lectura=True)
        cursor = con.execute(limpia)
        columnas = [c[0] for c in cursor.description]
        filas = cursor.fetchmany(limite)
        con.close()
    except sqlite3.Error as e:
        return {"ok": False, "error": f"Error SQL: {e}"}

    return {
        "ok": True,
        "columnas": columnas,
        "filas": [list(f) for f in filas],
        "num_filas": len(filas),
        "truncado": len(filas) == limite,
    }
