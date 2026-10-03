"""Control del gasto de tokens: medición, límites y reducción de lo que se envía al modelo."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.adaptadores.salida.llm.openai_compat import ProveedorLLMOpenAI, _uso_informado
from backend.adaptadores.salida.persistencia.limitador import LimitadorEnMemoria
from backend.adaptadores.salida.persistencia.memoria_seguridad import OperacionesEnMemoria
from backend.adaptadores.salida.persistencia.sesiones_memoria import SesionesEnMemoria
from backend.adaptadores.salida.sqlite import esquema
from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.adaptadores.salida.sqlite.uso import UsoSqlite
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.aplicacion.agente import MENSAJE_LIMITE_DIA, MENSAJE_LIMITE_TURNO
from backend.aplicacion.casos_uso.banco import ConsultarSaldo
from backend.aplicacion.chat import ServicioChat, _recortar
from backend.aplicacion.eventos import Fin, UsoConsumido
from backend.aplicacion.herramientas import movimientos, saldo
from backend.aplicacion.herramientas.registro import RegistroHerramientas
from backend.aplicacion.puertos.llm import DeltaTexto, UsoTokens
from backend.dominio import uso as dominio_uso
from backend.dominio.errores import DemasiadasPeticiones, ErrorDeValidacion, LimiteDeTokensExcedido, MensajeDemasiadoLargo
from backend.dominio.modelos import Mensaje
from backend.dominio.proveedores import ModeloRef
from backend.dominio.uso import PresupuestoUso, Uso, estimar_tokens
from tests.fakes import ALEX, ANA, CuentaEnMemoria, LLMGuionizado, RelojFijo, UsoEnMemoria, AjustesEnMemoria, crear_agente, llamada, texto


# ------------------------------------------------------------------ dominio

def test_uso_se_suma_y_marca_estimado_si_alguno_lo_es():
    u = Uso(100, 50) + Uso(10, 5, estimado=True)
    assert (u.entrada, u.salida, u.total, u.estimado) == (110, 55, 165, True)


def test_estimar_tokens_es_aproximado_y_nunca_cero_para_texto_con_contenido():
    assert estimar_tokens("") == 0 and estimar_tokens("hola") == 2 and 280 <= estimar_tokens("a" * 1000) <= 320


def test_mensaje_vacio_o_demasiado_largo_se_rechaza():
    p = PresupuestoUso(max_caracteres_mensaje=10)
    assert dominio_uso.validar_mensaje("  hola  ", p) == "hola"
    with pytest.raises(ErrorDeValidacion):
        dominio_uso.validar_mensaje("   ", p)
    with pytest.raises(MensajeDemasiadoLargo, match="11 caracteres; máximo 10"):
        dominio_uso.validar_mensaje("x" * 11, p)


def test_la_cuota_diaria_indica_cuanto_falta_para_medianoche():
    p = PresupuestoUso(tokens_por_dia=1000)
    dominio_uso.comprobar_cuota_diaria(999, p, datetime(2026, 10, 3, 12, 0))
    with pytest.raises(LimiteDeTokensExcedido) as e:
        dominio_uso.comprobar_cuota_diaria(1000, p, datetime(2026, 10, 3, 18, 0))
    assert e.value.reintentar_en == 6 * 3600 and "1.000 tokens" in e.value.mensaje


# ------------------------------------------------------------------ limitador

def test_el_limitador_permite_n_por_minuto_y_dice_cuanto_esperar():
    lim, t0 = LimitadorEnMemoria(3), datetime(2026, 10, 3, 12, 0, 0)
    assert [lim.permitir(1, t0 + timedelta(seconds=i)) for i in range(3)] == [None, None, None]
    espera = lim.permitir(1, t0 + timedelta(seconds=10))
    assert espera is not None and 50 <= espera <= 52
    assert lim.permitir(2, t0 + timedelta(seconds=10)) is None  # otro cliente: su propio contador
    assert lim.permitir(1, t0 + timedelta(seconds=61)) is None  # la ventana se desliza


# ------------------------------------------------------------------ servicio de chat

def montar(llm, presupuesto=None, uso=None, reloj=None):
    presupuesto = presupuesto or PresupuestoUso()
    reloj = reloj or RelojFijo()
    uso = uso if uso is not None else UsoEnMemoria()
    agente = crear_agente(llm, RegistroHerramientas([saldo.crear(ConsultarSaldo(CuentaEnMemoria()))]), uso=uso, presupuesto=presupuesto, reloj=reloj)
    chat = ServicioChat(agente, SesionesEnMemoria(), reloj, uso, LimitadorEnMemoria(presupuesto.peticiones_por_minuto), presupuesto, OperacionesEnMemoria())
    return chat, uso, reloj


def test_un_mensaje_demasiado_largo_se_rechaza_antes_de_llamar_al_modelo():
    llm = LLMGuionizado()
    chat, uso, _ = montar(llm, PresupuestoUso(max_caracteres_mensaje=20))
    with pytest.raises(MensajeDemasiadoLargo):
        chat.enviar(ALEX, "s", "x" * 21)  # lanza al llamar, no al iterar: el HTTP puede responder 413
    with pytest.raises(ErrorDeValidacion):
        chat.enviar(ALEX, "s", "   ")
    assert llm.llamadas == [] and uso.registros == []


def test_demasiadas_peticiones_por_minuto_429_con_espera():
    chat, _, reloj = montar(LLMGuionizado(*[texto("x")] * 5), PresupuestoUso(peticiones_por_minuto=2))
    for _ in range(2):
        list(chat.enviar(ALEX, "s", "hola"))
    with pytest.raises(DemasiadasPeticiones) as e:
        chat.enviar(ALEX, "s", "hola")
    assert e.value.reintentar_en and e.value.reintentar_en <= 61
    list(chat.enviar(ANA, "s", "hola"))  # el límite es por cliente
    reloj.avanzar(2)  # dos minutos después la ventana se ha deslizado
    assert list(chat.enviar(ALEX, "s", "hola"))[-1] == Fin("x")


def test_cuota_diaria_agotada_rechaza_el_turno_y_no_afecta_a_otro_cliente_ni_al_dia_siguiente():
    uso = UsoEnMemoria()
    reloj = RelojFijo(datetime(2026, 10, 3, 12, 0))
    uso.registrar(ALEX.id, "groq", "m", Uso(60, 40), reloj.ahora())
    chat, _, _ = montar(LLMGuionizado(texto("a"), texto("b")), PresupuestoUso(tokens_por_dia=100), uso, reloj)
    with pytest.raises(LimiteDeTokensExcedido):
        chat.enviar(ALEX, "s", "hola")
    assert list(chat.enviar(ANA, "s", "hola"))[-1] == Fin("a")  # Ana no ha gastado nada
    reloj.avanzar(24 * 60)  # mañana
    assert list(chat.enviar(ALEX, "s", "hola"))[-1] == Fin("b")


def _con_ia_local(llm, uso, reloj, presupuesto):
    ajustes = AjustesEnMemoria()
    ajustes.ajustes.fallback_local = True
    agente = crear_agente(llm, RegistroHerramientas([saldo.crear(ConsultarSaldo(CuentaEnMemoria()))]), ajustes=ajustes, uso=uso, presupuesto=presupuesto, reloj=reloj)
    return ServicioChat(agente, SesionesEnMemoria(), reloj, uso, LimitadorEnMemoria(presupuesto.peticiones_por_minuto), presupuesto, OperacionesEnMemoria()), agente


def test_los_tokens_del_modelo_local_no_cuentan_para_la_cuota_diaria():
    uso = UsoEnMemoria()
    reloj = RelojFijo(datetime(2026, 10, 3, 12, 0))
    uso.registrar(ALEX.id, "ollama", "qwen3:8b", Uso(90_000, 5_000), reloj.ahora())
    uso.registrar(ALEX.id, "groq", "m", Uso(30, 20), reloj.ahora())
    assert uso.tokens_del_dia(ALEX.id, reloj.hoy()) == 50


def test_con_la_nube_agotada_se_atiende_con_el_modelo_local_en_vez_de_un_429():
    uso = UsoEnMemoria()
    reloj = RelojFijo(datetime(2026, 10, 3, 12, 0))
    uso.registrar(ALEX.id, "groq", "m", Uso(60, 40), reloj.ahora())
    llm = LLMGuionizado(texto("respuesta local"))
    chat, agente = _con_ia_local(llm, uso, reloj, PresupuestoUso(tokens_por_dia=100))
    assert agente.tiene_respaldo_local()
    assert list(chat.enviar(ALEX, "s", "hola"))[-1] == Fin("respuesta local")
    assert all(l[0].proveedor == "ollama" for l in llm.llamadas)  # no se toca la nube agotada


def test_si_la_nube_se_agota_y_no_hay_modelo_local_sigue_el_429():
    uso = UsoEnMemoria()
    reloj = RelojFijo(datetime(2026, 10, 3, 12, 0))
    uso.registrar(ALEX.id, "groq", "m", Uso(60, 40), reloj.ahora())
    chat, _, _ = montar(LLMGuionizado(texto("a")), PresupuestoUso(tokens_por_dia=100), uso, reloj)
    with pytest.raises(LimiteDeTokensExcedido):
        chat.enviar(ALEX, "s", "hola")


def test_cada_llamada_al_modelo_se_registra_con_cliente_proveedor_y_modelo():
    llm = LLMGuionizado(llamada("consultar_saldo"), texto("Tienes 500,00 €"), uso=Uso(1000, 200))
    chat, uso, reloj = montar(llm)
    eventos = list(chat.enviar(ALEX, "s", "¿cuánto tengo?"))
    assert [(r[0], r[1], r[2], r[3].total) for r in uso.registros] == [(1, "groq", "modelo-a", 1200), (1, "groq", "modelo-a", 1200)]
    assert uso.tokens_del_dia(ALEX.id, reloj.hoy()) == 2400 and uso.tokens_del_dia(ANA.id, reloj.hoy()) == 0
    assert UsoConsumido(2400, 2400, 80_000) in eventos


def test_al_modelo_se_le_pasa_el_tope_de_tokens_de_respuesta():
    llm = LLMGuionizado(llamada("consultar_saldo"), texto("ok"))
    chat, *_ = montar(llm, PresupuestoUso(max_tokens_respuesta=1234))
    list(chat.enviar(ALEX, "s", "hola"))
    assert llm.max_tokens == [1234, 1234]


# ------------------------------------------------------------------ límites dentro del turno

def test_si_un_turno_supera_su_tope_no_se_hacen_mas_rondas():
    llm = LLMGuionizado(llamada("consultar_saldo"), llamada("consultar_saldo"), texto("nunca llega"), uso=Uso(20_000, 5_000))
    chat, uso, _ = montar(llm, PresupuestoUso(tokens_por_turno=30_000))
    eventos = list(chat.enviar(ALEX, "s", "hola"))
    assert eventos[-1] == Fin(MENSAJE_LIMITE_TURNO)
    assert len(llm.llamadas) == 2  # ronda 1 (25k) + ronda 2 (50k ≥ 30k): se corta antes de ejecutar más
    assert len(uso.registros) == 2


def test_una_respuesta_final_completa_no_se_descarta_aunque_haya_superado_el_tope():
    llm = LLMGuionizado(texto("Respuesta completa."), uso=Uso(50_000, 5_000))
    eventos = list(montar(llm, PresupuestoUso(tokens_por_turno=30_000))[0].enviar(ALEX, "s", "hola"))
    assert eventos[-1] == Fin("Respuesta completa.")


def test_si_el_dia_se_agota_a_mitad_de_turno_se_corta_con_el_mensaje_del_dia():
    uso = UsoEnMemoria()
    reloj = RelojFijo()
    uso.registrar(ALEX.id, "groq", "m", Uso(900, 0), reloj.ahora())
    llm = LLMGuionizado(llamada("consultar_saldo"), texto("nunca llega"), uso=Uso(100, 50))
    chat, *_ = montar(llm, PresupuestoUso(tokens_por_dia=1000), uso, reloj)
    assert list(chat.enviar(ALEX, "s", "hola"))[-1] == Fin(MENSAJE_LIMITE_DIA)


# ------------------------------------------------------------------ reducir lo que se envía

def test_el_historial_se_recorta_por_tokens_conservando_system_y_ultimo_turno():
    historial = [Mensaje.sistema("s")]
    for i in range(10):
        historial += [Mensaje.usuario(f"pregunta {i} " + "x" * 400), Mensaje.asistente(f"respuesta {i} " + "y" * 400)]
    historial.append(Mensaje.usuario("la última pregunta"))
    recortado = _recortar(list(historial), max_tokens=500)
    assert recortado[0].rol == "system" and recortado[-1].contenido == "la última pregunta"
    assert sum(estimar_tokens(m.contenido) for m in recortado[1:-1]) <= 500
    assert "pregunta 0" not in " ".join(m.contenido for m in recortado)  # se pierde lo más antiguo
    assert "respuesta 9" in " ".join(m.contenido for m in recortado)  # lo reciente se conserva


def test_un_resultado_sql_enorme_se_recorta_para_no_pagarlo_en_cada_ronda():
    filas = [[f"2026-01-{i % 28 + 1:02d}", "Supermercado", f"Compra {i} " + "x" * 30, -12.5] for i in range(60)]
    datos = {"ok": True, "columnas": ["fecha", "categoria", "concepto", "importe"], "filas": filas, "num_filas": 60, "truncado": False}
    r = movimientos.limitar_tamano(datos, 2_000)
    assert len(json.dumps(r, ensure_ascii=False)) <= 2_000 and r["truncado"] and r["num_filas"] < 60 and "recortado" in r["nota"]
    pequeno = {**datos, "filas": filas[:3], "num_filas": 3}
    assert movimientos.limitar_tamano(pequeno, 2_000) == pequeno  # lo pequeño no se toca


# ------------------------------------------------------------------ adaptador del proveedor

def _chunk(contenido=None, usage=None, extra=None):
    elegidos = [SimpleNamespace(delta=SimpleNamespace(content=contenido, tool_calls=None))] if contenido is not None else []
    return SimpleNamespace(choices=elegidos, usage=usage, model_extra=extra)


class _ClienteFalso:
    def __init__(self, chunks):
        self.peticiones = []
        self._chunks = chunks
        outer = self
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: (outer.peticiones.append(kw), iter(outer._chunks))[1]))


class _Fabrica:
    def __init__(self, cliente):
        self._cliente = cliente

    def cliente(self, _proveedor, **_):
        return self._cliente


def _llamar(proveedor, modelo, chunks, max_tokens=None):
    cliente = _ClienteFalso(chunks)
    eventos = list(ProveedorLLMOpenAI(_Fabrica(cliente)).completar(ModeloRef(proveedor, modelo), [Mensaje.usuario("hola")], None, max_tokens))
    return cliente.peticiones[0], eventos


def test_se_lee_el_uso_real_que_informa_el_proveedor():
    usage = SimpleNamespace(prompt_tokens=1234, completion_tokens=56)
    peticion, eventos = _llamar("groq", "openai/gpt-oss-120b", [_chunk("Hola"), _chunk(usage=usage)])
    assert peticion["stream_options"] == {"include_usage": True}
    assert eventos == [DeltaTexto("Hola"), UsoTokens(Uso(1234, 56, estimado=False))]


def test_groq_puede_informar_el_uso_en_x_groq():
    chunk = _chunk(extra={"x_groq": {"usage": {"prompt_tokens": 10, "completion_tokens": 3}}})
    assert _uso_informado(chunk) == Uso(10, 3)
    assert _uso_informado(_chunk("sin uso")) is None


def test_si_el_proveedor_no_informa_el_uso_se_estima_y_se_marca():
    peticion, eventos = _llamar("gemini", "gemini-2.5-flash", [_chunk("Hola " * 100)])
    assert "stream_options" not in peticion  # Gemini no lo soporta: no se envía
    uso = eventos[-1].uso
    assert uso.estimado and uso.entrada > 0 and uso.salida > 100


def test_el_tope_de_salida_usa_el_parametro_que_acepta_cada_proveedor():
    peticion, _ = _llamar("groq", "openai/gpt-oss-120b", [_chunk("x")], max_tokens=2048)
    assert peticion["max_tokens"] == 2048 and "max_completion_tokens" not in peticion
    peticion, _ = _llamar("openai", "gpt-5-mini", [_chunk("x")], max_tokens=2048)
    assert peticion["max_completion_tokens"] == 2048 and "max_tokens" not in peticion
    peticion, _ = _llamar("groq", "openai/gpt-oss-120b", [_chunk("x")])
    assert "max_tokens" not in peticion


# ------------------------------------------------------------------ SQLite

@pytest.fixture
def bd(tmp_path):
    bd = BaseDeDatos(tmp_path / "banco.db")
    esquema.inicializar(bd, RelojFijo(), HasheadorScrypt())
    return bd


def test_el_uso_se_guarda_en_sqlite_por_cliente_y_dia(bd):
    uso = UsoSqlite(bd)
    hoy = datetime(2026, 10, 3, 23, 59)
    uso.registrar(1, "groq", "m1", Uso(100, 20), hoy)
    uso.registrar(1, "groq", "m1", Uso(30, 5, estimado=True), hoy)
    uso.registrar(2, "groq", "m1", Uso(7, 7), hoy)
    uso.registrar(1, "groq", "m1", Uso(999, 1), hoy - timedelta(days=1))  # ayer
    assert uso.tokens_del_dia(1, hoy.date()) == 155 and uso.tokens_del_dia(2, hoy.date()) == 14
    ultimos = uso.ultimos(1, 2)
    assert ultimos[0] == {"momento": "2026-10-03T23:59:00", "modelo": "m1", "entrada": 30, "salida": 5, "estimado": True}


def test_la_tabla_de_uso_se_crea_tambien_en_bases_ya_existentes_sin_regenerarlas(bd):
    con = bd.abrir()
    con.execute("DROP TABLE uso_ia")
    con.execute("INSERT INTO movimientos (cliente_id, fecha, categoria, concepto, comercio, importe) VALUES (1,'2026-10-03','Bizum','mi bizum','Bizum',-1)")
    con.commit()
    con.close()
    esquema.inicializar(bd, RelojFijo(), HasheadorScrypt())
    con = bd.abrir(solo_lectura=True)
    assert con.execute("SELECT COUNT(*) FROM uso_ia").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM movimientos WHERE concepto = 'mi bizum'").fetchone()[0] == 1  # no se regeneró
    con.close()


def test_el_perfil_de_administracion_no_puede_usar_el_chat():
    from dataclasses import replace

    from backend.dominio.errores import ErrorDeAccesoDenegado

    chat, _, _ = montar(LLMGuionizado(texto("a")))
    with pytest.raises(ErrorDeAccesoDenegado):
        chat.enviar(replace(ALEX, es_admin=True), "s", "hola")
