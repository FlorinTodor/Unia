"""Bloqueo y desbloqueo de tarjetas: dominio, casos de uso, herramientas, red de seguridad del agente y migración."""
import json
import sqlite3
from datetime import datetime

import pytest

from backend.adaptadores.salida.persistencia.memoria_seguridad import OperacionesEnMemoria
from backend.adaptadores.salida.persistencia.sqlite_estado import OperacionesSqlite
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.adaptadores.salida.sqlite import esquema
from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.adaptadores.salida.sqlite.consultor import ConsultorMovimientosSqlite
from backend.adaptadores.salida.sqlite.repositorios import RepositorioClientesSqlite, RepositorioCuentaSqlite, RepositorioTarjetasSqlite
from backend.aplicacion.casos_uso.bizum import CancelarOperacion, CerrojosPorCliente, ConfirmarOperacion
from backend.aplicacion.casos_uso.tarjetas import BloquearTarjeta, ConsultarTarjetas, DesbloquearTarjeta, SolicitarDesbloqueoTarjeta
from backend.aplicacion.chat import ServicioChat
from backend.aplicacion.eventos import Fin, OperacionPorConfirmar, TarjetaMostrada
from backend.aplicacion.herramientas import tarjetas as herramienta_tarjetas
from backend.aplicacion.herramientas.registro import Herramienta, RegistroHerramientas, Riesgo
from backend.aplicacion.puertos.llm import EsquemaHerramienta, PeticionHerramientas
from backend.aplicacion.herramientas.tarjetas import RECHAZO_SIN_ORDEN_DE_BLOQUEO
from backend.aplicacion.texto import (
    datos_de_tarjeta, enmascarar_numeros_largos, es_aclaracion_de_tarjeta, habla_de_tarjetas, pide_bloquear_tarjeta,
)
from backend.dominio import reglas
from backend.dominio.errores import (
    CodigoIncorrecto,
    ConsultaNoPermitida,
    OperacionNoEncontrada,
    OperacionYaProcesada,
    TarjetaAmbigua,
    TarjetaNoEncontrada,
    TarjetaYaActiva,
    TarjetaYaBloqueada,
)
from backend.dominio.modelos import LlamadaHerramienta, Mensaje, Movimiento, Tarjeta
from backend.dominio.operaciones import EstadoOperacion, TipoOperacion
from tests.fakes import (
    ALEX, ANA, AuditoriaEnMemoria, CodigosFijos, LLMGuionizado, MovilFalso, RelojFijo, TarjetasEnMemoria, crear_agente, llamada, texto,
)

VISA = Tarjeta(1, "Visa", "débito", "4821")
MASTER = Tarjeta(2, "Mastercard", "crédito", "1093")
AHORA = datetime(2026, 10, 3, 12, 0)


# ------------------------------------------------------------------ dominio

@pytest.mark.parametrize("consulta,esperadas", [
    ("", [1, 2]), ("mi tarjeta", [1, 2]), ("la he perdido", [1, 2]),
    ("4821", [1]), ("terminada en 1093", [2]), ("••4821", [1]), ("48 21", [1]),
    ("visa", [1]), ("la Mastercard", [2]), ("débito", [1]), ("la de CREDITO", [2]), ("tarjeta de crédito", [2]),
    ("visa de crédito", []), ("9999", []), ("amex", [1, 2]),  # una marca desconocida no discrimina
        ("mastercard visa", [1, 2]),
])
def test_buscar_tarjetas_por_digitos_marca_o_tipo(consulta, esperadas):
    assert [t.id for t in reglas.buscar_tarjetas([VISA, MASTER], consulta)] == esperadas


def test_con_una_sola_tarjeta_activa_mi_tarjeta_es_esa():
    activa = reglas.elegir_tarjeta([VISA, reglas.bloquear_tarjeta(MASTER, AHORA)], "mi tarjeta", para_bloquear=True)
    assert activa == VISA


def test_con_varias_candidatas_se_pregunta_en_vez_de_adivinar():
    with pytest.raises(TarjetaAmbigua) as e:
        reglas.elegir_tarjeta([VISA, MASTER], "mi tarjeta", para_bloquear=True)
    assert e.value.datos["tarjetas_disponibles"] == ["Visa débito ••4821", "Mastercard crédito ••1093"]
    assert reglas.elegir_tarjeta([VISA, MASTER], "la de débito", para_bloquear=True) == VISA


def test_bloquear_una_ya_bloqueada_es_un_aviso_claro_y_no_se_vuelve_a_bloquear():
    bloqueada = reglas.bloquear_tarjeta(VISA, AHORA)
    assert bloqueada.bloqueada and bloqueada.bloqueada_el == AHORA and bloqueada.estado == "bloqueada"
    with pytest.raises(TarjetaYaBloqueada, match="Visa débito ••4821 ya estaba bloqueada"):
        reglas.bloquear_tarjeta(bloqueada, AHORA)
    with pytest.raises(TarjetaYaBloqueada):
        reglas.elegir_tarjeta([bloqueada], "visa", para_bloquear=True)
    with pytest.raises(TarjetaYaActiva):
        reglas.desbloquear_tarjeta(VISA)
    assert reglas.desbloquear_tarjeta(bloqueada) == VISA


def test_sin_tarjetas_o_sin_coincidencia_no_se_encuentra():
    with pytest.raises(TarjetaNoEncontrada, match="ninguna tarjeta"):
        reglas.elegir_tarjeta([], "", para_bloquear=True)
    with pytest.raises(TarjetaNoEncontrada) as e:
        reglas.elegir_tarjeta([VISA], "9999", para_bloquear=True)
    assert e.value.datos["tarjetas_disponibles"] == ["Visa débito ••4821"]


