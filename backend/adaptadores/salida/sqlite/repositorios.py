"""Implementaciones SQLite de los puertos bancarios. Cada consulta filtra por `cliente_id`."""
from datetime import date

from ....dominio.modelos import Cliente, Contacto, Cuenta, Movimiento
from .conexion import BaseDeDatos


def _cuenta(fila) -> Cuenta:
    return Cuenta(fila["iban"], fila["titular"], round(fila["saldo"], 2))


class RepositorioCuentaSqlite:
    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def obtener(self, cliente_id: int) -> Cuenta:
        con = self._bd.abrir(solo_lectura=True)
        try:
            return _cuenta(con.execute(
                "SELECT iban, titular, saldo FROM cuenta WHERE cliente_id = ?", (cliente_id,)
            ).fetchone())
        finally:
            con.close()

    def registrar_movimiento(self, cliente_id: int, movimiento: Movimiento) -> Cuenta:
        con = self._bd.abrir()
        try:
            with con:  # una sola transacción: el movimiento y el saldo cambian juntos
                con.execute(
                    "INSERT INTO movimientos (cliente_id, fecha, categoria, concepto, comercio, importe) "
                    "VALUES (?,?,?,?,?,?)",
                    (cliente_id, movimiento.fecha.isoformat(), movimiento.categoria, movimiento.concepto,
                     movimiento.comercio, movimiento.importe),
                )
                con.execute("UPDATE cuenta SET saldo = saldo + ? WHERE cliente_id = ?", (movimiento.importe, cliente_id))
            return _cuenta(con.execute(
                "SELECT iban, titular, saldo FROM cuenta WHERE cliente_id = ?", (cliente_id,)
            ).fetchone())
        finally:
            con.close()

    def bizum_enviado_el(self, cliente_id: int, dia: date) -> float:
        con = self._bd.abrir(solo_lectura=True)
        try:
            total = con.execute(
                "SELECT COALESCE(SUM(-importe), 0) FROM movimientos "
                "WHERE cliente_id = ? AND categoria = 'Bizum' AND importe < 0 AND fecha = ?",
                (cliente_id, dia.isoformat()),
            ).fetchone()[0]
        finally:
            con.close()
        return round(total, 2)

    def envios_bizum_a(self, cliente_id: int, nombre: str) -> int:
        con = self._bd.abrir(solo_lectura=True)
        try:
            return con.execute(
                "SELECT COUNT(*) FROM movimientos WHERE cliente_id = ? AND categoria = 'Bizum' "
                "AND concepto LIKE ?",
                (cliente_id, f"Bizum enviado a {nombre}%"),
            ).fetchone()[0]
        finally:
            con.close()


def _escapar_like(texto: str) -> str:
    """`%` y `_` del usuario (o del LLM) son literales: «%» no debe coincidir con todos los contactos."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class RepositorioContactosSqlite:
    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def listar(self, cliente_id: int) -> list[Contacto]:
        con = self._bd.abrir(solo_lectura=True)
        try:
            return [
                Contacto(f["nombre"], f["telefono"])
                for f in con.execute("SELECT nombre, telefono FROM contactos_bizum WHERE cliente_id = ?", (cliente_id,))
            ]
        finally:
            con.close()

    def buscar(self, cliente_id: int, nombre_o_telefono: str) -> Contacto | None:
        con = self._bd.abrir(solo_lectura=True)
        try:
            fila = con.execute(
                "SELECT nombre, telefono FROM contactos_bizum "
                "WHERE cliente_id = ? AND (nombre LIKE ? ESCAPE '\\' OR telefono = ?)",
                (cliente_id, f"%{_escapar_like(nombre_o_telefono)}%", nombre_o_telefono),
            ).fetchone()
        finally:
            con.close()
        return Contacto(fila["nombre"], fila["telefono"]) if fila else None


class RepositorioClientesSqlite:
    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def buscar_por_usuario(self, usuario: str) -> tuple[Cliente, str] | None:
        con = self._bd.abrir(solo_lectura=True)
        try:
            f = con.execute(
                "SELECT id, usuario, nombre, telefono, hash_contrasena, "
                "id IN (SELECT cliente_id FROM administradores) AS es_admin FROM clientes WHERE usuario = ?", (usuario,)
            ).fetchone()
        finally:
            con.close()
        return (Cliente(f["id"], f["usuario"], f["nombre"], f["telefono"], bool(f["es_admin"])), f["hash_contrasena"]) if f else None

    def listar(self) -> list[Cliente]:
        con = self._bd.abrir(solo_lectura=True)
        try:
            filas = con.execute(
                "SELECT id, usuario, nombre, telefono FROM clientes "
                "WHERE id NOT IN (SELECT cliente_id FROM administradores) ORDER BY id"
            ).fetchall()
        finally:
            con.close()
        return [Cliente(f["id"], f["usuario"], f["nombre"], f["telefono"]) for f in filas]

    def obtener(self, cliente_id: int) -> Cliente | None:
        con = self._bd.abrir(solo_lectura=True)
        try:
            f = con.execute(
                "SELECT id, usuario, nombre, telefono, id IN (SELECT cliente_id FROM administradores) AS es_admin "
                "FROM clientes WHERE id = ?", (cliente_id,)
            ).fetchone()
        finally:
            con.close()
        return Cliente(f["id"], f["usuario"], f["nombre"], f["telefono"], bool(f["es_admin"])) if f else None
