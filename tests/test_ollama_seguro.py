"""Ollama: la URL se valida también al crear el cliente, sin redirecciones, sonda robusta y auditoría sin credenciales."""
import httpx
import pytest

from backend.adaptadores.salida.llm.clientes import FabricaClientes
from backend.adaptadores.salida.llm.sonda import SondaOpenAI
from backend.aplicacion.puertos.llm import ProveedorInaccesible
from backend.dominio.ajustes import Ajustes
from tests.fakes import AjustesEnMemoria


def test_la_fabrica_rechaza_una_url_de_ollama_ajena_aunque_este_en_los_ajustes():
    """Medio-9: la validación solo existía al guardar; un fichero de ajustes editado a mano la saltaba."""
    ajustes = AjustesEnMemoria(Ajustes(ollama_url="http://metadatos.interno/v1"))
    with pytest.raises(ProveedorInaccesible):
        FabricaClientes(ajustes).cliente("ollama")
    assert FabricaClientes(ajustes, frozenset({"metadatos.interno"})).cliente("ollama")
    assert FabricaClientes(AjustesEnMemoria(Ajustes())).cliente("ollama")  # localhost: bien


def test_el_cliente_de_ollama_no_sigue_redirecciones():
    cliente = FabricaClientes(AjustesEnMemoria(Ajustes())).cliente("ollama")
    assert cliente._client.follow_redirects is False


def test_la_sonda_tolera_una_respuesta_que_no_es_json(monkeypatch):
    respuesta = httpx.Response(200, content=b"<html>no soy ollama</html>", request=httpx.Request("GET", "http://x"))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: respuesta)
    estado = SondaOpenAI(FabricaClientes(AjustesEnMemoria())).estado_ollama("http://localhost:11434/v1")
    assert estado.ok is False