@pytest.mark.parametrize("frase", [
    "he perdido la tarjeta", "perdí mi tarjeta", "me han robado la tarjeta", "creo que me han clonado la tarjeta",
    "ayuda, no encuentro mi tarjeta", "congela mi tarjeta por favor", "bloquea mi tarjeta", "bloquéala, es la tarjeta de crédito",
    "bloquea la tarjeta terminada en 4821", "me han robado la cartera, bloquéame la tarjeta de crédito",
    "he perdido la tarjeta. ¿Qué hago?", "bloquea la visa, he visto actividad rara", "quiero bloquear mi tarjeta",
    "me robaron la tarjeta", "perdí la tarjeta el 12 de octubre de 2026", "bloquea mi tarjeta, no la de crédito",
])
def test_ordenes_de_bloqueo_inequivocas(frase):
    assert pide_bloquear_tarjeta(frase)


@pytest.mark.parametrize("frase", [
    "¿cómo bloqueo mi tarjeta?", "¿está bloqueada mi tarjeta?", "mi tarjeta está bloqueada", "mi tarjeta está bloqueada, actívala",
    "desbloquea mi tarjeta", "quiero volver a usar mi tarjeta", "no quiero bloquear la tarjeta", "no he perdido la tarjeta",
    "¿qué tarjetas tengo?", "he perdido 5 euros", "bloquea mi cuenta", "haz un bizum de 5 a dani",
    # el servidor bloquea de verdad: ni preguntas sin signos, ni explicaciones, ni hipótesis, ni lo de otra persona
    "como puedo bloquear mi tarjeta", "¿cómo puedo bloquear mi tarjeta", "quiero saber cómo bloquear la tarjeta",
    "se puede bloquear la tarjeta desde la app", "explícame cómo bloquear una tarjeta", "no sé si bloquear la tarjeta",
    "perdí el tren pero tengo la tarjeta", "a mi madre le han robado la tarjeta", "perdí la tarjeta pero la encontré",
    "he perdido la cartera, la tarjeta no", "cuánto gasté con la tarjeta visa antes de bloquearla", "bloquear la tarjeta",
    "qué pasa si pierdo la tarjeta", "he perdido la cartera", "me han robado la cartera y el móvil", "si perdí la tarjeta, ¿qué hago?",
])
def test_lo_que_no_es_una_orden_de_bloqueo(frase):
    assert not pide_bloquear_tarjeta(frase)


# ------------------------------------------------------------------ casos de uso

class Escenario:
    def __init__(self):
        self.tarjetas = TarjetasEnMemoria()
        self.reloj = RelojFijo()
        self.auditoria = AuditoriaEnMemoria()
        self.operaciones = OperacionesEnMemoria()
        self.movil = MovilFalso()
        self.consultar = ConsultarTarjetas(self.tarjetas)
        cerrojos = CerrojosPorCliente()
        self.bloquear = BloquearTarjeta(self.tarjetas, self.reloj, self.auditoria, self.operaciones, cerrojos)
        self.solicitar = SolicitarDesbloqueoTarjeta(self.tarjetas, self.operaciones, CodigosFijos(), self.movil, self.reloj, self.auditoria)
        self.confirmar = ConfirmarOperacion(None, self.operaciones, self.reloj, self.auditoria, cerrojos, DesbloquearTarjeta(self.tarjetas, self.auditoria))
        self.cancelar = CancelarOperacion(self.operaciones, self.auditoria, cerrojos)

    def estado(self, cliente=ALEX) -> list[str]:
        return [t.estado for t in self.consultar(cliente)]


@pytest.fixture
def e():
    return Escenario()


def test_bloquear_no_pide_otp_y_queda_auditado(e):
    t = e.bloquear(ALEX, "débito")
    assert t.bloqueada and t.bloqueada_el == e.reloj.ahora()
    assert e.estado() == ["bloqueada", "activa"]
    assert e.movil.sms == {}  # sin código: bloquear es la dirección segura
    assert e.auditoria.acciones() == ["tarjeta_bloqueada"]


def test_bloquear_rechazos_tambien_se_auditan(e):
    with pytest.raises(TarjetaAmbigua):
        e.bloquear(ALEX, "")
    e.bloquear(ANA, "")
    with pytest.raises(TarjetaYaBloqueada):
        e.bloquear(ANA, "")
    assert e.auditoria.acciones() == ["tarjeta_bloqueo_rechazado", "tarjeta_bloqueada", "tarjeta_bloqueo_rechazado"]


def test_un_cliente_no_puede_tocar_las_tarjetas_de_otro(e):
    # Ana solo tiene la 7356: pedir la de Alex (4821) no la encuentra y la de Alex queda intacta
    with pytest.raises(TarjetaNoEncontrada):
        e.bloquear(ANA, "4821")
    assert e.estado(ALEX) == ["activa", "activa"] and e.estado(ANA) == ["activa"]
    # ni siquiera con el id interno de la tarjeta ajena
    with pytest.raises(TarjetaNoEncontrada):
        e.tarjetas.guardar_estado(ANA.id, reglas.bloquear_tarjeta(VISA, AHORA))
    with pytest.raises(TarjetaNoEncontrada):
        DesbloquearTarjeta(e.tarjetas, e.auditoria)(ANA, VISA.id)


