import json

import pytest

from backend.aplicacion.agente import MAX_RONDAS, Agente
from backend.aplicacion.casos_uso.banco import ConsultarSaldo
from backend.aplicacion.eventos import Aviso, Delta, Fin, HerramientaEnUso
from backend.aplicacion.herramientas import saldo
from backend.aplicacion.herramientas.registro import Herramienta, RegistroHerramientas, ResultadoHerramienta, Riesgo
from backend.aplicacion.puertos.llm import (
    CuotaAgotada,
    EsquemaHerramienta,
    GeneracionFallida,
    ProveedorInaccesible,
)
from backend.dominio.ajustes import Ajustes, ConfigClave
from backend.dominio.errores import ErrorNoDisponible, ImporteInvalido
from backend.dominio.modelos import Mensaje
from tests.fakes import AjustesEnMemoria, CuentaEnMemoria, LLMGuionizado, llamada, texto


def crear(llm, ajustes=None, extra=()):
    registro = RegistroHerramientas([saldo.crear(ConsultarSaldo(CuentaEnMemoria(123.45))), *extra])
    return Agente(llm, registro, ajustes or AjustesEnMemoria())


def correr(agente, pregunta="hola"):
    mensajes = [Mensaje.sistema("s"), Mensaje.usuario(pregunta)]
    return list(agente.responder(mensajes)), mensajes


def test_respuesta_directa_en_streaming():
    eventos, mensajes = correr(crear(LLMGuionizado(texto("Ho", "la"))))
    assert eventos == [Delta("Ho"), Delta("la"), Fin("Hola")]
    assert mensajes[-1] == Mensaje.asistente("Hola")


def test_ejecuta_herramienta_y_vuelve_a_preguntar_al_modelo():
    llm = LLMGuionizado(llamada("consultar_saldo"), texto("Tienes 123,45 €"))
    eventos, mensajes = correr(crear(llm))
    assert eventos == [HerramientaEnUso("consultar_saldo", "Consultando saldo…"), Delta("Tienes 123,45 €"), Fin("Tienes 123,45 €")]
    resultado = next(m for m in mensajes if m.rol == "tool")
    assert json.loads(resultado.contenido)["saldo"] == 123.45
    assert resultado.id_llamada == "c1"
    # el segundo turno del LLM ya incluye el resultado de la herramienta
    assert any(m.rol == "tool" for m in llm.llamadas[1][1])


def test_error_de_negocio_en_herramienta_se_devuelve_al_modelo_no_rompe():
    def falla(_args):
        raise ImporteInvalido("El importe debe ser mayor que 0.")

    herramienta = Herramienta(EsquemaHerramienta("falla", "x", {}), falla, "…", Riesgo.ESCRITURA)
    llm = LLMGuionizado(llamada("falla"), texto("No se pudo"))
    _, mensajes = correr(crear(llm, extra=[herramienta]))
    assert json.loads(next(m for m in mensajes if m.rol == "tool").contenido) == {
        "ok": False, "error": "El importe debe ser mayor que 0."}


def test_herramienta_desconocida_e_json_invalido_no_rompen():
    llm = LLMGuionizado(llamada("no_existe"), llamada("consultar_saldo", "{roto"), texto("ok"))
    eventos, _ = correr(crear(llm))
    assert isinstance(eventos[-1], Fin)


def test_fallback_a_siguiente_eslabon_con_aviso():
    ajustes = AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "grande", "pequeño")}, fallback_local=False))
    llm = LLMGuionizado(CuotaAgotada("429"), texto("desde el respaldo"))
    eventos, _ = correr(crear(llm, ajustes))
    assert eventos[0] == Aviso("grande ha agotado su cuota gratuita por ahora. Cambiando a pequeño (Groq).")
    assert eventos[-1] == Fin("desde el respaldo")
    assert [ll[0].modelo for ll in llm.llamadas] == ["grande", "pequeño"]


def test_cadena_agotada_lanza_error_con_mensaje_legible():
    ajustes = AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "a", None)}, fallback_local=False))
    llm = LLMGuionizado(ProveedorInaccesible("sin red"))
    with pytest.raises(ErrorNoDisponible, match="no está disponible"):
        correr(crear(llm, ajustes))


def test_sin_motor_configurado():
    with pytest.raises(ErrorNoDisponible, match="Ajustes"):
        correr(crear(LLMGuionizado(), AjustesEnMemoria(Ajustes(fallback_local=False))))


def test_fallos_de_generacion_se_reintentan_en_silencio_y_luego_se_propagan():
    eventos, _ = correr(crear(LLMGuionizado(GeneracionFallida("json"), texto("bien"))))
    assert eventos[-1] == Fin("bien")
    with pytest.raises(GeneracionFallida):
        correr(crear(LLMGuionizado(*[GeneracionFallida("json")] * 3)))


def test_rondas_agotadas_fuerzan_respuesta_sin_herramientas():
    llm = LLMGuionizado(*[llamada("consultar_saldo")] * MAX_RONDAS, texto("Resumen"))
    eventos, _ = correr(crear(llm))
    assert eventos[-1] == Fin("Resumen")
    assert llm.llamadas[-1][2] is None  # la última llamada no ofrece herramientas
