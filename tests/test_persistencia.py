"""El estado que no debe perderse al reiniciar el servidor (sesiones, operaciones, SMS y conversaciones)."""
from datetime import datetime, timedelta

import pytest

from backend.adaptadores.salida.persistencia.sqlite_estado import (
    MovilSqlite,
    OperacionesSqlite,
    SesionesAutenticadasSqlite,
    SesionesChatSqlite,
)
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.adaptadores.salida.sqlite import esquema
from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.dominio.modelos import LlamadaHerramienta, Mensaje
from backend.dominio.operaciones import EstadoOperacion, OperacionPendiente
from tests.fakes import CONTRASENA_ALEX, RelojFijo


@pytest.fixture
def bd(tmp_path):
    bd = BaseDeDatos(tmp_path / "banco.db")
    esquema.inicializar(bd, RelojFijo(), HasheadorScrypt())
    return bd


def reiniciar(bd):
    """Un «reinicio del servidor»: la base de datos es la misma, pero los objetos se crean de nuevo."""
    return BaseDeDatos(bd.ruta)


def test_la_sesion_de_login_sobrevive_a_un_reinicio_y_no_guarda_el_token_en_claro(bd):
    reloj = RelojFijo()
    token = SesionesAutenticadasSqlite(bd, reloj).crear(3)
    nuevas = SesionesAutenticadasSqlite(reiniciar(bd), reloj)
    assert nuevas.cliente_de(token) == 3
    con = bd.abrir(solo_lectura=True)
    guardado = con.execute("SELECT huella FROM sesiones_auth").fetchone()[0]
    con.close()
    assert token not in guardado and len(guardado) == 64  # solo la huella sha256


def test_la_sesion_caduca_se_puede_cerrar_y_un_token_falso_no_vale(bd):
    reloj = RelojFijo()
    sesiones = SesionesAutenticadasSqlite(bd, reloj)
    token, otro = sesiones.crear(1), sesiones.crear(2)
    assert sesiones.cliente_de("token-inventado") is None
    sesiones.cerrar(token)
    assert sesiones.cliente_de(token) is None and sesiones.cliente_de(otro) == 2
    reloj.avanzar(8 * 60 + 1)
    assert sesiones.cliente_de(otro) is None  # caducada


def operacion(estado=EstadoOperacion.PENDIENTE):
    ahora = datetime(2026, 10, 3, 12, 0)
    return OperacionPendiente(
        "op-1", 1, "María López", "600111222", 25.5, "cena", "huella", ahora, ahora + timedelta(minutes=5),
        alertas=("Es la primera vez que envías un Bizum a este contacto.",), intentos_restantes=2, estado=estado,
    )


def test_una_operacion_pendiente_sobrevive_a_un_reinicio_con_su_estado(bd):
    original = operacion()
    OperacionesSqlite(bd).guardar(original)
    leida = OperacionesSqlite(reiniciar(bd)).obtener("op-1")
    assert leida == original  # los 12 campos, incluidos fechas, alertas y estado
    assert OperacionesSqlite(bd).obtener("no-existe") is None


def test_los_cambios_de_estado_de_una_operacion_se_guardan(bd):
    repo = OperacionesSqlite(bd)
    op = operacion()
    repo.guardar(op)
    op.intentos_restantes = 1
    op.estado = EstadoOperacion.BLOQUEADA
    repo.guardar(op)
    leida = repo.obtener("op-1")
    assert (leida.intentos_restantes, leida.estado) == (1, EstadoOperacion.BLOQUEADA)


def test_los_sms_del_movil_sobreviven_a_un_reinicio_y_son_del_cliente(bd):
    reloj = RelojFijo()
    MovilSqlite(bd, reloj).enviar(1, "Código de confirmación: 123456. Bizum de 10,00 € a María.")
    movil = MovilSqlite(reiniciar(bd), reloj)
    movil.enviar(1, "segundo")
    movil.enviar(2, "de otro cliente")
    sms = movil.mensajes(1)
    assert [m["texto"] for m in sms] == ["segundo", "Código de confirmación: 123456. Bizum de 10,00 € a María."]  # el más reciente primero
    assert sms[0] == {"remitente": "Unicaja", "texto": "segundo", "hora": "12:00"}
    assert [m["texto"] for m in movil.mensajes(2)] == ["de otro cliente"]
    for i in range(15):
        movil.enviar(3, f"sms {i}")
    assert len(movil.mensajes(3)) == 10  # solo los 10 últimos