def test_desbloquear_exige_el_codigo_y_hasta_entonces_sigue_bloqueada(e):
    e.bloquear(ANA, "")
    op = e.solicitar(ANA, "mi tarjeta")
    assert op.tipo is TipoOperacion.DESBLOQUEO_TARJETA and op.destinatario == "Visa débito ••7356" and op.importe == 0
    assert "123456" in e.movil.sms[ANA.id][0] and "Visa débito ••7356" in e.movil.sms[ANA.id][0]
    assert e.estado(ANA) == ["bloqueada"]
    with pytest.raises(CodigoIncorrecto):
        e.confirmar(ANA, op.id, "000000")
    assert e.estado(ANA) == ["bloqueada"]
    comprobante = e.confirmar(ANA, op.id, "123456")
    assert comprobante.tarjeta.estado == "activa" and e.estado(ANA) == ["activa"]
    assert e.auditoria.acciones() == ["tarjeta_bloqueada", "desbloqueo_solicitado", "otp_rechazado", "tarjeta_desbloqueada"]


def test_desbloquear_con_huella_y_cancelar(e):
    e.bloquear(ANA, "")
    op = e.solicitar(ANA, "")
    e.cancelar(ANA, op.id)
    assert e.estado(ANA) == ["bloqueada"] and e.auditoria.acciones()[-1] == "desbloqueo_cancelado"
    op2 = e.solicitar(ANA, "")
    assert e.confirmar.aprobar(ANA, op2.id).tarjeta.estado == "activa"


def test_nadie_confirma_el_desbloqueo_de_otro_cliente(e):
    e.bloquear(ANA, "")
    op = e.solicitar(ANA, "")
    with pytest.raises(OperacionNoEncontrada):
        e.confirmar(ALEX, op.id, "123456")
    assert e.estado(ANA) == ["bloqueada"]


def test_pedir_desbloquear_una_activa_no_crea_operacion_ni_sms(e):
    with pytest.raises(TarjetaYaActiva):
        e.solicitar(ANA, "")
    assert e.movil.sms == {} and e.auditoria.acciones() == ["desbloqueo_rechazado"]


def test_si_la_tarjeta_ya_esta_activa_al_confirmar_la_operacion_se_cancela(e):
    e.bloquear(ANA, "")
    op = e.solicitar(ANA, "")
    e.tarjetas.tarjetas[ANA.id][0] = reglas.desbloquear_tarjeta(e.tarjetas.tarjetas[ANA.id][0])  # desbloqueada por otro canal
    with pytest.raises(TarjetaYaActiva):
        e.confirmar(ANA, op.id, "123456")
    assert e.operaciones.obtener(op.id).estado is EstadoOperacion.CANCELADA


def test_bloquear_cancela_los_desbloqueos_pendientes_de_esa_tarjeta(e):
    e.bloquear(ANA, "")
    op = e.solicitar(ANA, "")
    with pytest.raises(TarjetaYaBloqueada):  # «me han robado también el móvil»: ya estaba bloqueada, pero el desbloqueo muere
        e.bloquear(ANA, "")
    assert e.operaciones.obtener(op.id).estado is EstadoOperacion.CANCELADA
    for confirmar in (lambda: e.confirmar(ANA, op.id, "123456"), lambda: e.confirmar.aprobar(ANA, op.id)):
        with pytest.raises(OperacionYaProcesada):
            confirmar()
    assert e.estado(ANA) == ["bloqueada"]
    assert e.auditoria.acciones() == [
        "tarjeta_bloqueada", "desbloqueo_solicitado", "desbloqueo_cancelado", "tarjeta_bloqueo_rechazado", "otp_rechazado", "aprobacion_rechazada"]


def test_bloquear_no_cancela_los_desbloqueos_de_otra_tarjeta_ni_de_otro_cliente(e):
    e.bloquear(ALEX, "visa")
    e.bloquear(ALEX, "mastercard")
    e.bloquear(ANA, "")
    op_visa, op_ana = e.solicitar(ALEX, "visa"), e.solicitar(ANA, "")
    e.tarjetas.tarjetas[ALEX.id][1] = reglas.desbloquear_tarjeta(e.tarjetas.tarjetas[ALEX.id][1])  # la Mastercard vuelve a estar activa
    e.bloquear(ALEX, "mastercard")  # solo cancela los desbloqueos de la Mastercard (no hay ninguno)
    assert e.operaciones.obtener(op_visa.id).estado is EstadoOperacion.PENDIENTE
    assert e.operaciones.obtener(op_ana.id).estado is EstadoOperacion.PENDIENTE


def test_bloquear_y_confirmar_un_desbloqueo_a_la_vez_dejan_la_tarjeta_bloqueada(e):
    """Sin cerrojo compartido, la confirmación (leída antes del bloqueo) reactivaba la tarjeta DESPUÉS de bloquearla."""
    import copy
    import threading

    class OperacionesConCarrera(type(e.operaciones)):
        """Devuelve copias (como SQLite) y retiene la lectura de la confirmación para que el bloqueo se cuele en medio."""

        def obtener(self, id_operacion):
            copia = copy.copy(super().obtener(id_operacion))
            threading.Event().wait(0.3)
            return copia

    e.bloquear(ANA, "")
    op = e.solicitar(ANA, "")
    e.operaciones.__class__ = OperacionesConCarrera
    resultados = []

    def lanzar(accion):
        try:
            accion()
            resultados.append("ok")
        except OperacionYaProcesada:
            resultados.append("ya_procesada")

    confirmar = threading.Thread(target=lanzar, args=(lambda: e.confirmar(ANA, op.id, "123456"),))
    confirmar.start()
    threading.Event().wait(0.1)  # la confirmación ya leyó la operación pendiente
    bloquear = threading.Thread(target=lanzar, args=(lambda: e.bloquear(ANA, ""),))
    bloquear.start()
    for h in (confirmar, bloquear):
        h.join(5)
    # el orden lo decide el cerrojo, pero el resultado final es siempre el mismo: bloqueada y sin desbloqueo vivo
    assert e.estado(ANA) == ["bloqueada"]
    assert e.operaciones._operaciones[op.id].estado is not EstadoOperacion.PENDIENTE


