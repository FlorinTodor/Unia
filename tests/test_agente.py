import json

import pytest

from backend.aplicacion.agente import MAX_RONDAS, Agente
from backend.aplicacion.casos_uso.banco import ConsultarSaldo
from backend.aplicacion.eventos import Aviso, Delta, Fin, Grafico, HerramientaEnUso, UsoConsumido
from backend.aplicacion.herramientas import grafico, saldo
from backend.aplicacion.herramientas.registro import Herramienta, RegistroHerramientas, ResultadoHerramienta, Riesgo
from backend.aplicacion.puertos.llm import (
    CuotaAgotada,
    EsquemaHerramienta,
    GeneracionFallida,
    LimitePorMinuto,
    ProveedorInaccesible,
)
from backend.dominio.ajustes import Ajustes, ConfigClave
from backend.dominio.errores import ErrorNoDisponible, ImporteInvalido
from backend.dominio.modelos import Mensaje
from tests.fakes import ALEX, AjustesEnMemoria, CuentaEnMemoria, LLMGuionizado, crear_agente, llamada, texto


def crear(llm, ajustes=None, extra=()):
    registro = RegistroHerramientas([saldo.crear(ConsultarSaldo(CuentaEnMemoria(123.45))), *extra])
    return crear_agente(llm, registro, ajustes)


def correr(agente, pregunta="hola"):
    mensajes = [Mensaje.sistema("s"), Mensaje.usuario(pregunta)]
    return list(agente.responder(mensajes, ALEX)), mensajes


def test_respuesta_directa_en_streaming():
    eventos, mensajes = correr(crear(LLMGuionizado(texto("Ho", "la"))))
    assert eventos == [Delta("Ho"), Delta("la"), UsoConsumido(150, 150, 80_000), Fin("Hola")]
    assert mensajes[-1] == Mensaje.asistente("Hola")


def test_ejecuta_herramienta_y_vuelve_a_preguntar_al_modelo():
    llm = LLMGuionizado(llamada("consultar_saldo"), texto("Tienes 123,45 €"))
    eventos, mensajes = correr(crear(llm))
    assert eventos == [
        HerramientaEnUso("consultar_saldo", "Consultando saldo…"), Delta("Tienes 123,45 €"),
        UsoConsumido(300, 300, 80_000), Fin("Tienes 123,45 €"),  # dos llamadas al modelo: 2 × 150 tokens
    ]
    resultado = next(m for m in mensajes if m.rol == "tool")
    assert json.loads(resultado.contenido)["saldo"] == 123.45
    assert resultado.id_llamada == "c1"
    # el segundo turno del LLM ya incluye el resultado de la herramienta
    assert any(m.rol == "tool" for m in llm.llamadas[1][1])


def test_error_de_negocio_en_herramienta_se_devuelve_al_modelo_no_rompe():
    def falla(_args, _cliente):
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
    assert eventos[0] == Aviso(
        "grande ha agotado su cuota gratuita por ahora. No lo intentaré de nuevo hasta las 12:15. Cambiando a pequeño (Groq)."
    )
    assert eventos[-1] == Fin("desde el respaldo")
    assert [ll[0].modelo for ll in llm.llamadas] == ["grande", "pequeño"]


def test_cadena_agotada_lanza_error_con_mensaje_legible():
    ajustes = AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "a", None)}, fallback_local=False))
    llm = LLMGuionizado(ProveedorInaccesible("sin red"))
    with pytest.raises(ErrorNoDisponible, match="todos los modelos de IA"):
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


def test_limite_por_minuto_se_explica_distinto_de_cuota_diaria():
    ajustes = AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "grande", "pequeño")}, fallback_local=False))
    eventos, _ = correr(crear(LLMGuionizado(LimitePorMinuto("TPM"), texto("ok")), ajustes))
    assert "límite por minuto" in eventos[0].texto and "cuota" not in eventos[0].texto


def test_grafico_escrito_como_json_en_el_texto_se_convierte_en_evento():
    config = '{"type": "bar", "data": {"labels": ["a"], "datasets": []}}'
    eventos, mensajes = correr(crear(LLMGuionizado(texto("Aquí va:\n```json\n" + config + "\n```\nListo"))))
    graficos = [e for e in eventos if isinstance(e, Grafico)]
    assert len(graficos) == 1 and graficos[0].config["type"] == "bar"
    assert "```" not in eventos[-1].texto and "Listo" in eventos[-1].texto
    assert "```" not in mensajes[-1].contenido


