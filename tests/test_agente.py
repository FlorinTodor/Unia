import json

import pytest

from backend.aplicacion.agente import MAX_RONDAS, Agente
from backend.aplicacion.casos_uso.banco import ConsultarSaldo
from backend.aplicacion.eventos import Aviso, Delta, Fin, Grafico, HerramientaEnUso, OperacionPorConfirmar, UsoConsumido
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


def test_si_solo_algunas_herramientas_de_la_ronda_traen_respuesta_final_el_modelo_vuelve_a_hablar():
    from backend.aplicacion.eventos import Fin
    from backend.aplicacion.herramientas.registro import Herramienta, ResultadoHerramienta
    from backend.aplicacion.puertos.llm import PeticionHerramientas
    from backend.dominio.modelos import LlamadaHerramienta

    fija = Herramienta(EsquemaHerramienta("fija", "x", {}), lambda _a, _c: ResultadoHerramienta({}, respuesta_final="Hecho."), "…")
    datos = Herramienta(EsquemaHerramienta("datos", "x", {}), lambda _a, _c: ResultadoHerramienta({"saldo": 5}), "…")
    ronda = [PeticionHerramientas((LlamadaHerramienta("a", "fija", "{}"), LlamadaHerramienta("b", "datos", "{}")))]
    llm = LLMGuionizado(ronda, texto("Con los datos: 5."))
    eventos, _ = correr(crear(llm, extra=[fija, datos]))
    assert eventos[-1] == Fin("Con los datos: 5.") and len(llm.llamadas) == 2


def test_se_lee_la_espera_de_horas_minutos_y_segundos_que_indica_groq():
    from backend.adaptadores.salida.llm.openai_compat import _segundos_de_espera

    assert _segundos_de_espera("Please try again in 17m3.4s. Need more tokens?") == pytest.approx(1023.4)
    assert _segundos_de_espera("try again in 1h2m") == 3720
    assert _segundos_de_espera("try again in 2h0m0s") == 7200


# ------------------------------------------------------------------ validación de gráficos (incidencia 46)

def _config(labels, *series, tipo="bar"):
    return {"type": tipo, "data": {"labels": labels, "datasets": [{"label": n, "data": d} for n, d in series]}}


def test_el_agente_recibe_el_error_del_grafico_inventado_para_que_lo_corrija():
    import json
    mala = json.dumps({"titulo": "G", "config": _config(["a", "b"], ("X", [1, 2]), ("Total", [27000, 27000]))})
    buena = json.dumps({"titulo": "G", "config": _config(["a", "b"], ("X", [1, 2]))})
    llm = LLMGuionizado(llamada("generar_grafico", mala), llamada("generar_grafico", buena), texto("Hecho"))
    eventos, _ = correr(crear(llm, extra=[grafico.crear()]))
    assert len([e for e in eventos if isinstance(e, Grafico)]) == 1


# ------------------------------------------------------------------ respuesta vacía tras las herramientas

def test_respuesta_vacia_tras_herramientas_se_reintenta_pidiendo_el_grafico():
    """qwen3:8b consultaba movimientos y cerraba el turno con texto vacío sin generar el gráfico."""
    from backend.aplicacion.agente import aviso_haz_el_grafico
    config = '{"titulo": "G", "config": {"type": "bar", "data": {"labels": ["a"], "datasets": []}}}'
    llm = LLMGuionizado(llamada("consultar_saldo"), texto(""), llamada("generar_grafico", config), texto("Aquí lo tienes."))
    eventos, _ = correr(crear(llm, extra=[grafico.crear()]), "Hazme un gráfico de mis gastos por categoría del último mes")
    assert any(m.rol == "user" and m.contenido == aviso_haz_el_grafico("gráfico de mis gastos por categoría") for m in llm.llamadas[2][1])
    assert any(isinstance(e, Grafico) for e in eventos) and eventos[-1] == Fin("Aquí lo tienes.")


def test_respuesta_vacia_sin_grafico_pide_responder_y_si_sigue_vacia_da_un_mensaje_fijo():
    from backend.aplicacion.agente import AVISO_RESPONDE, MENSAJE_RESPUESTA_VACIA
    llm = LLMGuionizado(llamada("consultar_saldo"), texto(""), texto("  "))
    eventos, mensajes = correr(crear(llm), "¿cuánto tengo?")
    assert any(m.rol == "user" and m.contenido == AVISO_RESPONDE for m in llm.llamadas[2][1])
    assert eventos[-1] == Fin(MENSAJE_RESPUESTA_VACIA) and mensajes[-1] == Mensaje.asistente(MENSAJE_RESPUESTA_VACIA)