def test_el_update_de_la_tarjeta_es_condicional(bd):
    """Aunque dos peticiones se salten el cerrojo, la segunda transición al mismo estado no se aplica."""
    repo = RepositorioTarjetasSqlite(bd)
    bloqueada = reglas.bloquear_tarjeta(repo.listar(1)[0], AHORA)
    repo.guardar_estado(1, bloqueada)
    with pytest.raises(TarjetaYaBloqueada):
        repo.guardar_estado(1, bloqueada)
    with pytest.raises(TarjetaYaActiva):
        repo.guardar_estado(1, reglas.desbloquear_tarjeta(repo.listar(1)[1]))  # la 2.ª está activa: «desbloquear» no es una transición


def test_confirmar_un_desbloqueo_con_referencia_corrupta_es_un_error_de_dominio(e):
    e.bloquear(ANA, "")
    for referencia in ("", "abc", None):
        op = e.solicitar(ANA, "")
        op.referencia = referencia
        e.operaciones.guardar(op)
        with pytest.raises(TarjetaNoEncontrada):  # antes: ValueError → 500
            e.confirmar(ANA, op.id, "123456")
        assert e.operaciones.obtener(op.id).estado is EstadoOperacion.CANCELADA and e.estado(ANA) == ["bloqueada"]


# ------------------------------------------------------------------ herramientas

def montar_registro(e):
    return RegistroHerramientas(herramienta_tarjetas.crear(e.consultar, e.bloquear, e.solicitar))


def test_las_tres_herramientas_y_su_riesgo(e):
    r = montar_registro(e)
    assert [s.nombre for s in r.esquemas()] == ["consultar_tarjetas", "bloquear_tarjeta", "desbloquear_tarjeta"]
    assert (r.riesgo("consultar_tarjetas"), r.riesgo("bloquear_tarjeta"), r.riesgo("desbloquear_tarjeta")) == (
        Riesgo.LECTURA, Riesgo.PROTECCION, Riesgo.ESCRITURA)


def test_herramienta_bloquear_devuelve_el_texto_final_y_la_tarjeta_para_pintarla(e):
    res = montar_registro(e).ejecutar("bloquear_tarjeta", json.dumps({"tarjeta": "4821"}), ALEX)
    assert res.datos == {"ok": True, "estado": "bloqueada", "tarjeta": "Visa débito ••4821"}
    assert res.respuesta_final.startswith("Listo, he bloqueado tu tarjeta Visa débito ••4821")
    assert res.eventos == (TarjetaMostrada("Visa", "débito", "4821", "bloqueada", AHORA.isoformat()),)


def test_herramienta_bloquear_con_varias_pregunta_cual_y_no_bloquea(e):
    res = montar_registro(e).ejecutar("bloquear_tarjeta", "{}", ALEX)
    assert res.datos["ok"] is False and res.respuesta_final.startswith("¿Cuál quieres bloquear?")
    assert len(res.eventos) == 2 and e.estado() == ["activa", "activa"]


def test_herramienta_bloquear_ya_bloqueada_no_es_un_error(e):
    r = montar_registro(e)
    r.ejecutar("bloquear_tarjeta", "{}", ANA)
    res = r.ejecutar("bloquear_tarjeta", "{}", ANA)
    assert res.datos["ok"] is True and res.respuesta_final == "Tu tarjeta Visa débito ••7356 ya estaba bloqueada."


def test_herramienta_desbloquear_deja_la_operacion_pendiente_sin_dar_el_codigo(e):
    r = montar_registro(e)
    r.ejecutar("bloquear_tarjeta", "{}", ANA)
    res = r.ejecutar("desbloquear_tarjeta", "{}", ANA)
    assert res.datos["estado"] == "pendiente_de_confirmacion" and "123456" not in json.dumps(res.datos) + res.respuesta_final
    evento = res.eventos[0]
    assert isinstance(evento, OperacionPorConfirmar) and evento.tipo == "desbloqueo_tarjeta" and evento.destinatario == "Visa débito ••7356"
    assert e.estado(ANA) == ["bloqueada"]


def test_herramienta_consultar_lista_las_tarjetas_del_cliente(e):
    res = montar_registro(e).ejecutar("consultar_tarjetas", "{}", ANA)
    assert res.respuesta_final == "Estas son tus tarjetas: Visa débito ••7356 (activa)." and len(res.eventos) == 1


# ------------------------------------------------------------------ red de seguridad del agente (modelo pequeño)

def correr_agente(llm, pregunta):
    e = Escenario()
    agente = crear_agente(llm, montar_registro(e))
    mensajes = [Mensaje.sistema("s"), Mensaje.usuario(pregunta)]
    return list(agente.responder(mensajes, ANA)), mensajes, e


