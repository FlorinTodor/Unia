from backend.aplicacion.casos_uso.banco import ConsultarSaldo
from backend.aplicacion.chat import MAX_MENSAJES_HISTORIAL, ServicioChat, compactar_historial
from backend.aplicacion.eventos import Delta, ErrorChat, Fin, UsoConsumido
from backend.aplicacion.herramientas import saldo
from backend.aplicacion.herramientas.registro import RegistroHerramientas
from backend.adaptadores.salida.persistencia.memoria_seguridad import OperacionesEnMemoria
from backend.adaptadores.salida.persistencia.sesiones_memoria import SesionesEnMemoria
from backend.dominio.modelos import LlamadaHerramienta, Mensaje
from tests.fakes import ALEX, ANA, CuentaEnMemoria, LLMGuionizado, RelojFijo, UsoEnMemoria, crear_agente, llamada, texto
from backend.adaptadores.salida.persistencia.limitador import LimitadorEnMemoria
from backend.dominio.uso import PresupuestoUso


def servicio(llm, sesiones=None, presupuesto=None, reloj=None, uso=None):
    consultar = ConsultarSaldo(CuentaEnMemoria())
    presupuesto = presupuesto or PresupuestoUso()
    reloj = reloj or RelojFijo()
    uso = uso if uso is not None else UsoEnMemoria()
    agente = crear_agente(llm, RegistroHerramientas([saldo.crear(consultar)]), uso=uso, presupuesto=presupuesto, reloj=reloj)
    sesiones = sesiones or SesionesEnMemoria()
    chat = ServicioChat(agente, sesiones, reloj, uso, LimitadorEnMemoria(presupuesto.peticiones_por_minuto), presupuesto, OperacionesEnMemoria())
    return chat, sesiones


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
    assert list(chat.enviar(ALEX, "s1", "hola")) == [Delta("Hola"), UsoConsumido(150, 150, 80_000), Fin("Hola")]
    system = sesiones.obtener("1:s1")[0]
    assert system.rol == "system" and "2026-10-03" in system.contenido and "Alex García" in system.contenido
    assert "Te llamas Unia" in system.contenido


def test_la_sesion_conserva_el_historial_entre_turnos():
    llm = LLMGuionizado(texto("uno"), texto("dos"))
    chat, sesiones = servicio(llm)
    list(chat.enviar(ALEX, "s1", "a"))
    list(chat.enviar(ALEX, "s1", "b"))
    assert [m.contenido for m in sesiones.obtener("1:s1")[1:]] == ["a", "uno", "b", "dos"]
    assert len(llm.llamadas[1][1]) == 4  # system + a + uno + b


def test_historial_se_recorta_conservando_el_system():
    chat, sesiones = servicio(LLMGuionizado(*[texto("x")] * 30), presupuesto=PresupuestoUso(peticiones_por_minuto=1000))
    for i in range(30):
        list(chat.enviar(ALEX, "s", f"m{i}"))
    mensajes = sesiones.obtener("1:s")
    assert len(mensajes) <= MAX_MENSAJES_HISTORIAL + 2 and mensajes[0].rol == "system"


def test_caracteres_invisibles_se_eliminan_de_la_salida():
    chat, _ = servicio(LLMGuionizado(texto("20​26")))
    assert list(chat.enviar(ALEX, "s", "x"))[-1] == Fin("2026")


def test_error_inesperado_llega_como_mensaje_generico_sin_filtrar_detalles():
    chat, sesiones = servicio(LLMGuionizado(RuntimeError("clave=secreto-de-prueba")))
    eventos = list(chat.enviar(ALEX, "s", "x"))
    assert len(eventos) == 1 and isinstance(eventos[0], ErrorChat)
    assert "secreto-de-prueba" not in eventos[0].mensaje
    assert sesiones.obtener("1:s") is not None  # la sesión se guarda aunque falle