def test_el_empujon_del_grafico_nombra_la_herramienta_y_la_fuente_adecuada():
    """Incidencia 71: el aviso genérico no bastaba a qwen3:8b; ahora dice qué llamar y con qué fuente."""
    from backend.aplicacion.agente import aviso_haz_el_grafico
    aviso = aviso_haz_el_grafico("Hazme un gráfico de mis gastos por categoría del último mes")
    assert 'generar_grafico' in aviso and 'fuente="gastos_por_categoria"' in aviso
    assert 'fuente="gastos_por_mes"' in aviso_haz_el_grafico("dibújame la evolución mes a mes")


def test_si_pide_grafico_y_el_modelo_responde_con_texto_tras_consultar_se_le_empuja():
    from backend.aplicacion.agente import aviso_haz_el_grafico
    config = '{"titulo": "G", "config": {"type": "bar", "data": {"labels": ["a"], "datasets": []}}}'
    pregunta = "Dibújame un gráfico de barras de mis gastos por categoría"
    llm = LLMGuionizado(llamada("consultar_saldo"), texto("Supermercado 150 €, Ocio 30 €"), llamada("generar_grafico", config), texto("Listo."))
    eventos, _ = correr(crear(llm, extra=[grafico.crear()]), pregunta)
    assert any(m.rol == "user" and m.contenido == aviso_haz_el_grafico(pregunta) for m in llm.llamadas[2][1])
    assert any(isinstance(e, Grafico) for e in eventos)


def test_sin_pedir_grafico_un_texto_tras_consultar_no_recibe_empujon():
    llm = LLMGuionizado(llamada("consultar_saldo"), texto("Tienes 123,45 €"))
    eventos, _ = correr(crear(llm), "¿cuánto tengo?")
    assert len(llm.llamadas) == 2 and eventos[-1] == Fin("Tienes 123,45 €")


# ------------------------------------------------------------------ marca [auto] imitada por el modelo

def test_la_marca_auto_en_un_solo_delta_no_llega_al_cliente_ni_al_historial():
    eventos, mensajes = correr(crear(LLMGuionizado(texto("[auto] Solo se admiten euros."))))
    assert [e for e in eventos if isinstance(e, Delta)] == [Delta("Solo se admiten euros.")]
    assert eventos[-1] == Fin("Solo se admiten euros.")
    assert mensajes[-1] == Mensaje.asistente("Solo se admiten euros.")


def test_la_marca_auto_troceada_en_varios_deltas_tampoco_sale():
    eventos, mensajes = correr(crear(LLMGuionizado(texto("[", "au", "to", "] ", "Hola", " qué tal"))))
    assert "".join(e.texto for e in eventos if isinstance(e, Delta)) == "Hola qué tal"
    assert eventos[-1] == Fin("Hola qué tal") and mensajes[-1] == Mensaje.asistente("Hola qué tal")


def test_una_respuesta_normal_o_con_corchetes_legitimos_sale_intacta():
    for partes in (("Tu ", "saldo"), ("[1] Primero",), ("[", "x", "] va", " así")):
        eventos, _ = correr(crear(LLMGuionizado(texto(*partes))))
        assert "".join(e.texto for e in eventos if isinstance(e, Delta)) == "".join(partes)
        assert eventos[-1] == Fin("".join(partes))


def test_un_corchete_suelto_al_final_del_stream_no_se_pierde():
    eventos, _ = correr(crear(LLMGuionizado(texto("["))))
    assert eventos[-1] == Fin("[") and Delta("[") in eventos


def test_el_aviso_auto_del_servidor_sigue_llegando_al_modelo():
    from backend.aplicacion.agente import AVISO_CONTINUAR

    llm = LLMGuionizado(texto("Voy a consultar tu saldo. Un momento…"), texto("Listo"))
    correr(crear(llm))
    assert llm.llamadas[1][1][-1].contenido == AVISO_CONTINUAR and AVISO_CONTINUAR.startswith("[auto]")


# ------------------------------------------------------------------ empujón: Bizum pedido y no ejecutado

def _con_bizum(llm, contactos_extra=()):
    from backend.aplicacion.casos_uso.bizum import SolicitarBizum
    from backend.aplicacion.herramientas import bizum
    from backend.adaptadores.salida.persistencia.memoria_seguridad import OperacionesEnMemoria
    from backend.dominio.modelos import Contacto
    from tests.fakes import AuditoriaEnMemoria, CodigosFijos, ContactosEnMemoria, MovilFalso, RelojFijo

    agenda, operaciones = ContactosEnMemoria(), OperacionesEnMemoria()
    agenda.contactos[ALEX.id] += [Contacto(n, t) for n, t in contactos_extra]
    solicitar = SolicitarBizum(CuentaEnMemoria(2000.0), agenda, operaciones, CodigosFijos(), MovilFalso(), RelojFijo(), AuditoriaEnMemoria())
    return crear(llm, extra=[bizum.crear(solicitar)]), operaciones