def test_si_el_modelo_dice_que_la_bloqueo_sin_llamar_a_la_herramienta_se_le_obliga():
    llm = LLMGuionizado(texto("Tarjeta bloqueada correctamente."), llamada("bloquear_tarjeta"))
    eventos, mensajes, e = correr_agente(llm, "me han robado la tarjeta")
    assert e.estado(ANA) == ["bloqueada"]
    assert any("bloquear_tarjeta" in (m.contenido or "") and (m.contenido or "").startswith("[auto]") for m in llm.llamadas[1][1])
    assert isinstance(eventos[-1], Fin) and eventos[-1].texto.startswith("Listo, he bloqueado")


def test_si_tras_el_empujon_sigue_sin_llamar_la_llama_el_servidor():
    llm = LLMGuionizado(texto("Tarjeta bloqueada."), texto("Ya está, tarjeta bloqueada."))
    eventos, mensajes, e = correr_agente(llm, "he perdido la tarjeta")
    assert e.estado(ANA) == ["bloqueada"] and e.auditoria.acciones() == ["tarjeta_bloqueada"]
    assert eventos[-1].texto.startswith("Listo, he bloqueado tu tarjeta Visa débito ••7356")  # el texto es el de la herramienta, no el del modelo
    assert any(isinstance(ev, TarjetaMostrada) for ev in eventos)


@pytest.mark.parametrize("pregunta", [
    "como puedo bloquear mi tarjeta", "¿cómo puedo bloquear mi tarjeta", "se puede bloquear la tarjeta desde la app",
    "a mi madre le han robado la tarjeta", "perdí la tarjeta pero la encontré", "no sé si bloquear la tarjeta",
])
def test_el_servidor_no_bloquea_si_no_es_una_orden_clara(pregunta):
    """Antes bastaba la palabra «bloquear» sin «?»: el servidor bloqueaba una tarjeta que nadie le había pedido bloquear."""
    llm = LLMGuionizado(texto("Puedes bloquearla desde la app o decírmelo aquí."))
    eventos, _, e = correr_agente(llm, pregunta)
    assert e.estado(ANA) == ["activa"] and e.auditoria.acciones() == []
    assert len(llm.llamadas) == 1 and eventos[-1].texto.startswith("Puedes bloquearla")  # ni empujón ni llamada del servidor


def test_orden_directa_se_ejecuta_solo_con_una_frase_explicita():
    orden = herramienta_tarjetas._orden_de_bloqueo
    assert orden("he perdido la tarjeta") == {} and orden("¿cómo bloqueo mi tarjeta?") is None
    assert orden("bloquea la visa terminada en 4821") == {"tarjeta": "visa 4821"}


@pytest.mark.parametrize("frase,esperado", [
    ("bloquea mi tarjeta, no la de crédito", {}),  # la negación no se convierte en «la de crédito»
    ("perdí la tarjeta el 12 de octubre de 2026", {}),  # un año no son los últimos 4 dígitos
    ("me han robado la tarjeta, me cobraron 1.250 euros", {}),
    ("bloquea la visa o la mastercard", {}),
    ("bloquea la tarjeta de crédito", {"tarjeta": "crédito"}),
    ("bloquéala, la mastercard acabada en 1093", {"tarjeta": "mastercard 1093"}),
])
def test_el_servidor_solo_pasa_los_datos_de_la_tarjeta_no_la_frase(frase, esperado):
    assert herramienta_tarjetas._orden_de_bloqueo(frase) == esperado


def test_con_negacion_el_servidor_pregunta_cual_y_no_repite_la_frase():
    llm = LLMGuionizado(texto("Hecho."), texto("Hecho."))
    e = Escenario()
    agente = crear_agente(llm, montar_registro(e))
    mensajes = [Mensaje.sistema("s"), Mensaje.usuario("bloquea mi tarjeta, no la de crédito")]
    eventos = list(agente.responder(mensajes, ALEX))  # Alex tiene dos: no se adivina
    assert e.estado(ALEX) == ["activa", "activa"] and eventos[-1].texto.startswith("¿Cuál quieres bloquear?")
    assert "no la de crédito" not in eventos[-1].texto


def test_un_numero_de_tarjeta_escrito_no_se_audita_ni_se_repite():
    e = Escenario()
    res = montar_registro(e).ejecutar("bloquear_tarjeta", json.dumps({"tarjeta": "4111 1111 1111 9999"}), ANA)
    assert "4111" not in res.respuesta_final and "9999" not in res.respuesta_final
    detalle = " ".join(f"{a}" for a in e.auditoria.eventos)
    assert "4111" not in detalle and "1111 9999" not in detalle and "[número oculto]" in detalle
    montar_registro(e).ejecutar("desbloquear_tarjeta", json.dumps({"tarjeta": "4111-1111-1111-9999"}), ANA)
    assert "4111" not in " ".join(f"{a}" for a in e.auditoria.eventos)


def test_un_modelo_no_encadena_bloqueos_de_todas_las_tarjetas_en_un_turno():
    dos = [
        LlamadaHerramienta("c1", "bloquear_tarjeta", json.dumps({"tarjeta": "visa"})),
        LlamadaHerramienta("c2", "bloquear_tarjeta", json.dumps({"tarjeta": "mastercard"})),
    ]
    e = Escenario()
    agente = crear_agente(LLMGuionizado([PeticionHerramientas(tuple(dos))]), montar_registro(e))
    mensajes = [Mensaje.sistema("s"), Mensaje.usuario("me han robado la cartera, bloquea mis tarjetas")]
    eventos = list(agente.responder(mensajes, ALEX))
    assert e.estado(ALEX) == ["bloqueada", "activa"] and e.auditoria.acciones() == ["tarjeta_bloqueada"]
    assert "Visa débito ••4821" in eventos[-1].texto and "una tarjeta por petición" in eventos[-1].texto
    resultado_rechazado = json.loads(next(m for m in mensajes if m.rol == "tool" and m.id_llamada == "c2").contenido)
    assert resultado_rechazado["ok"] is False