def test_la_sesion_de_chat_pertenece_al_cliente_aunque_comparta_id():
    """Ana usa el mismo id de sesión que Alex y no ve su conversación."""
    llm = LLMGuionizado(texto("secreto de Alex"), texto("hola Ana"))
    chat, sesiones = servicio(llm)
    list(chat.enviar(ALEX, "misma", "dato privado"))
    list(chat.enviar(ANA, "misma", "hola"))
    assert [m.contenido for m in sesiones.obtener("2:misma") if m.rol != "system"] == ["hola", "hola Ana"]
    assert "Ana Ruiz" in sesiones.obtener("2:misma")[0].contenido
    assert all("dato privado" not in (m.contenido or "") for m in llm.llamadas[1][1])


def test_el_empujon_automatico_de_un_turno_viejo_no_se_arrastra_ni_cuenta_como_turno():
    from backend.aplicacion.agente import AVISO_CONTINUAR

    historial = [
        Mensaje.sistema("s"),
        Mensaje.usuario("pregunta 1"),
        Mensaje.asistente("Voy a ver. Un momento…"),
        Mensaje.usuario(AVISO_CONTINUAR),
        Mensaje.asistente("Respuesta 1"),
        Mensaje.usuario("pregunta 2"),
        Mensaje.asistente("Respuesta 2"),
    ]
    assert [m.contenido for m in compactar_historial(historial)] == [
        "s", "pregunta 1", "Voy a ver. Un momento…", "Respuesta 1", "pregunta 2", "Respuesta 2",
    ]
    # si el empujón es del turno en curso (último), se conserva: el agente aún lo necesita
    en_curso = [Mensaje.sistema("s"), Mensaje.usuario("p"), Mensaje.asistente("Voy a ver."), Mensaje.usuario(AVISO_CONTINUAR)]
    assert compactar_historial(en_curso)[-1].contenido == AVISO_CONTINUAR


# ------------------------------------------------------------------ el modelo se entera de cómo acabó el Bizum

def test_el_modelo_recibe_el_resultado_de_la_operacion_en_el_turno_siguiente():
    import json

    from backend.adaptadores.salida.persistencia.memoria_seguridad import OperacionesEnMemoria
    from backend.aplicacion.casos_uso.bizum import SolicitarBizum
    from backend.aplicacion.herramientas import bizum
    from backend.dominio.operaciones import EstadoOperacion
    from tests.fakes import AuditoriaEnMemoria, CodigosFijos, ContactosEnMemoria, MovilFalso

    cuentas, reloj, operaciones = CuentaEnMemoria(), RelojFijo(), OperacionesEnMemoria()
    solicitar = SolicitarBizum(cuentas, ContactosEnMemoria(), operaciones, CodigosFijos(), MovilFalso(), reloj, AuditoriaEnMemoria())
    llm = LLMGuionizado(
        llamada("transferencia_bizum", json.dumps({"destinatario": "María", "importe": 10})),  # el turno acaba solo: no hay 2.ª llamada
        texto("Está cancelada"),
        texto("Ya sin avisos"),
    )
    presupuesto, uso = PresupuestoUso(), UsoEnMemoria()
    agente = crear_agente(llm, RegistroHerramientas([bizum.crear(solicitar)]), uso=uso, presupuesto=presupuesto, reloj=reloj)
    chat = ServicioChat(agente, SesionesEnMemoria(), reloj, uso, LimitadorEnMemoria(1000), presupuesto, operaciones)

    list(chat.enviar(ALEX, "s", "envía 10 a María"))
    list(chat.enviar(ALEX, "s", "¿y ahora?"))  # el cliente aún no ha hecho nada: no hay aviso
    assert not any(m.rol == "user" and "[auto]" in (m.contenido or "") for m in llm.llamadas[1][1])
    operaciones.obtener("op1").estado = EstadoOperacion.BLOQUEADA  # el cliente falló el código tres veces fuera del chat
    list(chat.enviar(ALEX, "s", "pero no ha funcionado"))
    avisos = [m.contenido for m in llm.llamadas[2][1] if m.rol == "user" and "[auto]" in (m.contenido or "")]
    assert avisos == ["[auto] Resultado del Bizum de 10,00 € a María López: BLOQUEADA por demasiados códigos erróneos: no se ha enviado nada."]


