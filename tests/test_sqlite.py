"""Integración con SQLite real: esquema multicliente, fechas, repositorios y AISLAMIENTO de datos."""
import sqlite3
from datetime import date, datetime

import pytest

from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.adaptadores.salida.sqlite import esquema
from backend.adaptadores.salida.sqlite.auditoria import AuditoriaSqlite
from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.adaptadores.salida.sqlite.consultor import ConsultorMovimientosSqlite
from backend.adaptadores.salida.sqlite.repositorios import (
    RepositorioClientesSqlite,
    RepositorioContactosSqlite,
    RepositorioCuentaSqlite,
)
from backend.aplicacion.casos_uso.banco import ConsultarMovimientos
from backend.dominio.errores import ConsultaNoPermitida
from backend.dominio.modelos import Movimiento
from tests.fakes import ALEX, ANA, AuditoriaEnMemoria, RelojFijo

HASHEADOR = HasheadorScrypt()


@pytest.fixture(scope="module")
def bd_base(tmp_path_factory):
    bd = BaseDeDatos(tmp_path_factory.mktemp("bd") / "banco.db")
    esquema.inicializar(bd, RelojFijo(), HASHEADOR)
    return bd


@pytest.fixture
def bd(tmp_path, bd_base):
    """Copia de la base de datos de cada test para que las escrituras no se contaminen."""
    copia = BaseDeDatos(tmp_path / "copia.db")
    copia.ruta.write_bytes(bd_base.ruta.read_bytes())
    return copia


def consultar(bd, cliente, sql):
    return ConsultorMovimientosSqlite(bd).ejecutar_select(cliente.id, sql, 60)


# ------------------------------------------------------------------ esquema y datos

def test_cuatro_clientes_con_datos_distintos(bd):
    con = bd.abrir(solo_lectura=True)
    clientes = con.execute("SELECT id, usuario FROM clientes ORDER BY id").fetchall()
    assert [c["usuario"] for c in clientes] == ["alex", "ana", "marta", "jose"]
    saldos = {f["cliente_id"]: f["saldo"] for f in con.execute("SELECT cliente_id, saldo FROM cuenta")}
    assert len(set(saldos.values())) == 4
    for cid in saldos:
        n, hasta = con.execute("SELECT COUNT(*), MAX(fecha) FROM movimientos WHERE cliente_id = ?", (cid,)).fetchone()
        assert n > 100 and hasta <= "2026-10-03"
    con.close()


def test_las_contrasenas_se_guardan_con_hash_nunca_en_claro(bd):
    con = bd.abrir(solo_lectura=True)
    hashes = [f[0] for f in con.execute("SELECT hash_contrasena FROM clientes")]
    con.close()
    assert all(h.startswith("scrypt$") for h in hashes)
    assert not any("2026" in h for h in hashes)
    cliente, hash_alex = RepositorioClientesSqlite(bd).buscar_por_usuario("alex")
    assert HASHEADOR.verificar("alex2026", hash_alex) and cliente.nombre == "Alex García"


def test_inicializar_es_idempotente(bd):
    antes = RepositorioCuentaSqlite(bd).obtener(1)
    esquema.inicializar(bd, RelojFijo(), HASHEADOR)
    assert RepositorioCuentaSqlite(bd).obtener(1) == antes


def test_un_esquema_antiguo_se_regenera(tmp_path):
    bd = BaseDeDatos(tmp_path / "viejo.db")
    con = sqlite3.connect(bd.ruta)
    con.executescript("CREATE TABLE cuenta (iban TEXT, titular TEXT, saldo REAL); INSERT INTO cuenta VALUES ('x','y',1);")
    con.close()
    esquema.inicializar(bd, RelojFijo(), HASHEADOR)
    assert RepositorioClientesSqlite(bd).buscar_por_usuario("ana") is not None


def test_las_fechas_se_desplazan_para_que_el_ultimo_movimiento_sea_hoy(bd):
    reloj = RelojFijo(datetime(2026, 11, 20, 9, 0))  # han pasado 48 días desde 3-oct
    dias = esquema.desplazar_fechas(bd, reloj)
    assert dias == 48
    con = bd.abrir(solo_lectura=True)
    assert con.execute("SELECT MAX(fecha) FROM movimientos").fetchone()[0] <= "2026-11-20"
    assert con.execute("SELECT MAX(fecha) FROM movimientos").fetchone()[0] >= "2026-11-15"
    con.close()
    assert esquema.desplazar_fechas(bd, reloj) == 0  # segunda vez: nada que hacer