def test_el_servidor_solo_bloquea_si_la_ultima_pregunta_habla_de_tarjetas():
    """Un modelo engañado (p. ej. por texto de un movimiento) no bloquea nada si el cliente preguntaba por otra cosa."""
    llm = LLMGuionizado(llamada("bloquear_tarjeta", json.dumps({"tarjeta": "visa"})), texto("No he bloqueado nada."))
    eventos, mensajes, e = correr_agente(llm, "¿cuánto he gastado este mes?")
    assert e.estado(ANA) == ["activa"] and e.auditoria.acciones() == []
    assert eventos[-1].texto == RECHAZO_SIN_ORDEN_DE_BLOQUEO  # texto fijo del servidor, no el del modelo
    # y si la respuesta a «¿cuál quieres bloquear?» es «la de débito», sí vale
    llm = LLMGuionizado(llamada("bloquear_tarjeta", json.dumps({"tarjeta": "débito"})))
    anterior = [Mensaje.sistema("s"), Mensaje.usuario("bloquea mi tarjeta"), Mensaje.asistente("¿Cuál quieres bloquear? Tienes Visa débito ••7356."), Mensaje.usuario("la de débito")]
    e = Escenario()
    list(crear_agente(llm, montar_registro(e)).responder(anterior, ANA))
    assert e.estado(ANA) == ["bloqueada"]
    # pero «la de débito» sin que el asistente haya preguntado cuál no es una orden
    llm = LLMGuionizado(llamada("bloquear_tarjeta", json.dumps({"tarjeta": "débito"})), texto("ok"))
    _, _, e = correr_agente(llm, "la de débito")
    assert e.estado(ANA) == ["activa"]


def test_una_herramienta_con_orden_directa_exige_aviso_y_riesgo_seguro():
    def herramienta(**kw):
        return Herramienta(EsquemaHerramienta("x", "x", {"type": "object", "properties": {}}), lambda a, c: None, "…", **kw)
    orden = {"orden_directa": lambda p: {}}
    with pytest.raises(ValueError, match="aviso_orden"):
        RegistroHerramientas([herramienta(riesgo=Riesgo.PROTECCION, **orden)])
    with pytest.raises(ValueError, match="PROTECCION o crear una operación"):
        RegistroHerramientas([herramienta(riesgo=Riesgo.LECTURA, aviso_orden="[auto] haz x", **orden)])
    RegistroHerramientas([herramienta(riesgo=Riesgo.PROTECCION, aviso_orden="[auto] haz x", **orden)])
    RegistroHerramientas([herramienta(riesgo=Riesgo.ESCRITURA, aviso_orden="[auto] haz x", **orden)])


def test_el_servidor_nunca_desbloquea_ni_crea_operaciones_por_su_cuenta():
    llm = LLMGuionizado(texto("Tarjeta desbloqueada."))
    eventos, _, e = correr_agente(llm, "desbloquea mi tarjeta")
    assert e.operaciones._operaciones == {} and e.movil.sms == {}


# ------------------------------------------------------------------ chat: el resultado de la operación llega al modelo

def test_el_modelo_se_entera_de_si_el_desbloqueo_se_confirmo():
    e = Escenario()
    e.bloquear(ANA, "")
    op = e.solicitar(ANA, "")
    chat = ServicioChat(None, None, e.reloj, None, None, None, e.operaciones)
    chat._seguimiento["2:s"] = [op.id]
    assert chat._avisos_de_operaciones("2:s") == []  # sigue pendiente: aún no hay nada que contar
    e.confirmar(ANA, op.id, "123456")
    avisos = chat._avisos_de_operaciones("2:s")
    assert len(avisos) == 1 and "desbloqueo de la tarjeta Visa débito ••7356" in avisos[0].contenido and "YA está desbloqueada" in avisos[0].contenido


# ------------------------------------------------------------------ SQLite y migración

HASHEADOR = HasheadorScrypt()


@pytest.fixture
def bd(tmp_path):
    bd = BaseDeDatos(tmp_path / "banco.db")
    esquema.inicializar(bd, RelojFijo(), HASHEADOR)
    return bd