def test_bloque_json_que_no_es_un_grafico_se_deja_intacto():
    eventos, _ = correr(crear(LLMGuionizado(texto('Mira ```json\n{"a": 1}\n``` esto'))))
    assert not any(isinstance(e, Grafico) for e in eventos) and "```" in eventos[-1].texto


# ------------------------------------------------------------------ promesas sin acción y esperas

def test_si_el_modelo_promete_algo_y_no_lo_hace_se_le_obliga_a_cumplirlo_una_vez():
    from backend.aplicacion.agente import AVISO_CONTINUAR

    llm = LLMGuionizado(
        texto("Voy a consultar tu saldo. Un momento…"),   # promete y cierra el turno
        llamada("consultar_saldo"),
        texto("Tienes 123,45 €"),
    )
    eventos, mensajes = correr(crear(llm))
    assert eventos[-1] == Fin("Tienes 123,45 €")  # el usuario recibe el resultado, no la promesa
    assert any(m.rol == "user" and m.contenido == AVISO_CONTINUAR for m in llm.llamadas[1][1])
    assert any(e == HerramientaEnUso("consultar_saldo", "Consultando saldo…") for e in eventos)


def test_el_empujon_es_solo_uno_por_turno():
    llm = LLMGuionizado(texto("Voy a ver. Un momento…"), texto("Voy a verlo otra vez. Un momento…"))
    eventos, _ = correr(crear(llm))
    assert len(llm.llamadas) == 2 and isinstance(eventos[-1], Fin)  # la segunda promesa ya no se persigue


def test_un_limite_por_minuto_corto_se_espera_y_se_reintenta_con_el_mismo_modelo():
    ajustes = AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "grande", "pequeño")}, fallback_local=False))
    esperas = []
    llm = LLMGuionizado(LimitePorMinuto("TPM", espera=3.2), texto("ok"))
    agente = crear_agente(llm, RegistroHerramientas([]), ajustes, esperar=esperas.append)
    mensajes = [Mensaje.sistema("s"), Mensaje.usuario("hola")]
    eventos = list(agente.responder(mensajes, ALEX))
    assert esperas == [3.7] and [ll[0].modelo for ll in llm.llamadas] == ["grande", "grande"]
    assert eventos[0] == Aviso("grande ha alcanzado su límite por minuto. Espero 4 s y lo reintento.")
    assert eventos[-1] == Fin("ok")


def test_un_limite_por_minuto_largo_o_repetido_baja_al_siguiente_modelo_sin_esperar_de_mas():
    ajustes = AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "grande", "pequeño")}, fallback_local=False))
    esperas = []
    llm = LLMGuionizado(LimitePorMinuto("TPM", espera=45), texto("ok"))  # 45 s: demasiado para esperar
    agente = crear_agente(llm, RegistroHerramientas([]), ajustes, esperar=esperas.append)
    list(agente.responder([Mensaje.sistema("s"), Mensaje.usuario("hola")], ALEX))
    assert esperas == [] and [ll[0].modelo for ll in llm.llamadas] == ["grande", "pequeño"]

    esperas.clear()
    llm = LLMGuionizado(LimitePorMinuto("TPM", espera=2), LimitePorMinuto("TPM", espera=2), texto("ok"))
    agente = crear_agente(llm, RegistroHerramientas([]), ajustes, esperar=esperas.append)
    list(agente.responder([Mensaje.sistema("s"), Mensaje.usuario("hola")], ALEX))
    assert len(esperas) == 1 and [ll[0].modelo for ll in llm.llamadas] == ["grande", "grande", "pequeño"]  # solo una espera por modelo


def test_se_lee_el_tiempo_de_espera_que_indica_groq():
    from backend.adaptadores.salida.llm.openai_compat import _segundos_de_espera

    assert _segundos_de_espera("Rate limit reached ... Please try again in 4.205s. Need more tokens?") == 4.205
    assert _segundos_de_espera("Please try again in 250ms.") == 0.25
    assert _segundos_de_espera("sin dato") is None