# ------------------------------------------------------------------ repositorios por cliente

def test_bizum_registrado_solo_afecta_a_su_cliente(bd):
    cuentas = RepositorioCuentaSqlite(bd)
    antes_alex, antes_ana = cuentas.obtener(ALEX.id).saldo, cuentas.obtener(ANA.id).saldo
    cuentas.registrar_movimiento(ALEX.id, Movimiento(date(2026, 10, 3), "Bizum", "Bizum enviado a María López", "Bizum", -20))
    assert cuentas.obtener(ALEX.id).saldo == round(antes_alex - 20, 2)
    assert cuentas.obtener(ANA.id).saldo == antes_ana
    assert cuentas.bizum_enviado_el(ALEX.id, date(2026, 10, 3)) == 20 and cuentas.bizum_enviado_el(ANA.id, date(2026, 10, 3)) == 0
    assert cuentas.envios_bizum_a(ALEX.id, "María López") >= 1 and cuentas.envios_bizum_a(ANA.id, "María López") == 0


def test_cada_cliente_ve_solo_sus_contactos(bd):
    agenda = RepositorioContactosSqlite(bd)
    assert agenda.buscar(ALEX.id, "pablo").telefono == "611333444"
    assert agenda.buscar(ANA.id, "pablo") is None
    assert agenda.buscar(ANA.id, "mamá").nombre == "Mamá"
    assert {c.nombre for c in agenda.listar(ALEX.id)}.isdisjoint({c.nombre for c in agenda.listar(ANA.id)})


# ------------------------------------------------------------------ aislamiento del NL→SQL

def test_el_cliente_solo_ve_sus_movimientos_con_sql_normal(bd):
    r = consultar(bd, ANA, "SELECT COUNT(*), SUM(importe) FROM movimientos")
    con = bd.abrir(solo_lectura=True)
    esperado = con.execute("SELECT COUNT(*), SUM(importe) FROM movimientos WHERE cliente_id = 2").fetchone()
    total = con.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]
    con.close()
    assert r.filas[0][0] == esperado[0] < total


def test_la_copia_de_ana_no_contiene_nada_de_otros_clientes_aunque_el_sql_lo_intente(bd):
    """Aunque la consulta se salte todo filtro textual, los datos de Alex no existen en la conexión de Ana."""
    nombres_de_alex = {"María López", "Pablo Ruiz", "Lucía Fernández", "Javi Moreno"}
    filas = consultar(bd, ANA, "SELECT concepto FROM movimientos UNION ALL SELECT nombre FROM contactos_bizum").filas
    texto = " ".join(f[0] for f in filas)
    assert not any(n in texto for n in nombres_de_alex)


def test_la_vista_cuenta_y_contactos_son_del_cliente(bd):
    assert consultar(bd, ANA, "SELECT titular FROM cuenta").filas == [["Ana Ruiz"]]
    assert consultar(bd, ALEX, "SELECT COUNT(*) FROM contactos_bizum").filas == [[4]]


@pytest.mark.parametrize("sql", [
    "SELECT hash_contrasena FROM clientes",                 # robar los hashes de contraseña
    "SELECT usuario, nombre FROM clientes",
    "SELECT * FROM auditoria",
    "SELECT name, sql FROM sqlite_master",                  # descubrir el esquema real
    "SELECT * FROM sqlite_temp_master",
    "SELECT * FROM temp.movimientos",                       # no hay esquema temp con datos
    "SELECT * FROM movimientos WHERE cliente_id = 1",       # la columna ni siquiera existe en su copia
    "SELECT * FROM movimientos UNION SELECT id, cliente_id, fecha, categoria, concepto, comercio FROM clientes",
])
def test_intentos_de_leer_tablas_internas_o_columnas_ocultas_fallan(bd, sql):
    with pytest.raises(ConsultaNoPermitida):
        consultar(bd, ANA, sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM main.movimientos",                       # nombre cualificado para saltarse un filtro
    "SELECT * FROM main.cuenta",
    "WITH movimientos AS (SELECT * FROM main.movimientos) SELECT * FROM movimientos",   # CTE que suplanta la tabla
    "WITH cuenta AS (SELECT * FROM main.cuenta) SELECT * FROM cuenta",
])
def test_los_trucos_para_saltarse_filtros_solo_devuelven_datos_propios(bd, sql):
    """Estos SQL no son un error: simplemente no hay datos ajenos que ver en la conexión de Ana."""
    propios = consultar(bd, ANA, "SELECT COUNT(*) FROM movimientos").filas[0][0]
    r = consultar(bd, ANA, sql)
    assert r.filas and all("Alex" not in str(f) and "María López" not in str(f) for f in r.filas)
    if "movimientos" in sql and "temp" not in sql:
        assert len(r.filas) == min(propios, 60)