def tablas(bd):
    con = bd.abrir(solo_lectura=True)
    try:
        return {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        con.close()


def test_la_demo_siembra_las_tarjetas_de_cada_cliente_y_el_admin_no_tiene(bd):
    repo = RepositorioTarjetasSqlite(bd)
    assert [t.etiqueta for t in repo.listar(1)] == ["Visa débito ••4821", "Mastercard crédito ••1093"]
    assert [len(repo.listar(i)) for i in (1, 2, 3, 4)] == [2, 1, 2, 1]
    admin = RepositorioClientesSqlite(bd).buscar_por_usuario("admin")[0]
    assert repo.listar(admin.id) == []


def test_aislamiento_en_sqlite_y_el_sql_del_llm_no_ve_las_tarjetas(bd):
    repo = RepositorioTarjetasSqlite(bd)
    with pytest.raises(TarjetaNoEncontrada):  # la tarjeta 1 es de Alex (cliente 1)
        repo.guardar_estado(2, reglas.bloquear_tarjeta(repo.listar(1)[0], AHORA))
    assert not repo.listar(1)[0].bloqueada
    with pytest.raises(ConsultaNoPermitida):
        ConsultorMovimientosSqlite(bd).ejecutar_select(1, "SELECT * FROM tarjetas", 10)


def test_el_estado_de_la_tarjeta_se_guarda(bd):
    repo = RepositorioTarjetasSqlite(bd)
    repo.guardar_estado(1, reglas.bloquear_tarjeta(repo.listar(1)[0], AHORA))
    leida = RepositorioTarjetasSqlite(bd).listar(1)[0]
    assert leida.bloqueada and leida.bloqueada_el == AHORA


def _base_anterior_con_un_bizum(bd) -> int:
    """Deja la base como la tenía el usuario antes de esta función: sin tabla `tarjetas`, `operaciones_pendientes` sin
    las columnas nuevas y con un Bizum ya hecho desde el chat. Devuelve el nº de movimientos."""
    RepositorioCuentaSqlite(bd).registrar_movimiento(1, Movimiento(RelojFijo().hoy(), "Bizum", "Bizum enviado a María López — cena", "Bizum", -25.5))
    con = bd.abrir()
    con.executescript("""
        DROP TABLE tarjetas;
        DROP TABLE operaciones_pendientes;
        CREATE TABLE operaciones_pendientes (
            id TEXT PRIMARY KEY, cliente_id INTEGER NOT NULL, destinatario TEXT NOT NULL, telefono TEXT NOT NULL,
            importe REAL NOT NULL, concepto TEXT NOT NULL, huella TEXT NOT NULL, creada TEXT NOT NULL, caduca TEXT NOT NULL,
            alertas TEXT NOT NULL, intentos_restantes INTEGER NOT NULL, estado TEXT NOT NULL);
        INSERT INTO operaciones_pendientes VALUES ('vieja', 1, 'María López', '600111222', 25.5, 'cena', 'h',
            '2026-10-03T12:00:00', '2026-10-03T12:05:00', '[]', 3, 'confirmada');
    """)
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]
    con.close()
    return total


def test_la_migracion_es_aditiva_idempotente_y_no_regenera_la_base(bd):
    movimientos = _base_anterior_con_un_bizum(bd)
    assert "tarjetas" not in tablas(bd)
    for _ in range(2):  # dos arranques seguidos: el segundo no cambia nada
        esquema.inicializar(bd, RelojFijo(), HASHEADOR)
        repo = RepositorioTarjetasSqlite(bd)
        assert [len(repo.listar(i)) for i in (1, 2, 3, 4)] == [2, 1, 2, 1]
        con = bd.abrir(solo_lectura=True)
        assert con.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0] == movimientos  # el Bizum NO desaparece
        assert con.execute("SELECT COUNT(*) FROM movimientos WHERE concepto LIKE 'Bizum enviado a María López — cena'").fetchone()[0] == 1
        assert con.execute("PRAGMA user_version").fetchone()[0] == esquema.VERSION_ESQUEMA  # no se disparó la regeneración
        con.close()
    vieja = OperacionesSqlite(bd).obtener("vieja")  # la operación antigua sigue ahí, como Bizum
    assert vieja.tipo is TipoOperacion.BIZUM and vieja.referencia == "" and vieja.estado is EstadoOperacion.CONFIRMADA


def test_re_arrancar_no_vuelve_a_sembrar_ni_pisa_un_bloqueo(bd):
    repo = RepositorioTarjetasSqlite(bd)
    repo.guardar_estado(1, reglas.bloquear_tarjeta(repo.listar(1)[0], AHORA))
    esquema.inicializar(bd, RelojFijo(), HASHEADOR)
    assert len(repo.listar(1)) == 2 and repo.listar(1)[0].bloqueada


def test_la_operacion_de_desbloqueo_se_guarda_con_su_tipo_y_tarjeta(bd):
    e = Escenario()
    e.operaciones = OperacionesSqlite(bd)
    e.solicitar = SolicitarDesbloqueoTarjeta(e.tarjetas, e.operaciones, CodigosFijos(), e.movil, e.reloj, e.auditoria)
    e.bloquear(ANA, "")
    op = e.solicitar(ANA, "")
    leida = OperacionesSqlite(bd).obtener(op.id)
    assert leida == op and leida.tipo is TipoOperacion.DESBLOQUEO_TARJETA and leida.referencia == "3"


# ------------------------------------------------------------------ endurecimiento (ronda 3)

def test_pedir_una_marca_o_tipo_que_no_se_tiene_no_bloquea_otra_tarjeta():
    # ana solo tiene Visa débito: «Mastercard» o «crédito» no equivalen a «cualquiera»
    for consulta, esperado in [("mastercard", "Mastercard"), ("crédito", "crédito"), ("mastercard crédito", "Mastercard crédito")]:
        with pytest.raises(TarjetaNoEncontrada) as e:
            reglas.elegir_tarjeta([VISA], consulta, para_bloquear=True)
        assert e.value.mensaje == f"No encuentro una tarjeta {esperado} entre las tuyas."
    with pytest.raises(TarjetaNoEncontrada) as e:  # el texto libre no se repite
        reglas.elegir_tarjeta([VISA], "mastercard 4111111111111111", para_bloquear=True)
    assert "4111" not in e.value.mensaje


def test_quiero_bloquear_mi_mastercard_con_solo_una_visa_no_bloquea_nada():
    llm = LLMGuionizado(llamada("bloquear_tarjeta", json.dumps({"tarjeta": "mastercard"})))
    eventos, _, e = correr_agente(llm, "quiero bloquear mi tarjeta Mastercard")
    assert e.estado(ANA) == ["activa"] and "No encuentro una tarjeta Mastercard" in eventos[-1].texto