def test_si_se_pide_un_bizum_completo_y_el_modelo_solo_pregunta_se_le_empuja_a_llamar_a_la_herramienta():
    from backend.aplicacion.agente import AVISO_HAZ_EL_BIZUM

    llm = LLMGuionizado(texto("¿Deseas enviar 1 € a María?"), llamada("transferencia_bizum", json.dumps({"destinatario": "María", "importe": 1})))
    agente, operaciones = _con_bizum(llm)
    eventos, _ = correr(agente, "Envía 1 euro por Bizum a María con concepto prueba")
    assert any(m.contenido == AVISO_HAZ_EL_BIZUM for m in llm.llamadas[1][1])
    assert eventos[-1].texto.startswith("He preparado el Bizum de 1,00 €")


def test_el_aviso_dice_que_no_se_pida_confirmacion_ni_se_invente_concepto():
    from backend.aplicacion.agente import AVISO_HAZ_EL_BIZUM

    for frase in ("YA", "tal como lo escribió", "no pidas confirmación", "no inventes concepto"):
        assert frase in AVISO_HAZ_EL_BIZUM


def test_si_tras_el_empujon_el_modelo_sigue_sin_llamar_la_herramienta_la_llama_el_servidor_y_solo_deja_una_pendiente():
    llm = LLMGuionizado(texto("¿Estás seguro de que quieres enviar 5 € a Dani?"), texto("¿Confirmas?"))
    agente, operaciones = _con_bizum(llm, [("Dani Ortega", "600999888")])
    eventos, mensajes = correr(agente, "Haz un bizum de 5 a dani")
    tarjetas = [e for e in eventos if isinstance(e, OperacionPorConfirmar)]
    assert len(tarjetas) == 1 and tarjetas[0].destinatario == "Dani Ortega" and tarjetas[0].importe == 5
    assert tarjetas[0].concepto == "Bizum"  # el usuario no dio concepto
    assert eventos[-1].texto.startswith("He preparado el Bizum de 5,00 € a Dani Ortega")
    assert len(llm.llamadas) == 2  # no hay tercera vuelta al modelo
    assert sum(1 for m in mensajes if m.rol == "tool") == 1


def test_orden_automatica_con_contacto_inexistente_no_crea_nada_y_el_modelo_lo_explica():
    llm = LLMGuionizado(texto("¿Seguro?"), texto("¿Confirmas?"), texto("No tienes ningún contacto llamado Pepe."))
    agente, _ = _con_bizum(llm)
    eventos, _ = correr(agente, "envía 5 euros por bizum a Pepe")
    assert not any(isinstance(e, OperacionPorConfirmar) for e in eventos)
    assert eventos[-1] == Fin("No tienes ningún contacto llamado Pepe.")


def test_orden_automatica_con_contacto_ambiguo_no_crea_nada():
    llm = LLMGuionizado(texto("¿Seguro?"), texto("¿Confirmas?"), texto("¿A cuál: Dani Ortega o Dani Pérez?"))
    agente, _ = _con_bizum(llm, [("Dani Ortega", "600999888"), ("Dani Pérez", "600999777")])
    eventos, mensajes = correr(agente, "haz un bizum de 5 a dani")
    assert not any(isinstance(e, OperacionPorConfirmar) for e in eventos)
    assert "coincide con varios" in next(m for m in mensajes if m.rol == "tool").contenido


def test_el_concepto_inventado_por_el_modelo_se_descarta_y_el_dicho_por_el_usuario_se_respeta():
    args = {"destinatario": "María", "importe": 5, "concepto": "Pago amigo"}
    llm = LLMGuionizado(llamada("transferencia_bizum", json.dumps(args)))
    agente, _ = _con_bizum(llm)
    eventos, _ = correr(agente, "Envíale un bizum de 5€ a María")
    assert [e.concepto for e in eventos if isinstance(e, OperacionPorConfirmar)] == ["Bizum"]

    args["concepto"] = "cena"
    llm = LLMGuionizado(llamada("transferencia_bizum", json.dumps(args)))
    agente, _ = _con_bizum(llm)
    eventos, _ = correr(agente, "Envíale un bizum de 5€ a María con concepto Cena")
    assert [e.concepto for e in eventos if isinstance(e, OperacionPorConfirmar)] == ["cena"]


def test_sin_orden_de_bizum_completa_no_hay_empujon():
    for pregunta in ("¿Qué es un Bizum?", "¿Cuánto he enviado por Bizum a María?", "envía un bizum de 500 USD a María",
                     "Envía 5000 euros por Bizum a María", "Envía un Bizum a María"):
        llm = LLMGuionizado(texto("Respuesta"))
        correr(crear(llm), pregunta)
        assert len(llm.llamadas) == 1, pregunta