def test_la_conversacion_sobrevive_a_un_reinicio_con_las_llamadas_a_herramientas(bd):
    llamada = LlamadaHerramienta("c1", "consultar_saldo", "{}")
    historial = [
        Mensaje.sistema("prompt"), Mensaje.usuario("¿cuánto tengo? ñ €"), Mensaje.asistente(None, (llamada,)),
        Mensaje.resultado_herramienta("c1", '{"saldo": 4200.0}'), Mensaje.asistente("Tienes 4.200,00 €"),
    ]
    SesionesChatSqlite(bd).guardar("1:abc", historial)
    assert SesionesChatSqlite(reiniciar(bd)).obtener("1:abc") == historial
    assert SesionesChatSqlite(bd).obtener("2:abc") is None  # otra clave (otro cliente): nada


def test_la_aplicacion_completa_conserva_la_sesion_tras_reiniciar(tmp_path, monkeypatch):
    """De extremo a extremo con la composición real: entrar, «reiniciar» el servidor y seguir dentro."""
    from fastapi.testclient import TestClient

    from backend import composicion
    from backend.adaptadores.salida.sqlite import conexion

    ruta = tmp_path / "banco.db"
    monkeypatch.setattr(conexion, "RUTA_DB", ruta)
    monkeypatch.setattr(composicion, "BaseDeDatos", lambda: BaseDeDatos(ruta))
    monkeypatch.setattr(composicion, "SintetizadorPiper", lambda: type("P", (), {"disponible": lambda s: False, "precargar": lambda s: None})())
    monkeypatch.setenv("COOKIE_SEGURA", "0")

    with TestClient(composicion.crear_aplicacion()) as primero:
        assert primero.post("/auth/login", json={"usuario": "alex", "contrasena": CONTRASENA_ALEX}).status_code == 200
        cookie = primero.cookies.get("sesion")
        op = primero.post("/api/banco/bizum", json={"destinatario": "María", "importe": 10}).json()["operacion"]["id"]
    with TestClient(composicion.crear_aplicacion()) as segundo:  # «reinicio»: aplicación nueva, misma base de datos
        segundo.cookies.set("sesion", cookie)
        assert segundo.get("/auth/yo").json()["usuario"] == "alex"  # sigue dentro
        assert len(segundo.get("/movil/mensajes").json()) == 1  # el SMS con el código no se perdió
        assert segundo.post(f"/operaciones/{op}/aprobar").status_code == 200  # ni la operación a medias


def test_las_conversaciones_viejas_y_las_sobrantes_se_purgan(bd):
    """M-3: `session_id` lo elige el cliente; sin purga la tabla crecía sin fin."""
    from backend.adaptadores.salida.persistencia.sqlite_estado import MAX_CONVERSACIONES_POR_CLIENTE
    sesiones = SesionesChatSqlite(bd)
    sesiones.guardar("1:vieja", [Mensaje.sistema("p")])
    con = bd.abrir()
    with con:
        con.execute("UPDATE sesiones_chat SET actualizada = datetime('now', '-30 days')")
    con.close()
    for i in range(MAX_CONVERSACIONES_POR_CLIENTE + 20):
        sesiones.guardar(f"1:s{i}", [Mensaje.sistema("p")])
    sesiones.guardar("2:otra", [Mensaje.sistema("p")])
    con = bd.abrir(solo_lectura=True)
    n1 = con.execute("SELECT COUNT(*) FROM sesiones_chat WHERE clave LIKE '1:%'").fetchone()[0]
    con.close()
    assert n1 == MAX_CONVERSACIONES_POR_CLIENTE
    assert sesiones.obtener("1:vieja") is None and sesiones.obtener("2:otra") is not None
    assert sesiones.obtener(f"1:s{MAX_CONVERSACIONES_POR_CLIENTE + 19}") is not None  # la más reciente se conserva