def test_una_subconsulta_escalar_cuenta_solo_las_filas_del_cliente(bd):
    propios = consultar(bd, ANA, "SELECT COUNT(*) FROM movimientos").filas[0][0]
    assert consultar(bd, ANA, "SELECT (SELECT COUNT(*) FROM main.movimientos)").filas == [[propios]]
    # y el total real de la base de datos es mayor: hay datos de otros clientes que no se ven
    con = bd.abrir(solo_lectura=True)
    assert con.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0] > propios
    con.close()


@pytest.mark.parametrize("sql", [
    "PRAGMA table_info(movimientos)",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "DELETE FROM movimientos",
    "INSERT INTO movimientos VALUES (1)",
    "CREATE TABLE x (a)",
    "DROP VIEW movimientos",
    "UPDATE cuenta SET saldo = 1e9",
])
def test_la_conexion_rechaza_cualquier_escritura_o_instruccion_peligrosa_aunque_falle_la_validacion(bd, sql):
    """Segunda y tercera barrera: aunque el dominio no las hubiera parado, SQLite las deniega."""
    with pytest.raises(ConsultaNoPermitida):
        consultar(bd, ANA, sql)
    assert RepositorioCuentaSqlite(bd).obtener(2).saldo != 1e9


def test_el_id_del_cliente_debe_ser_un_entero():
    with pytest.raises(TypeError):
        ConsultorMovimientosSqlite(BaseDeDatos()).ejecutar_select("1 OR 1=1", "SELECT 1", 60)  # type: ignore[arg-type]


def test_funciones_y_agregaciones_normales_siguen_funcionando(bd):
    r = consultar(bd, ALEX, "SELECT strftime('%Y-%m', fecha) AS mes, SUM(-importe) FROM movimientos WHERE importe < 0 GROUP BY mes ORDER BY mes DESC LIMIT 3")
    assert len(r.filas) == 3 and r.columnas[0] == "mes"
    assert consultar(bd, ALEX, "SELECT * FROM movimientos").truncado


def test_consulta_rechazada_queda_en_la_auditoria(bd):
    auditoria = AuditoriaSqlite(bd, RelojFijo())
    consulta = ConsultarMovimientos(ConsultorMovimientosSqlite(bd), auditoria)
    with pytest.raises(ConsultaNoPermitida):
        consulta(ANA, "SELECT * FROM clientes")  # la para el aislamiento: la tabla no existe en su copia
    with pytest.raises(ConsultaNoPermitida):
        consulta(ANA, "DROP TABLE cuenta")  # la para el dominio antes de llegar a la base de datos
    assert [a["accion"] for a in auditoria.ultimos(ANA.id)] == ["consulta_rechazada", "consulta_rechazada"]


def test_hay_dos_anos_de_historial_para_comparar_este_ano_con_el_pasado(bd):
    """Antes solo había 12 meses y «ingresos de 2025» salía con solo dos meses."""
    con = bd.abrir(solo_lectura=True)
    for cliente_id in (1, 2, 3, 4):
        meses = {f[0] for f in con.execute(
            "SELECT strftime('%m', fecha) FROM movimientos WHERE cliente_id = ? AND fecha LIKE '2025-%' AND importe > 0",
            (cliente_id,))}
        assert len(meses) == 12, f"el cliente {cliente_id} no tiene ingresos todos los meses de 2025: {sorted(meses)}"
    con.close()


def test_una_base_de_una_version_anterior_se_regenera(bd):
    con = sqlite3.connect(bd.ruta)
    con.execute("PRAGMA user_version = 1")  # como la base de 12 meses de antes
    con.close()
    esquema.inicializar(bd, RelojFijo(), HASHEADOR)
    con = bd.abrir(solo_lectura=True)
    assert con.execute("PRAGMA user_version").fetchone()[0] == esquema.VERSION_ESQUEMA
    con.close()