# ------------------------------------------------------------------ respuestas sin respaldo (alucinaciones)

def test_cifras_inventadas_sin_consultar_datos_obligan_a_consultar():
    from backend.aplicacion.agente import AVISO_SIN_DATOS

    llm = LLMGuionizado(
        texto("En 2025 recibiste 96.770,00 € por Bizum."),   # sin llamar a ninguna herramienta
        llamada("consultar_saldo"),
        texto("Tienes 123,45 €"),
    )
    eventos, _ = correr(crear(llm))
    assert eventos[-1] == Fin("Tienes 123,45 €")
    assert any(m.rol == "user" and m.contenido == AVISO_SIN_DATOS for m in llm.llamadas[1][1])


def test_cifras_que_ya_salieron_en_la_conversacion_no_se_consideran_inventadas():
    llm = LLMGuionizado(texto("Como te dije, son 123,45 €."))
    mensajes = [Mensaje.sistema("s"), Mensaje.usuario("¿cuánto era?"), Mensaje.asistente("Tienes 123,45 €"), Mensaje.usuario("repítelo")]
    eventos = list(crear(llm).responder(mensajes, ALEX))
    assert len(llm.llamadas) == 1 and eventos[-1] == Fin("Como te dije, son 123,45 €.")


def test_si_ya_se_consultaron_datos_en_el_turno_no_se_vigilan_los_totales_calculados():
    llm = LLMGuionizado(llamada("consultar_saldo"), texto("Tienes 123,45 € y el doble serían 246,90 €."))
    eventos, _ = correr(crear(llm))
    assert len(llm.llamadas) == 2 and eventos[-1] == Fin("Tienes 123,45 € y el doble serían 246,90 €.")


def test_decir_aqui_tienes_el_grafico_sin_haberlo_generado_obliga_a_generarlo():
    config = '{"titulo": "G", "config": {"type": "bar", "data": {"labels": ["a"], "datasets": []}}}'
    llm = LLMGuionizado(
        texto("Resumen.\n\n**Gráfico comparativo:** barras agrupadas"),
        llamada("generar_grafico", config),
        texto("Hecho"),
    )
    eventos, _ = correr(crear(llm, extra=[grafico.crear()]))
    assert any(isinstance(e, Grafico) for e in eventos) and eventos[-1] == Fin("Hecho")


def test_el_gpt_oss_que_si_genera_el_grafico_no_recibe_correccion():
    config = '{"titulo": "G", "config": {"type": "bar", "data": {"labels": ["a"], "datasets": []}}}'
    llm = LLMGuionizado(llamada("generar_grafico", config), texto("Listo.\n\n**Gráfico:** G (barras)"))
    eventos, _ = correr(crear(llm, extra=[grafico.crear()]))
    assert len(llm.llamadas) == 2 and eventos[-1].texto.startswith("Listo.")


def test_si_fallan_todos_los_modelos_el_mensaje_es_claro_y_sugiere_encender_ollama():
    ajustes = AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "a", None)}, ollama_modelo="qwen", fallback_local=True))
    llm = LLMGuionizado(CuotaAgotada("429"), ProveedorInaccesible("sin red"))
    with pytest.raises(ErrorNoDisponible) as e:
        correr(crear(llm, ajustes))
    assert "todos los modelos de IA han alcanzado su límite" in e.value.mensaje and "ollama serve" in e.value.mensaje


# ------------------------------------------------------------------ modelos sin cuota y respuestas fijas de herramientas

def _ajustes_dos_modelos():
    return AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "grande", "pequeño")}, fallback_local=False))


