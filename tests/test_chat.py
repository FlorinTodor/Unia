from backend.aplicacion.agente import Agente
from backend.aplicacion.casos_uso.banco import ConsultarSaldo
from backend.aplicacion.chat import MAX_MENSAJES_HISTORIAL, ServicioChat, compactar_historial
from backend.aplicacion.eventos import Delta, ErrorChat, Fin
from backend.aplicacion.herramientas import saldo
from backend.aplicacion.herramientas.registro import RegistroHerramientas
from backend.adaptadores.salida.persistencia.sesiones_memoria import SesionesEnMemoria
from backend.dominio.modelos import LlamadaHerramienta, Mensaje
from tests.fakes import AjustesEnMemoria, CuentaEnMemoria, LLMGuionizado, RelojFijo, llamada, texto


def servicio(llm, sesiones=None):
    cuentas = CuentaEnMemoria()
    consultar = ConsultarSaldo(cuentas)
    agente = Agente(llm, RegistroHerramientas([saldo.crear(consultar)]), AjustesEnMemoria())
    sesiones = sesiones or SesionesEnMemoria()
    return ServicioChat(agente, sesiones, consultar, RelojFijo()), sesiones


def test_compactar_quita_trafico_de_herramientas_de_turnos_viejos():
    ll = LlamadaHerramienta("1", "consultar_saldo", "{}")
    historial = [
        Mensaje.sistema("s"),
        Mensaje.usuario("saldo"),
        Mensaje.asistente(None, (ll,)),
        Mensaje.resultado_herramienta("1", "{...}"),
        Mensaje.asistente("Tienes 5 €"),
        Mensaje.usuario("otra"),
        Mensaje.asistente(None, (ll,)),
        Mensaje.resultado_herramienta("1", "{...}"),
    ]
    compactado = compactar_historial(historial)
    assert [m.rol for m in compactado] == ["system", "user", "assistant", "user", "assistant", "tool"]
    assert compactado[2] == Mensaje.asistente("Tienes 5 €")  # turno viejo: solo texto
    assert compactado[-1].rol == "tool"  # turno en curso: intacto


def test_primer_mensaje_crea_sesion_con_system_prompt_con_fecha_y_titular():
    chat, sesiones = servicio(LLMGuionizado(texto("Hola")))
    assert list(chat.enviar("s1", "hola")) == [Delta("Hola"), Fin("Hola")]
    system = sesiones.obtener("s1")[0]
    assert system.rol == "system" and "2026-10-03" in system.contenido and "Alex García" in system.contenido


def test_la_sesion_conserva_el_historial_entre_turnos():
    llm = LLMGuionizado(texto("uno"), texto("dos"))
    chat, sesiones = servicio(llm)
    list(chat.enviar("s1", "a"))
    list(chat.enviar("s1", "b"))
    assert [m.contenido for m in sesiones.obtener("s1")[1:]] == ["a", "uno", "b", "dos"]
    assert len(llm.llamadas[1][1]) == 4  # system + a + uno + b


def test_historial_se_recorta_conservando_el_system():
    chat, sesiones = servicio(LLMGuionizado(*[texto("x")] * 30))
    for i in range(30):
        list(chat.enviar("s", f"m{i}"))
    mensajes = sesiones.obtener("s")
    assert len(mensajes) <= MAX_MENSAJES_HISTORIAL + 2 and mensajes[0].rol == "system"


def test_caracteres_invisibles_se_eliminan_de_la_salida():
    chat, _ = servicio(LLMGuionizado(texto("20​26")))
    assert list(chat.enviar("s", "x"))[-1] == Fin("2026")


def test_error_inesperado_llega_como_mensaje_generico_sin_filtrar_detalles():
    chat, sesiones = servicio(LLMGuionizado(RuntimeError("clave=secreto-de-prueba")))
    eventos = list(chat.enviar("s", "x"))
    assert len(eventos) == 1 and isinstance(eventos[0], ErrorChat)
    assert "secreto-de-prueba" not in eventos[0].mensaje
    assert sesiones.obtener("s") is not None  # la sesión se guarda aunque falle