# ------------------------------------------------------------------ un solo turno a la vez por cliente (A-2)

class _LLMBloqueado(LLMGuionizado):
    """Se queda esperando dentro del turno hasta que el test lo suelte (simula un turno lento)."""

    def __init__(self, *pasos):
        super().__init__(*pasos)
        import threading
        self.dentro = threading.Event()
        self.soltar = threading.Event()

    def completar(self, modelo, mensajes, herramientas, max_tokens=None):
        self.dentro.set()
        assert self.soltar.wait(5)
        yield from super().completar(modelo, mensajes, herramientas, max_tokens)


def test_veinte_peticiones_en_paralelo_solo_dejan_pasar_una():
    """Antes pasaban todas la comprobación del tope diario porque el gasto se anota al terminar el turno."""
    import threading
    from backend.dominio.errores import TurnoEnCurso
    llm = _LLMBloqueado(texto("ok"))
    chat, _ = servicio(llm)
    resultados = []

    def lanzar():
        try:
            resultados.append(("ok", list(chat.enviar(ALEX, "s", "hola"))))
        except TurnoEnCurso as e:
            resultados.append(("429", e))

    primero = threading.Thread(target=lanzar)
    primero.start()
    assert llm.dentro.wait(5)
    otros = [threading.Thread(target=lanzar) for _ in range(19)]
    for h in otros:
        h.start()
    for h in otros:
        h.join(5)
    assert [r[0] for r in resultados] == ["429"] * 19 and resultados[0][1].reintentar_en
    llm.soltar.set()
    primero.join(5)
    assert sum(r[0] == "ok" for r in resultados) == 1
    assert ANA.id != ALEX.id  # otro cliente no se ve afectado
    llm2 = LLMGuionizado(texto("hola"))
    assert list(servicio(llm2)[0].enviar(ALEX, "s", "otra"))  # y el cliente puede volver a preguntar tras terminar


def test_el_turno_se_libera_si_falla_o_si_nunca_se_consume():
    import pytest
    from backend.dominio.errores import ErrorDeValidacion
    chat, _ = servicio(LLMGuionizado(texto("uno"), texto("dos"), texto("tres")))
    with pytest.raises(ErrorDeValidacion):
        chat.enviar(ALEX, "s", "   ")  # rechazado antes de reservar
    abandonado = chat.enviar(ALEX, "s", "a")  # nunca se itera (el cliente se desconectó)
    abandonado.close()
    assert list(chat.enviar(ALEX, "s", "b"))
    del_sin_cerrar = chat.enviar(ALEX, "s", "c")
    del del_sin_cerrar  # el recolector lo libera
    assert list(chat.enviar(ALEX, "s", "d")) is not None


def test_liberar_el_turno_no_toma_el_cerrojo_y_no_se_interbloquea():
    """Medio-8: `__del__` liberaba con un `threading.Lock` no reentrante; el GC podía dispararlo con el cerrojo tomado."""
    import threading
    chat, _ = servicio(LLMGuionizado(texto("a")))
    turno = chat.enviar(ALEX, "s", "hola")
    hecho = threading.Event()

    def liberar_con_el_cerrojo_tomado():
        with chat._en_curso_guarda:
            turno.close()
        hecho.set()

    hilo = threading.Thread(target=liberar_con_el_cerrojo_tomado, daemon=True)
    hilo.start()
    assert hecho.wait(2), "interbloqueo al liberar con el cerrojo tomado"


def test_el_prompt_y_la_herramienta_avisan_de_que_printf_esta_bloqueado():
    """Medio-11: el consultor veta printf/format; el modelo debe usar ROUND(x, 2) desde el principio."""
    from backend.aplicacion.herramientas import movimientos
    chat, sesiones = servicio(LLMGuionizado(texto("Hola")))
    list(chat.enviar(ALEX, "s1", "hola"))
    assert "ROUND(x, 2)" in sesiones.obtener("1:s1")[0].contenido
    herramienta = movimientos.crear(lambda *a, **k: None)
    assert "ROUND(x, 2)" in herramienta.esquema.descripcion
