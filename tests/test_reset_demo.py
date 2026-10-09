"""`pruebas/reset_demo.py`: deja la demo como nueva, siempre sobre una base temporal (nunca `data/banco.db`)."""
import importlib.util
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.adaptadores.salida.persistencia.sqlite_estado import MovilSqlite, OperacionesSqlite, SesionesAutenticadasSqlite
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.adaptadores.salida.sqlite import esquema
from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.dominio.operaciones import OperacionPendiente
from tests.fakes import CONTRASENA_ALEX, RelojFijo

_RUTA = Path(__file__).resolve().parent.parent / "pruebas" / "reset_demo.py"
_spec = importlib.util.spec_from_file_location("reset_demo", _RUTA)
reset_demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reset_demo)


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def contar(bd: BaseDeDatos, sql: str) -> int:
    con = bd.abrir(solo_lectura=True)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def sucia(tmp_path, monkeypatch):
    """Una base «usada»: sesión abierta, operación pendiente, SMS, conversación, tarjeta bloqueada y saldo tocado."""
    monkeypatch.setattr(reset_demo, "cargar_entorno", lambda: None)  # el .env real no entra en los tests
    monkeypatch.delenv("CONTRASENA_ADMIN", raising=False)
    bd = BaseDeDatos(tmp_path / "banco.db")
    reloj = RelojFijo()
    esquema.inicializar(bd, reloj, HasheadorScrypt())
    SesionesAutenticadasSqlite(bd, reloj).crear(1)
    ahora = datetime(2026, 10, 3, 12, 0)
    OperacionesSqlite(bd).guardar(OperacionPendiente(
        "op-1", 1, "María López", "600111222", 5.0, "cena", "huella", ahora, ahora + timedelta(minutes=5)))
    MovilSqlite(bd, reloj).enviar(1, "Código de confirmación: 123456.")
    con = bd.abrir()
    with con:
        con.execute("INSERT INTO sesiones_chat (clave, mensajes, actualizada) VALUES ('1:s', '[]', '2026-10-03')")
        con.execute("UPDATE tarjetas SET bloqueada = 1 WHERE cliente_id = 1")
        con.execute("UPDATE cuenta SET saldo = 1 WHERE cliente_id = 1")
    con.close()
    return bd


ESTADO = {
    "sesiones": "SELECT COUNT(*) FROM sesiones_auth",
    "operaciones": "SELECT COUNT(*) FROM operaciones_pendientes",
    "sms": "SELECT COUNT(*) FROM sms_movil",
    "conversaciones": "SELECT COUNT(*) FROM sesiones_chat",
    "bloqueadas": "SELECT COUNT(*) FROM tarjetas WHERE bloqueada = 1",
}


def test_sin_si_no_toca_nada(sucia, capsys):
    assert reset_demo.main(["--bd", str(sucia.ruta), "--puerto", str(puerto_libre())]) == 0
    assert all(contar(sucia, sql) > 0 for sql in ESTADO.values())
    assert list(sucia.ruta.parent.glob("*.copia-*")) == []
    assert "Simulacro" in capsys.readouterr().out


def test_con_si_copia_la_base_y_la_deja_como_nueva(sucia):
    assert reset_demo.main(["--si", "--bd", str(sucia.ruta), "--puerto", str(puerto_libre())]) == 0
    assert {n: contar(sucia, sql) for n, sql in ESTADO.items()} == dict.fromkeys(ESTADO, 0)
    assert contar(sucia, "SELECT saldo FROM cuenta WHERE cliente_id = 1") != 1
    assert contar(sucia, "SELECT COUNT(*) FROM clientes") == 4  # sin CONTRASENA_ADMIN no hay administrador
    assert contar(sucia, "SELECT COUNT(*) FROM movimientos") > 100
    con = sucia.abrir(solo_lectura=True)
    hash_alex = con.execute("SELECT hash_contrasena FROM clientes WHERE usuario = 'alex'").fetchone()[0]
    con.close()
    assert HasheadorScrypt().verificar(CONTRASENA_ALEX, hash_alex)
    # la copia guarda el estado anterior, intacto
    (copia,) = sucia.ruta.parent.glob("banco.db.copia-*")
    assert contar(BaseDeDatos(copia), ESTADO["operaciones"]) == 1


def test_aborta_si_el_servidor_esta_en_marcha(sucia, capsys):
    with socket.socket() as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen()
        puerto = servidor.getsockname()[1]
        assert reset_demo.main(["--si", "--bd", str(sucia.ruta), "--puerto", str(puerto)]) == 2
    assert contar(sucia, ESTADO["operaciones"]) == 1
    assert list(sucia.ruta.parent.glob("*.copia-*")) == []
    assert "ABORTADO" in capsys.readouterr().err


def test_ajustes_solo_se_apartan_con_la_opcion(sucia, tmp_path):
    ajustes = tmp_path / "ajustes.json"
    ajustes.write_text('{"activo": "ollama"}', encoding="utf-8")
    base = ["--si", "--bd", str(sucia.ruta), "--ruta-ajustes", str(ajustes), "--puerto", str(puerto_libre())]
    reset_demo.main(base)
    assert ajustes.exists()
    reset_demo.main([*base, "--ajustes"])
    assert not ajustes.exists()
    (copia,) = tmp_path.glob("ajustes.json.copia-*")
    assert "ollama" in copia.read_text(encoding="utf-8")


def test_dos_ejecuciones_en_el_mismo_segundo_no_pisan_la_copia(sucia, monkeypatch):
    class Congelado(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 9, 12, 0, 0)
    monkeypatch.setattr(reset_demo, "datetime", Congelado)
    argv = ["--si", "--bd", str(sucia.ruta), "--puerto", str(puerto_libre())]
    reset_demo.main(argv)
    reset_demo.main(argv)
    copias = sorted(p.name for p in sucia.ruta.parent.glob("banco.db.copia-*"))
    assert copias == ["banco.db.copia-20261009-120000", "banco.db.copia-20261009-120000-2"]
    # la primera conserva el estado sucio: la segunda ejecución no la ha sobrescrito
    assert contar(BaseDeDatos(sucia.ruta.parent / copias[0]), ESTADO["operaciones"]) == 1


def test_por_defecto_vigila_todo_el_rango_de_puertos(sucia, monkeypatch):
    with socket.socket() as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen()
        monkeypatch.setattr(reset_demo, "PUERTOS_SERVIDOR", (puerto_libre(), servidor.getsockname()[1]))
        assert reset_demo.main(["--si", "--bd", str(sucia.ruta)]) == 2
    assert contar(sucia, ESTADO["operaciones"]) == 1


def test_aborta_si_un_proceso_tiene_abierta_la_bd(sucia, monkeypatch, capsys):
    monkeypatch.setattr(reset_demo, "procesos_con_la_bd", lambda ruta: "4242")
    assert reset_demo.main(["--si", "--bd", str(sucia.ruta), "--puerto", str(puerto_libre())]) == 2
    assert contar(sucia, ESTADO["operaciones"]) == 1
    assert "4242" in capsys.readouterr().err


def test_sin_fuser_la_comprobacion_se_salta(sucia, monkeypatch):
    monkeypatch.setattr(reset_demo.shutil, "which", lambda _: None)
    assert reset_demo.procesos_con_la_bd(sucia.ruta) == ""