def test_el_modelo_que_llama_solo_ante_la_tarjeta_de_otra_persona_no_bloquea_nada():
    """Caso real: «a mi madre le han robado la tarjeta» hizo que qwen3:8b llamara solo a la herramienta."""
    llm = LLMGuionizado(llamada("bloquear_tarjeta"))
    eventos, _, e = correr_agente(llm, "a mi madre le han robado la tarjeta")
    assert e.estado(ANA) == ["activa"] and e.auditoria.acciones() == []
    assert isinstance(eventos[-1], Fin) and eventos[-1].texto == RECHAZO_SIN_ORDEN_DE_BLOQUEO


@pytest.mark.parametrize("frase", [
    "he perdido la tarjeta del gimnasio", "he perdido la tarjeta del metro", "he perdido la tarjeta de embarque",
    "he perdido la tarjeta sanitaria", "he perdido la tarjeta SIM", "he perdido la tarjeta regalo",
    "bloquea la tarjeta de mi hermano", "bloquea la tarjeta de mi madre", "mi hijo dice: bloquea mi tarjeta",
    "bloquea mi tarjeta cuando vuelva de viaje", "bloquea mi tarjeta mañana", "bloquea mi tarjeta luego",
    "bloquea mi tarjeta más tarde", "bloquea mi tarjeta, era una prueba", "he perdido mi tarjeta, no lo hagas",
    "bloquea mi tarjeta, era broma", "he perdido mi tarjeta, mentira", "bloquea mi tarjeta, mejor espera",
    "perdí mi tarjeta en 2019", 'bloquea «mi tarjeta»', "él dijo bloquea mi tarjeta",
])
def test_otras_tarjetas_otras_personas_aplazadas_rectificaciones_y_citas_no_son_orden(frase):
    assert not pide_bloquear_tarjeta(frase)


@pytest.mark.parametrize("frase", [
    "he perdido mi tarjeta", "me han robado la tarjeta", "bloquea la tarjeta terminada en 4821",
    "quiero bloquear mi tarjeta Mastercard", "he perdido la tarjeta. ¿Qué hago?", "bloquea la visa, he visto actividad rara",
    "bloquea mis tarjetas", "he perdido la tarjeta de crédito",
])
def test_las_ordenes_claras_siguen_valiendo(frase):
    assert pide_bloquear_tarjeta(frase)


def test_si_el_modelo_pregunta_una_aclaracion_el_servidor_no_la_anula():
    llm = LLMGuionizado(texto("¿Te refieres a la tarjeta del gimnasio?"), texto("¿Te refieres a la tarjeta del gimnasio?"))
    eventos, _, e = correr_agente(llm, "he perdido la tarjeta")
    assert e.estado(ANA) == ["activa"] and eventos[-1].texto == "¿Te refieres a la tarjeta del gimnasio?"


@pytest.mark.parametrize("frase,habla", [
    ("¿cuánto gasté en 2025?", False), ("bloque de gastos", False), ("mi crédito", False), ("la de débito", False),
    ("la 4821", False), ("mi tarjeta", True), ("la visa", True), ("bloquéala", True), ("•• 4821", True),
])
def test_habla_de_tarjetas_no_acepta_cifras_ni_palabras_sueltas(frase, habla):
    assert habla_de_tarjetas(frase) is habla


def test_los_datos_sueltos_solo_valen_tras_el_cual_quieres():
    assert habla_de_tarjetas("la de débito", tras_aclaracion=True) and habla_de_tarjetas("la 4821", tras_aclaracion=True)
    assert es_aclaracion_de_tarjeta("¿Cuál quieres bloquear? Tienes Visa débito ••4821.")
    assert not es_aclaracion_de_tarjeta("Listo, he bloqueado tu tarjeta.")


@pytest.mark.parametrize("numero", [
    "4111 1111 1111 1234", "4111.1111.1111.1234", "4111  1111  1111  1234", "4111\xa01111\xa01111\xa01234",
    "4111\u20091111\u20091111\u20091234", "4111\t1111\t1111\t1234", "4111/1111/1111/1234", "4111_1111_1111_1234",
    "4111 – 1111 – 1111 – 1234", "4111-1111-1111-1234", "4111111111111234",
])
def test_se_enmascaran_los_numeros_largos_con_cualquier_separador(numero):
    assert "1234" not in enmascarar_numeros_largos(f"mi tarjeta {numero} gracias")


def test_el_destinatario_de_un_bizum_rechazado_no_deja_un_numero_largo_en_la_auditoria():
    from tests.test_bizum_otp import Escenario as EscenarioBizum
    b = EscenarioBizum()
    with pytest.raises(Exception):
        b.solicitar(ALEX, "4111\xa01111\xa01111\xa01234", -5.0)
    detalle = b.auditoria.eventos[-1][2]
    assert b.auditoria.acciones() == ["bizum_rechazado"] and "1234" not in detalle


def test_el_texto_largo_no_dispara_el_coste_de_las_expresiones_regulares():
    import time
    for texto_largo in ["bloquea mi tarjeta " + "*" * 20000, "perdí mi tarjeta " + "a" * 20000, "¿" + "a " * 10000, "a" * 20000 + " tarjeta", "1 " * 10000]:
        t0 = time.perf_counter()
        pide_bloquear_tarjeta(texto_largo)
        datos_de_tarjeta(texto_largo)
        habla_de_tarjetas(texto_largo)
        es_aclaracion_de_tarjeta(texto_largo)
        enmascarar_numeros_largos(texto_largo)
        assert time.perf_counter() - t0 < 0.2
