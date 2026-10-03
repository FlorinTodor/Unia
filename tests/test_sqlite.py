"""Pruebas de integración del adaptador SQLite contra una base temporal."""
import sqlite3

import pytest

from backend.adaptadores.salida.sqlite import esquema
from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.adaptadores.salida.sqlite.repositorios import (
    ConsultorMovimientosSqlite,
    RepositorioContactosSqlite,
    RepositorioCuentaSqlite,
)
from backend.aplicacion.casos_uso.banco import ConsultarMovimientos, EnviarBizum
from backend.dominio.errores import ConsultaNoPermitida
from tests.fakes import RelojFijo


@pytest.fixture
def bd(tmp_path):
    bd = BaseDeDatos(tmp_path / "banco.db")
    esquema.inicializar(bd, RelojFijo())
    return bd


def test_inicializacion_es_idempotente_y_no_hay_fechas_futuras(bd):
    con = bd.abrir(solo_lectura=True)
    n, hasta = con.execute("SELECT COUNT(*), MAX(fecha) FROM movimientos").fetchone()
    con.close()
    assert n > 100 and hasta <= "2026-10-03"
    esquema.inicializar(bd, RelojFijo())  # no regenera
    assert RepositorioCuentaSqlite(bd).obtener().iban.startswith("ES21")


def test_bizum_de_extremo_a_extremo_es_atomico_y_persiste(bd):
    cuentas, agenda = RepositorioCuentaSqlite(bd), RepositorioContactosSqlite(bd)
    antes = cuentas.obtener().saldo
    EnviarBizum(cuentas, agenda, RelojFijo())("lucía", 20, "regalo")
    assert cuentas.obtener().saldo == round(antes - 20, 2)
    ultimo = ConsultarMovimientos(ConsultorMovimientosSqlite(bd)).ultimos(1)
    assert ultimo.filas[0][:3] == ["2026-10-03", "Bizum", "Bizum enviado a Lucía Fernández — regalo"]


def test_buscar_contacto_por_nombre_parcial_o_telefono(bd):
    agenda = RepositorioContactosSqlite(bd)
    assert agenda.buscar("pablo").telefono == "611333444"
    assert agenda.buscar("600111222").nombre == "María López"
    assert agenda.buscar("nadie") is None


def test_consulta_trunca_a_limite(bd):
    r = ConsultorMovimientosSqlite(bd).ejecutar_select("SELECT * FROM movimientos", 60)
    assert len(r.filas) == 60 and r.truncado


def test_la_conexion_de_consulta_es_de_solo_lectura_aunque_falle_la_validacion(bd):
    """Segunda barrera: aunque un DELETE llegase al adaptador, SQLite lo rechaza."""
    with pytest.raises(ConsultaNoPermitida):
        ConsultorMovimientosSqlite(bd).ejecutar_select("DELETE FROM movimientos", 60)
    con = bd.abrir(solo_lectura=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM movimientos")
    con.close()


def test_error_sql_se_traduce_a_error_de_dominio(bd):
    with pytest.raises(ConsultaNoPermitida, match="Error SQL"):
        ConsultorMovimientosSqlite(bd).ejecutar_select("SELECT * FROM no_existe", 60)
