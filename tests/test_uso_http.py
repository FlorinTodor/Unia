"""Control de tokens visto desde HTTP: códigos de error, endpoint de uso y evento SSE."""
import json

from backend.dominio.uso import PresupuestoUso, Uso
from tests.fakes import LLMGuionizado, texto
from tests.test_http import App, bd_base, eventos  # noqa: F401  (bd_base es un fixture)


def chat(c, mensaje="hola", sesion="s"):
    return c.post("/chat", json={"session_id": sesion, "mensaje": mensaje})


def test_un_mensaje_demasiado_largo_es_413_y_uno_vacio_422_sin_llamar_al_modelo(tmp_path, bd_base):
    llm = LLMGuionizado()
    c = App(tmp_path, bd_base, llm, presupuesto=PresupuestoUso(max_caracteres_mensaje=50)).cliente("alex")
    largo = chat(c, "x" * 51)
    assert largo.status_code == 413 and "demasiado largo" in largo.json()["detail"]
    vacio = chat(c, "   ")
    assert vacio.status_code == 422 and vacio.json()["detail"] == "Escribe un mensaje."
    assert llm.llamadas == []


def test_demasiadas_peticiones_es_429_con_retry_after(tmp_path, bd_base):
    c = App(tmp_path, bd_base, LLMGuionizado(*[texto("x")] * 3), presupuesto=PresupuestoUso(peticiones_por_minuto=2)).cliente("alex")
    assert chat(c).status_code == 200 and chat(c).status_code == 200
    r = chat(c)
    assert r.status_code == 429 and "demasiado rápido" in r.json()["detail"]
    assert 1 <= int(r.headers["retry-after"]) <= 61


def test_cuota_diaria_de_tokens_agotada_es_429_con_retry_after_hasta_medianoche(tmp_path, bd_base):
    a = App(tmp_path, bd_base, LLMGuionizado(texto("a")), presupuesto=PresupuestoUso(tokens_por_dia=100))
    c = a.cliente("alex")
    assert chat(c).status_code == 200  # gasta 150 tokens (100 + 50) > 100
    r = chat(c)
    assert r.status_code == 429 and "uso diario" in r.json()["detail"]
    assert int(r.headers["retry-after"]) == 12 * 3600  # el reloj de las pruebas marca las 12:00
    assert a.cliente("ana").get("/api/uso").json()["tokens_hoy"] == 0  # el gasto es de cada cliente


def test_el_chat_emite_el_evento_uso_y_el_gasto_queda_registrado(tmp_path, bd_base):
    a = App(tmp_path, bd_base, LLMGuionizado(texto("Hola")))
    c = a.cliente("alex")
    ev = eventos(chat(c))
    assert [e["tipo"] for e in ev] == ["delta", "uso", "fin"]
    assert ev[1]["dato"] == {"tokens_turno": 150, "tokens_hoy": 150, "limite_dia": 80_000}
    uso = c.get("/api/uso").json()
    assert uso["tokens_hoy"] == 150 and uso["restante"] == 79_850 and uso["porcentaje"] == 0.2
    assert uso["ultimos"][0]["entrada"] == 100 and uso["ultimos"][0]["salida"] == 50 and uso["ultimos"][0]["estimado"] is False
    assert (uso["por_turno"], uso["peticiones_por_minuto"], uso["max_caracteres_mensaje"]) == (30_000, 20, 1_500)


def test_el_endpoint_de_uso_exige_sesion_y_esta_documentado(tmp_path, bd_base):
    a = App(tmp_path, bd_base)
    assert a.cliente().get("/api/uso").status_code == 401
    assert a.cliente("alex").get("/api/uso").json()["tokens_hoy"] == 0


def test_un_turno_que_se_pasa_del_tope_termina_con_un_mensaje_claro_por_sse(tmp_path, bd_base):
    from tests.fakes import llamada

    llm = LLMGuionizado(llamada("consultar_saldo"), llamada("consultar_saldo"), texto("no llega"), uso=Uso(20_000, 5_000))
    c = App(tmp_path, bd_base, llm).cliente("alex")
    ev = eventos(chat(c))
    assert ev[-1]["tipo"] == "fin" and "límite de uso permitido para una sola pregunta" in ev[-1]["dato"]
    assert ev[-2]["tipo"] == "uso" and ev[-2]["dato"]["tokens_turno"] == 50_000
