"""Adaptador HTTP de extremo a extremo: SQLite temporal + LLM falso, con login, sin red."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.adaptadores.entrada.http import rutas_ajustes, rutas_auth, rutas_banco, rutas_chat, rutas_operaciones
from backend.adaptadores.entrada.http.app import crear_app
from backend.adaptadores.entrada.http.seguridad import COOKIE_SESION, crear_dependencia
from backend.adaptadores.salida.persistencia.memoria_seguridad import IntentosEnMemoria, OperacionesEnMemoria
from backend.adaptadores.salida.persistencia.sesiones_memoria import SesionesEnMemoria
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.adaptadores.salida.seguridad.sesiones_auth import SesionesAutenticadasEnMemoria
from backend.adaptadores.salida.sqlite import esquema
from backend.adaptadores.salida.sqlite.auditoria import AuditoriaSqlite
from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.adaptadores.salida.sqlite.consultor import ConsultorMovimientosSqlite
from backend.adaptadores.salida.sqlite.repositorios import (
    RepositorioClientesSqlite,
    RepositorioContactosSqlite,
    RepositorioCuentaSqlite,
)
from backend.adaptadores.salida.persistencia.limitador import LimitadorEnMemoria
from backend.adaptadores.salida.sqlite.uso import UsoSqlite
from backend.aplicacion.casos_uso.uso import ConsultarUso
from backend.dominio.uso import PresupuestoUso
from backend.aplicacion.casos_uso.acceso import CerrarSesion, IdentificarCliente, IniciarSesion
from backend.aplicacion.casos_uso.ajustes import GestionAjustes
from backend.aplicacion.casos_uso.banco import ConsultarMovimientos, ConsultarSaldo, ListarContactos
from backend.aplicacion.casos_uso.bizum import CancelarOperacion, ConfirmarOperacion, SolicitarBizum
from backend.aplicacion.casos_uso.estado import ConsultarEstado
from backend.aplicacion.casos_uso.movil import LeerMensajesMovil
from backend.aplicacion.casos_uso.voz import SintetizarVoz, TranscribirAudio
from backend.aplicacion.chat import ServicioChat
from backend.aplicacion.herramientas import bizum, contactos, grafico, movimientos, saldo
from backend.aplicacion.herramientas.registro import RegistroHerramientas
from backend.dominio.ajustes import Ajustes, ConfigClave
from backend.adaptadores.entrada.http import rutas_uso
from tests.fakes import AjustesEnMemoria, CodigosFijos, LLMGuionizado, MovilFalso, RelojFijo, SondaFalsa, crear_agente, llamada, texto

HASHEADOR = HasheadorScrypt()


class TranscriptorFalso:
    def transcribir(self, audio, nombre):
        return "  ¿cuánto tengo?  "


class SintetizadorFalso:
    def __init__(self, ok=True):
        self.ok = ok

    def disponible(self):
        return self.ok

    def sintetizar(self, texto):
        return b"RIFF" + texto.encode()


@pytest.fixture(scope="module")
def bd_base(tmp_path_factory):
    bd = BaseDeDatos(tmp_path_factory.mktemp("bd") / "banco.db")
    esquema.inicializar(bd, RelojFijo(), HASHEADOR)
    return bd


class App:
    """Aplicación completa con adaptadores reales de SQLite y falsos para LLM, voz y móvil."""

    def __init__(self, tmp_path, bd_base, llm=None, ajustes=None, sintetizador=None, presupuesto=None):
        self.reloj = RelojFijo()
        self.bd = BaseDeDatos(tmp_path / "banco.db")
        self.bd.ruta.write_bytes(bd_base.ruta.read_bytes())
        self.movil = MovilFalso()
        self.auditoria = AuditoriaSqlite(self.bd, self.reloj)
        cuentas, agenda, clientes = RepositorioCuentaSqlite(self.bd), RepositorioContactosSqlite(self.bd), RepositorioClientesSqlite(self.bd)
        ajustes = ajustes or AjustesEnMemoria()
        self.sintetizador = sintetizador or SintetizadorFalso()
        operaciones = OperacionesEnMemoria()
        sesiones_auth = SesionesAutenticadasEnMemoria(self.reloj)
        c_saldo, c_contactos = ConsultarSaldo(cuentas), ListarContactos(agenda)
        c_movs = ConsultarMovimientos(ConsultorMovimientosSqlite(self.bd), self.auditoria)
        solicitar = SolicitarBizum(cuentas, agenda, operaciones, CodigosFijos(), self.movil, self.reloj, self.auditoria)
        registro = RegistroHerramientas([
            saldo.crear(c_saldo), contactos.crear(c_contactos), bizum.crear(solicitar),
            movimientos.crear(c_movs), grafico.crear(),
        ])
        self.presupuesto = presupuesto or PresupuestoUso()
        self.uso = UsoSqlite(self.bd)
        agente = crear_agente(llm or LLMGuionizado(), registro, ajustes, self.uso, self.presupuesto, self.reloj)
        chat = ServicioChat(
            agente, SesionesEnMemoria(), self.reloj, self.uso, LimitadorEnMemoria(self.presupuesto.peticiones_por_minuto),
            self.presupuesto, operaciones,
        )
        identificar = IdentificarCliente(sesiones_auth, clientes)
        actual = crear_dependencia(identificar)
        routers = [
            rutas_auth.crear_router(
                IniciarSesion(clientes, HASHEADOR, sesiones_auth, IntentosEnMemoria(), self.reloj, self.auditoria),
                CerrarSesion(sesiones_auth, self.auditoria), actual, False),
            rutas_banco.crear_router(c_saldo, c_contactos, solicitar, c_movs, actual),
            rutas_operaciones.crear_router(
                ConfirmarOperacion(cuentas, operaciones, self.reloj, self.auditoria),
                CancelarOperacion(operaciones, self.auditoria), LeerMensajesMovil(self.movil), actual),
            rutas_uso.crear_router(ConsultarUso(self.uso, self.presupuesto, self.reloj), actual),
            rutas_ajustes.crear_router(GestionAjustes(ajustes, SondaFalsa()), actual),
            rutas_chat.crear_router(chat, TranscribirAudio(TranscriptorFalso(), ajustes), SintetizarVoz(self.sintetizador),
                                    ConsultarEstado(ajustes, self.sintetizador), actual),
        ]
        (tmp_path / "index.html").write_text("<h1>hola</h1>")
        self.routers = routers
        self.app = crear_app(routers, tmp_path)

    def cliente(self, usuario=None):
        c = TestClient(self.app)
        if usuario:
            r = c.post("/auth/login", json={"usuario": usuario, "contrasena": f"{usuario}2026"})
            assert r.status_code == 200, r.text
        return c


@pytest.fixture
def app(tmp_path, bd_base):
    return App(tmp_path, bd_base)


def eventos(respuesta):
    return [json.loads(b[6:]) for b in respuesta.text.split("\n\n") if b.startswith("data: ")]


# ------------------------------------------------------------------ autenticación

RUTAS_PROTEGIDAS = [
    ("GET", "/api/banco/saldo"), ("GET", "/api/banco/contactos"), ("GET", "/api/banco/movimientos"),
    ("POST", "/api/banco/bizum"), ("POST", "/chat"), ("POST", "/stt"), ("POST", "/tts"), ("GET", "/estado"),
    ("GET", "/ajustes"), ("POST", "/ajustes/claves"), ("PUT", "/ajustes/ollama"), ("GET", "/ajustes/ollama/estado"),
    ("GET", "/auth/yo"), ("GET", "/movil/mensajes"), ("POST", "/operaciones/x/confirmar"), ("POST", "/operaciones/x/cancelar"),
]


@pytest.mark.parametrize("metodo,ruta", RUTAS_PROTEGIDAS)
def test_sin_sesion_todo_devuelve_401(app, metodo, ruta):
    r = app.cliente().request(metodo, ruta, json={})
    assert r.status_code == 401 and r.json()["detail"] == "Inicia sesión para continuar."


def test_con_cookie_inventada_tambien_401(app):
    c = app.cliente()
    c.cookies.set(COOKIE_SESION, "token-inventado")
    assert c.get("/api/banco/saldo").status_code == 401


def test_login_pone_cookie_httponly_samesite_strict(app):
    r = app.cliente().post("/auth/login", json={"usuario": "alex", "contrasena": "alex2026"})
    cabecera = r.headers["set-cookie"].lower()
    assert r.json() == {"usuario": "alex", "nombre": "Alex García"}
    assert "httponly" in cabecera and "samesite=strict" in cabecera and cabecera.startswith(f"{COOKIE_SESION}=")


def test_login_incorrecto_401_y_bloqueo_429_tras_5_fallos(app):
    c = app.cliente()
    for _ in range(4):
        assert c.post("/auth/login", json={"usuario": "alex", "contrasena": "mala"}).status_code == 401
    r = c.post("/auth/login", json={"usuario": "alex", "contrasena": "mala"})
    assert r.status_code == 429 and "bloqueada" in r.json()["detail"]
    assert c.post("/auth/login", json={"usuario": "alex", "contrasena": "alex2026"}).status_code == 429
    assert "set-cookie" not in c.post("/auth/login", json={"usuario": "alex", "contrasena": "alex2026"}).headers


def test_logout_cierra_la_sesion(app):
    c = app.cliente("alex")
    assert c.get("/auth/yo").json()["nombre"] == "Alex García"
    assert c.post("/auth/logout").status_code == 200
    assert c.get("/auth/yo").status_code == 401


def test_cabeceras_de_seguridad_y_sin_documentacion_de_la_api(app):
    c = app.cliente("alex")
    r = c.get("/api/banco/saldo")
    assert "default-src 'self'" in r.headers["content-security-policy"] and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


# ------------------------------------------------------------------ datos por cliente

def test_cada_cliente_ve_sus_datos(app):
    alex, ana = app.cliente("alex"), app.cliente("ana")
    assert alex.get("/api/banco/saldo").json()["titular"] == "Alex García"
    assert ana.get("/api/banco/saldo").json()["titular"] == "Ana Ruiz"
    assert alex.get("/api/banco/saldo").json()["saldo"] != ana.get("/api/banco/saldo").json()["saldo"]
    assert "María López" in str(alex.get("/api/banco/contactos").json())
    assert "María López" not in str(ana.get("/api/banco/contactos").json())
    movs = ana.get("/api/banco/movimientos", params={"limite": 5}).json()
    assert movs["ok"] and movs["num_filas"] == 5 and movs["columnas"][0] == "fecha"


def test_pagina_principal_y_estaticos_no_exigen_login(app):
    c = app.cliente()
    assert c.get("/").text == "<h1>hola</h1>" and c.get("/static/index.html").status_code == 200


# ------------------------------------------------------------------ Bizum + OTP por HTTP

def test_bizum_rest_no_ejecuta_hasta_confirmar_con_el_codigo_del_movil(app):
    c = app.cliente("alex")
    antes = c.get("/api/banco/saldo").json()["saldo"]
    r = c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 10}).json()
    assert r["ok"] and r["estado"] == "pendiente_de_confirmacion" and "codigo" not in json.dumps(r).lower().replace("código", "")
    assert c.get("/api/banco/saldo").json()["saldo"] == antes  # nada se ha movido
    op = r["operacion"]["id"]

    mala = c.post(f"/operaciones/{op}/confirmar", json={"codigo": "000000"})
    assert mala.status_code == 422 and "Te quedan 2" in mala.json()["detail"]
    sms = c.get("/movil/mensajes").json()[0]["texto"]
    assert "123456" in sms  # el código solo está en el móvil
    ok = c.post(f"/operaciones/{op}/confirmar", json={"codigo": "123456"}).json()
    assert ok["ok"] and ok["nuevo_saldo"] == round(antes - 10, 2)
    assert c.get("/api/banco/saldo").json()["saldo"] == round(antes - 10, 2)
    assert c.post(f"/operaciones/{op}/confirmar", json={"codigo": "123456"}).status_code == 409  # ya procesada


def test_otro_cliente_no_puede_confirmar_mi_operacion_ni_leer_mi_movil(app):
    alex, ana = app.cliente("alex"), app.cliente("ana")
    op = alex.post("/api/banco/bizum", json={"destinatario": "María", "importe": 10}).json()["operacion"]["id"]
    assert ana.post(f"/operaciones/{op}/confirmar", json={"codigo": "123456"}).status_code == 404
    assert ana.post(f"/operaciones/{op}/cancelar").status_code == 404
    assert ana.get("/movil/mensajes").json() == []
    assert len(alex.get("/movil/mensajes").json()) == 1


def test_rechazos_de_negocio_del_bizum_usan_su_codigo_http(app):
    c = app.cliente("alex")
    tope = c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 5000})
    assert tope.status_code == 422 and "1.000" in tope.json()["detail"]
    sin = c.post("/api/banco/bizum", json={"destinatario": "Zzz", "importe": 5})
    assert sin.status_code == 404 and len(sin.json()["contactos_disponibles"]) == 4
    assert c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 0}).status_code == 422
    assert c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 999999}).status_code == 422
    assert c.post("/api/banco/bizum", json={"destinatario": "María"}).status_code == 422  # falta el importe


def test_saldo_insuficiente_y_tope_diario_son_409(app):
    ana = app.cliente("ana")  # Ana tiene 480 €
    sin_saldo = ana.post("/api/banco/bizum", json={"destinatario": "Mamá", "importe": 900})
    assert sin_saldo.status_code == 409 and "Saldo insuficiente" in sin_saldo.json()["detail"]
    alex = app.cliente("alex")
    for _ in range(2):  # 2 × 700 = 1.400 € confirmados; el tercero supera los 1.500 € del día
        op = alex.post("/api/banco/bizum", json={"destinatario": "María", "importe": 700}).json()["operacion"]["id"]
        assert alex.post(f"/operaciones/{op}/confirmar", json={"codigo": "123456"}).status_code == 200
    tercero = alex.post("/api/banco/bizum", json={"destinatario": "María", "importe": 700})
    assert tercero.status_code == 409 and "límite diario" in tercero.json()["detail"]


def test_otp_caducado_410_agotado_423_y_ya_procesado_409(app):
    c = app.cliente("alex")
    op = c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 10}).json()["operacion"]["id"]
    for esperado in (422, 422, 423):
        assert c.post(f"/operaciones/{op}/confirmar", json={"codigo": "000000"}).status_code == esperado
    assert c.post(f"/operaciones/{op}/confirmar", json={"codigo": "123456"}).status_code == 409  # ya bloqueada
    otra = c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 10}).json()["operacion"]["id"]
    app.reloj.avanzar(6)
    caducado = c.post(f"/operaciones/{otra}/confirmar", json={"codigo": "123456"})
    assert caducado.status_code == 410 and "caducado" in caducado.json()["detail"]


def test_cancelar_desde_la_interfaz(app):
    c = app.cliente("alex")
    op = c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 10}).json()["operacion"]["id"]
    assert c.post(f"/operaciones/{op}/cancelar").json() == {"ok": True}
    assert c.post(f"/operaciones/{op}/confirmar", json={"codigo": "123456"}).status_code == 409


# ------------------------------------------------------------------ chat SSE

def test_chat_sse_con_herramienta_y_grafico(tmp_path, bd_base):
    config = {"type": "bar", "data": {"labels": ["a"], "datasets": []}}
    llm = LLMGuionizado(
        llamada("consultar_saldo", id="1"),
        llamada("generar_grafico", json.dumps({"titulo": "G", "config": config}), id="2"),
        texto("Listo"),
    )
    ev = eventos(App(tmp_path, bd_base, llm).cliente("alex").post("/chat", json={"session_id": "t", "mensaje": "hola"}))
    assert [e["tipo"] for e in ev] == ["herramienta", "herramienta", "grafico", "delta", "uso", "fin"]
    assert ev[0] == {"tipo": "herramienta", "dato": "consultar_saldo", "etiqueta": "Consultando saldo…"}
    assert ev[2]["dato"] == {"titulo": "G", "config": config} and ev[-1]["dato"] == "Listo"


def test_chat_el_bizum_del_llm_llega_como_tarjeta_sin_codigo_y_sin_mover_dinero(tmp_path, bd_base):
    llm = LLMGuionizado(
        llamada("transferencia_bizum", json.dumps({"destinatario": "María", "importe": 25})), texto("Confirma en la tarjeta"),
    )
    a = App(tmp_path, bd_base, llm)
    c = a.cliente("alex")
    antes = c.get("/api/banco/saldo").json()["saldo"]
    r = c.post("/chat", json={"session_id": "t", "mensaje": "envía 25 a María"})
    ev = eventos(r)
    tarjeta = next(e for e in ev if e["tipo"] == "operacion")["dato"]
    assert tarjeta["destinatario"] == "María López" and tarjeta["importe"] == 25
    assert "123456" not in r.text  # el código no viaja por el chat
    assert c.get("/api/banco/saldo").json()["saldo"] == antes
    # la tarjeta se confirma por el endpoint, con el código del móvil
    assert c.post(f"/operaciones/{tarjeta['id']}/confirmar", json={"codigo": "123456"}).json()["nuevo_saldo"] == round(antes - 25, 2)


def test_chat_sql_peligroso_del_llm_no_toca_la_base_de_datos(tmp_path, bd_base):
    llm = LLMGuionizado(llamada("consultar_movimientos", json.dumps({"sql": "DELETE FROM movimientos"})), texto("no"))
    a = App(tmp_path, bd_base, llm)
    c = a.cliente("alex")
    eventos(c.post("/chat", json={"session_id": "t", "mensaje": "borra todo"}))
    assert c.get("/api/banco/movimientos").json()["num_filas"] > 0
    assert [x["accion"] for x in a.auditoria.ultimos(1)][0] == "consulta_rechazada"


def test_chat_consulta_del_llm_solo_ve_datos_del_cliente(tmp_path, bd_base):
    llm = LLMGuionizado(
        llamada("consultar_movimientos", json.dumps({"sql": "SELECT COUNT(*) FROM main.movimientos"})), texto("ok"),
    )
    a = App(tmp_path, bd_base, llm)
    ana = a.cliente("ana")
    eventos(ana.post("/chat", json={"session_id": "t", "mensaje": "cuántos movimientos hay"}))
    propios = ana.get("/api/banco/movimientos", params={"limite": 60}).json()
    resultado = a.bd.abrir(solo_lectura=True).execute("SELECT COUNT(*) FROM movimientos WHERE cliente_id = 2").fetchone()[0]
    assert propios["num_filas"] == min(resultado, 60)


def test_chat_sin_motor_devuelve_evento_de_error(tmp_path, bd_base):
    a = App(tmp_path, bd_base, ajustes=AjustesEnMemoria(Ajustes(fallback_local=False)))
    ev = eventos(a.cliente("alex").post("/chat", json={"session_id": "t", "mensaje": "hola"}))
    assert ev[-1]["tipo"] == "error" and "Ajustes" in ev[-1]["dato"]


# ------------------------------------------------------------------ voz, estado y ajustes (con sesión)

def test_stt_ok_audio_corto_y_sin_clave(tmp_path, bd_base):
    a = App(tmp_path, bd_base, ajustes=AjustesEnMemoria(Ajustes(claves={"groq": ConfigClave("clave-falsa-groq")})))
    c = a.cliente("alex")
    assert c.post("/stt", files={"audio": ("a.webm", b"x" * 5000)}).json() == {"texto": "¿cuánto tengo?"}
    corto = c.post("/stt", files={"audio": ("a.webm", b"x" * 10)})
    assert corto.status_code == 422 and "No se ha detectado voz" in corto.json()["detail"]
    (tmp_path / "otra").mkdir()
    sin = App(tmp_path / "otra", bd_base, ajustes=AjustesEnMemoria(Ajustes(fallback_local=False)))
    assert sin.cliente("alex").post("/stt", files={"audio": ("a.webm", b"x" * 5000)}).status_code == 503


def test_tts_normaliza_numeros_y_responde_503_si_no_hay_voz(tmp_path, bd_base):
    c = App(tmp_path, bd_base).cliente("alex")
    r = c.post("/tts", json={"texto": "Tienes 5 €"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and b"cinco euros" in r.content
    assert c.post("/tts", json={"texto": "  "}).status_code == 422
    (tmp_path / "b").mkdir()
    sin_voz = App(tmp_path / "b", bd_base, sintetizador=SintetizadorFalso(False)).cliente("alex")
    assert sin_voz.post("/tts", json={"texto": "a"}).status_code == 503


def test_estado(app):
    e = app.cliente("alex").get("/estado").json()
    assert e["ok"] and e["modelo"] == "modelo-a" and e["cadena_fallback"] == ["modelo-a (groq)", "modelo-b (groq)"]
    assert e["configurado"] and e["voz_disponible"] and e["tts_servidor"]


def test_ajustes_nunca_exponen_la_clave(app):
    cuerpo = app.cliente("alex").get("/ajustes").text
    assert "clave-falsa-groq" not in cuerpo and "••••" in cuerpo


def test_ajustes_flujo_completo(app):
    c = app.cliente("alex")
    añadida = c.post("/ajustes/claves", json={"proveedor": "openai", "api_key": "clave-falsa-de-prueba"}).json()
    assert {x["proveedor"] for x in añadida["claves"]} == {"groq", "openai"} and "válida" in añadida["mensaje"]
    assert c.post("/ajustes/activar", json={"proveedor": "openai"}).json()["activo"] == "openai"
    patch = c.patch("/ajustes/claves/openai", json={"modelo": "otro"}).json()
    assert next(x for x in patch["claves"] if x["proveedor"] == "openai")["modelo"] == "otro"
    assert c.delete("/ajustes/claves/openai").json()["activo"] == "groq"
    assert c.put("/ajustes/ollama", json={"url": "http://x:1/v1/", "fallback_local": False}).json()["ollama"]["url"] == "http://x:1/v1"


def test_ajustes_errores_http(app):
    c = app.cliente("alex")
    assert c.post("/ajustes/probar", json={"proveedor": "nada", "api_key": "k"}).status_code == 404
    assert c.post("/ajustes/claves", json={"proveedor": "openai", "api_key": "  "}).status_code == 422
    assert c.post("/ajustes/activar", json={"proveedor": "gemini"}).status_code == 404
    assert c.patch("/ajustes/claves/gemini", json={"modelo": "x"}).status_code == 404


# ------------------------------------------------------------------ OpenAPI / Swagger

def app_con_docs(tmp_path, bd_base):
    a = App(tmp_path, bd_base)
    a.app = crear_app(a.routers, tmp_path, documentar=True)
    return a


def test_por_defecto_no_se_publica_el_mapa_de_la_api(app):
    c = app.cliente()
    assert all(c.get(ruta).status_code == 404 for ruta in ("/docs", "/redoc", "/openapi.json"))


def test_con_docs_activados_swagger_y_openapi_estan_disponibles_con_su_propia_csp(tmp_path, bd_base):
    c = app_con_docs(tmp_path, bd_base).cliente()
    docs = c.get("/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    assert "cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert c.get("/redoc").status_code == 200 and c.get("/openapi.json").status_code == 200
    # el resto de la app sigue con la CSP estricta, sin 'unsafe-inline'
    assert "unsafe-inline" not in c.get("/").headers["content-security-policy"]
    assert "unsafe-inline" not in c.post("/auth/login", json={"usuario": "x", "contrasena": "y"}).headers["content-security-policy"]


def test_la_especificacion_openapi_esta_completa_y_declara_la_cookie_de_sesion(tmp_path, bd_base):
    spec = app_con_docs(tmp_path, bd_base).cliente().get("/openapi.json").json()
    assert spec["info"]["title"] == "Habla con tu dinero" and spec["openapi"].startswith("3.")
    assert spec["components"]["securitySchemes"]["APIKeyCookie"] == {
        "type": "apiKey", "in": "cookie", "name": "sesion",
        "description": "Sesión iniciada con `POST /auth/login` (la pone el servidor).",
    }
    assert {t["name"] for t in spec["tags"]} == {"auth", "chat", "voz", "banco", "operaciones", "ajustes", "estado", "uso"}
    for ruta, operaciones in spec["paths"].items():
        for metodo, op in operaciones.items():
            assert op.get("summary") and op.get("tags"), f"{metodo.upper()} {ruta} sin summary o tags"
            if ruta not in ("/auth/login", "/auth/logout"):
                assert "401" in op["responses"], f"{metodo.upper()} {ruta} no documenta el 401"


def test_todas_las_rutas_protegidas_declaran_el_candado_en_openapi(tmp_path, bd_base):
    spec = app_con_docs(tmp_path, bd_base).cliente().get("/openapi.json").json()
    sin_candado = [
        f"{m.upper()} {r}" for r, ops in spec["paths"].items() for m, o in ops.items()
        if r not in ("/auth/login", "/auth/logout") and {"APIKeyCookie": []} not in o.get("security", [])
    ]
    assert sin_candado == []


def test_aprobar_con_huella_por_http_ejecuta_y_respeta_las_mismas_reglas(app):
    alex, ana = app.cliente("alex"), app.cliente("ana")
    antes = alex.get("/api/banco/saldo").json()["saldo"]
    op = alex.post("/api/banco/bizum", json={"destinatario": "María", "importe": 12}).json()["operacion"]["id"]
    assert ana.post(f"/operaciones/{op}/aprobar").status_code == 404  # una operación ajena no se aprueba
    assert app.cliente().post(f"/operaciones/{op}/aprobar").status_code == 401
    ok = alex.post(f"/operaciones/{op}/aprobar")
    assert ok.status_code == 200 and ok.json()["nuevo_saldo"] == round(antes - 12, 2)
    assert alex.post(f"/operaciones/{op}/aprobar").status_code == 409  # ya procesada
    otra = alex.post("/api/banco/bizum", json={"destinatario": "María", "importe": 12}).json()["operacion"]["id"]
    app.reloj.avanzar(6)
    assert alex.post(f"/operaciones/{otra}/aprobar").status_code == 410  # caducada