def test_un_modelo_sin_cuota_diaria_no_se_vuelve_a_intentar_hasta_que_vuelva():
    from datetime import datetime

    from tests.fakes import RelojFijo, UsoEnMemoria

    reloj = RelojFijo(datetime(2026, 10, 3, 12, 0))
    llm = LLMGuionizado(CuotaAgotada("sin cuota", espera=900), texto("uno"), texto("dos"), texto("tres"))
    agente = crear_agente(llm, RegistroHerramientas([]), _ajustes_dos_modelos(), reloj=reloj)
    for turno in ("a", "b"):
        list(agente.responder([Mensaje.sistema("s"), Mensaje.usuario(turno)], ALEX))
    # el segundo turno ni siquiera prueba «grande»: no pierde tiempo con un modelo que se sabe agotado
    assert [ll[0].modelo for ll in llm.llamadas] == ["grande", "pequeño", "pequeño"]
    reloj.avanzar(16)  # 16 min después, pasados los 15 que indicó el proveedor
    list(agente.responder([Mensaje.sistema("s"), Mensaje.usuario("c")], ALEX))
    assert [ll[0].modelo for ll in llm.llamadas][-1] == "grande"


def test_un_limite_por_minuto_no_marca_al_modelo_como_agotado():
    llm = LLMGuionizado(LimitePorMinuto("TPM", espera=45), texto("ok"), texto("ok2"))
    agente = crear_agente(llm, RegistroHerramientas([]), _ajustes_dos_modelos())
    list(agente.responder([Mensaje.sistema("s"), Mensaje.usuario("a")], ALEX))
    list(agente.responder([Mensaje.sistema("s"), Mensaje.usuario("b")], ALEX))
    assert [ll[0].modelo for ll in llm.llamadas] == ["grande", "pequeño", "grande"]  # «grande» se prueba otra vez


def test_si_todos_estan_sin_cuota_se_dice_cuando_volver_sin_llamar_al_modelo():
    llm = LLMGuionizado(CuotaAgotada("x", espera=600), CuotaAgotada("y", espera=1800))
    agente = crear_agente(llm, RegistroHerramientas([]), _ajustes_dos_modelos())
    with pytest.raises(ErrorNoDisponible):
        list(agente.responder([Mensaje.sistema("s"), Mensaje.usuario("a")], ALEX))
    with pytest.raises(ErrorNoDisponible, match="Vuelve a probar sobre las 12:10"):
        list(agente.responder([Mensaje.sistema("s"), Mensaje.usuario("b")], ALEX))
    assert len(llm.llamadas) == 2  # el segundo turno no gastó ninguna llamada


def test_ollama_sin_el_modelo_descargado_dice_que_hay_que_hacer_pull():
    from backend.aplicacion.puertos.llm import ModeloNoEncontrado

    ajustes = AjustesEnMemoria(Ajustes(activo="groq", claves={"groq": ConfigClave("k", "a", None)}, ollama_modelo="qwen3:8b", fallback_local=True))
    llm = LLMGuionizado(CuotaAgotada("x"), ModeloNoEncontrado("no existe"))
    with pytest.raises(ErrorNoDisponible, match="ollama pull qwen3:8b"):
        correr(crear(llm, ajustes))


def test_una_herramienta_con_respuesta_final_termina_el_turno_sin_otra_vuelta_al_modelo():
    from backend.aplicacion.herramientas.registro import Herramienta, ResultadoHerramienta

    herramienta = Herramienta(
        EsquemaHerramienta("fija", "x", {}), lambda _a, _c: ResultadoHerramienta({"ok": True}, respuesta_final="Hecho al instante."), "…"
    )
    llm = LLMGuionizado(llamada("fija"), texto("no debería llamarse"))
    eventos, mensajes = correr(crear(llm, extra=[herramienta]))
    assert eventos[-1] == Fin("Hecho al instante.") and len(llm.llamadas) == 1
    assert mensajes[-1] == Mensaje.asistente("Hecho al instante.")
    # si el modelo ya había escrito algo antes de llamar a la herramienta, se conserva
    llm = LLMGuionizado([*texto("Voy con ello."), *llamada("fija")])
    eventos, _ = correr(crear(llm, extra=[herramienta]))
    assert eventos[-1] == Fin("Voy con ello.\n\nHecho al instante.")


def test_se_lee_la_espera_de_horas_minutos_y_segundos_que_indica_groq():
    from backend.adaptadores.salida.llm.openai_compat import _segundos_de_espera

    assert _segundos_de_espera("Please try again in 17m3.4s. Need more tokens?") == pytest.approx(1023.4)
    assert _segundos_de_espera("try again in 1h2m") == 3720
    assert _segundos_de_espera("try again in 2h0m0s") == 7200
