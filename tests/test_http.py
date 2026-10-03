"""Adaptador HTTP de extremo a extremo: SQLite temporal + LLM falso, sin red."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.adaptadores.entrada.http import rutas_ajustes, rutas_banco, rutas_chat
from backend.adaptadores.entrada.http.app import crear_app
from backend.adaptadores.salida.persistencia.sesiones_memoria import SesionesEnMemoria
from backend.adaptadores.salida.sqlite import esquema
from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.adaptadores.salida.sqlite.repositorios import (
    ConsultorMovimientosSqlite,
    RepositorioContactosSqlite,
    RepositorioCuentaSqlite,
)
from backend.aplicacion.agente import Agente
from backend.aplicacion.casos_uso.ajustes import GestionAjustes
from backend.aplicacion.casos_uso.banco import ConsultarMovimientos, ConsultarSaldo, EnviarBizum, ListarContactos
from backend.aplicacion.casos_uso.estado import ConsultarEstado
from backend.aplicacion.casos_uso.voz import SintetizarVoz, TranscribirAudio
from backend.aplicacion.chat import ServicioChat
from backend.aplicacion.herramientas import bizum, contactos, grafico, movimientos, saldo
from backend.aplicacion.herramientas.registro import RegistroHerramientas
from backend.dominio.ajustes import Ajustes, ConfigClave
from tests.fakes import AjustesEnMemoria, LLMGuionizado, RelojFijo, SondaFalsa, llamada, texto


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


def montar(tmp_path, llm, ajustes=None, sintetizador=None):
    reloj = RelojFijo()
    bd = BaseDeDatos(tmp_path / "banco.db")
    esquema.inicializar(bd, reloj)
    cuentas, agenda = RepositorioCuentaSqlite(bd), RepositorioContactosSqlite(bd)
    ajustes = ajustes or AjustesEnMemoria()
    sintetizador = sintetizador or SintetizadorFalso()
    c_saldo, c_contactos = ConsultarSaldo(cuentas), ListarContactos(agenda)
    c_bizum, c_movs = EnviarBizum(cuentas, agenda, reloj), ConsultarMovimientos(ConsultorMovimientosSqlite(bd))
    registro = RegistroHerramientas([
        saldo.crear(c_saldo), contactos.crear(c_contactos), bizum.crear(c_bizum),
        movimientos.crear(c_movs), grafico.crear(),
    ])
    chat = ServicioChat(Agente(llm, registro, ajustes), SesionesEnMemoria(), c_saldo, reloj)
    routers = [
        rutas_banco.crear_router(c_saldo, c_contactos, c_bizum, c_movs),
        rutas_ajustes.crear_router(GestionAjustes(ajustes, SondaFalsa())),
        rutas_chat.crear_router(chat, TranscribirAudio(TranscriptorFalso(), ajustes), SintetizarVoz(sintetizador),
                                ConsultarEstado(ajustes, sintetizador)),
    ]
    return TestClient(crear_app(routers, tmp_path))


def eventos(respuesta):
    return [json.loads(b[6:]) for b in respuesta.text.split("\n\n") if b.startswith("data: ")]


@pytest.fixture
def cliente(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hola</h1>")
    return montar(tmp_path, LLMGuionizado())


# ------------------------------------------------------------------ banco

def test_banco_saldo_contactos_y_movimientos(cliente):
    assert cliente.get("/api/banco/saldo").json()["titular"] == "Alex García"
    assert len(cliente.get("/api/banco/contactos").json()) == 4
    movs = cliente.get("/api/banco/movimientos", params={"limite": 5}).json()
    assert movs["ok"] and movs["num_filas"] == 5 and movs["columnas"][0] == "fecha"


def test_bizum_rest_ok_y_rechazo_de_negocio_es_200_con_ok_false(cliente):
    ok = cliente.post("/api/banco/bizum", json={"destinatario": "María", "importe": 10}).json()
    assert ok["ok"] and ok["destinatario"] == "María López"
    no = cliente.post("/api/banco/bizum", json={"destinatario": "María", "importe": 5000}).json()
    assert not no["ok"] and "1.000" in no["error"]
    sin = cliente.post("/api/banco/bizum", json={"destinatario": "Zzz", "importe": 5}).json()
    assert not sin["ok"] and len(sin["contactos_disponibles"]) == 4


def test_pagina_principal_y_estaticos(cliente):
    assert cliente.get("/").text == "<h1>hola</h1>"
    assert cliente.get("/static/index.html").status_code == 200


# ------------------------------------------------------------------ chat SSE

def test_chat_sse_con_herramienta_y_grafico(tmp_path):
    config = {"type": "bar", "data": {"labels": ["a"], "datasets": []}}
    llm = LLMGuionizado(
        llamada("consultar_saldo", id="1"),
        llamada("generar_grafico", json.dumps({"titulo": "G", "config": config}), id="2"),
        texto("Listo"),
    )
    c = montar(tmp_path, llm)
    ev = eventos(c.post("/chat", json={"session_id": "t", "mensaje": "hola"}))
    assert [e["tipo"] for e in ev] == ["herramienta", "herramienta", "grafico", "delta", "fin"]
    assert ev[0] == {"tipo": "herramienta", "dato": "consultar_saldo", "etiqueta": "Consultando saldo…"}
    assert ev[2]["dato"] == {"titulo": "G", "config": config}
    assert ev[-1]["dato"] == "Listo"


def test_chat_sql_peligroso_del_llm_no_toca_la_base_de_datos(tmp_path):
    llm = LLMGuionizado(llamada("consultar_movimientos", json.dumps({"sql": "DELETE FROM movimientos"})), texto("no"))
    c = montar(tmp_path, llm)
    eventos(c.post("/chat", json={"session_id": "t", "mensaje": "borra todo"}))
    assert c.get("/api/banco/movimientos").json()["num_filas"] > 0


def test_chat_sin_motor_devuelve_evento_de_error(tmp_path):
    c = montar(tmp_path, LLMGuionizado(), AjustesEnMemoria(Ajustes(fallback_local=False)))
    ev = eventos(c.post("/chat", json={"session_id": "t", "mensaje": "hola"}))
    assert ev[-1]["tipo"] == "error" and "Ajustes" in ev[-1]["dato"]


# ------------------------------------------------------------------ voz y estado

def test_stt_ok_audio_corto_y_sin_clave(tmp_path):
    c = montar(tmp_path, LLMGuionizado(), AjustesEnMemoria(Ajustes(claves={"groq": ConfigClave("k")})))
    assert c.post("/stt", files={"audio": ("a.webm", b"x" * 5000)}).json() == {"texto": "¿cuánto tengo?"}
    corto = c.post("/stt", files={"audio": ("a.webm", b"x" * 10)})
    assert corto.status_code == 422 and "No se ha detectado voz" in corto.json()["detail"]
    sin = montar(tmp_path, LLMGuionizado(), AjustesEnMemoria(Ajustes(fallback_local=False)))
    assert sin.post("/stt", files={"audio": ("a.webm", b"x" * 5000)}).status_code == 503


def test_tts_normaliza_numeros_y_responde_503_si_no_hay_voz(tmp_path):
    c = montar(tmp_path, LLMGuionizado())
    r = c.post("/tts", json={"texto": "Tienes 5 €"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and b"cinco euros" in r.content
    assert c.post("/tts", json={"texto": "  "}).status_code == 422
    assert montar(tmp_path, LLMGuionizado(), sintetizador=SintetizadorFalso(False)).post("/tts", json={"texto": "a"}).status_code == 503


def test_estado(cliente):
    e = cliente.get("/estado").json()
    assert e["ok"] and e["modelo"] == "modelo-a" and e["cadena_fallback"] == ["modelo-a (groq)", "modelo-b (groq)"]
    assert e["configurado"] and e["voz_disponible"] and e["tts_servidor"]


# ------------------------------------------------------------------ ajustes

def test_ajustes_nunca_exponen_la_clave(cliente):
    cuerpo = cliente.get("/ajustes").text
    assert "gsk_x" not in cuerpo and "••••" in cuerpo


def test_ajustes_flujo_completo(cliente):
    añadida = cliente.post("/ajustes/claves", json={"proveedor": "openai", "api_key": "sk-clave-larga-123"}).json()
    assert {c["proveedor"] for c in añadida["claves"]} == {"groq", "openai"} and "válida" in añadida["mensaje"]
    assert cliente.post("/ajustes/activar", json={"proveedor": "openai"}).json()["activo"] == "openai"
    patch = cliente.patch("/ajustes/claves/openai", json={"modelo": "otro"}).json()
    assert next(c for c in patch["claves"] if c["proveedor"] == "openai")["modelo"] == "otro"
    assert cliente.delete("/ajustes/claves/openai").json()["activo"] == "groq"
    assert cliente.put("/ajustes/ollama", json={"url": "http://x:1/v1/", "fallback_local": False}).json()["ollama"]["url"] == "http://x:1/v1"


def test_ajustes_errores_http(cliente):
    assert cliente.post("/ajustes/probar", json={"proveedor": "nada", "api_key": "k"}).status_code == 404
    assert cliente.post("/ajustes/claves", json={"proveedor": "openai", "api_key": "  "}).status_code == 422
    assert cliente.post("/ajustes/activar", json={"proveedor": "gemini"}).status_code == 404
    assert cliente.patch("/ajustes/claves/gemini", json={"modelo": "x"}).status_code == 404
