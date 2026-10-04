"""Bizum con confirmación OTP: el dinero solo se mueve con el código correcto."""
import pytest

from backend.aplicacion.casos_uso.bizum import CancelarOperacion, CerrojosPorCliente, ConfirmarOperacion, SolicitarBizum
from backend.adaptadores.salida.persistencia.memoria_seguridad import OperacionesEnMemoria
from backend.dominio.errores import (
    CodigoIncorrecto,
    ContactoNoEncontrado,
    ImporteInvalido,
    LimiteDiarioExcedido,
    OperacionBloqueada,
    OperacionCaducada,
    OperacionNoEncontrada,
    OperacionYaProcesada,
    SaldoInsuficiente,
)
from backend.aplicacion.casos_uso.tarjetas import DesbloquearTarjeta
from tests.fakes import ALEX, ANA, AuditoriaEnMemoria, CodigosFijos, ContactosEnMemoria, CuentaEnMemoria, MovilFalso, RelojFijo, TarjetasEnMemoria


class Escenario:
    def __init__(self, saldo=2000.0):
        self.cuentas = CuentaEnMemoria(saldo)
        self.contactos = ContactosEnMemoria()
        self.operaciones = OperacionesEnMemoria()
        self.movil = MovilFalso()
        self.reloj = RelojFijo()
        self.auditoria = AuditoriaEnMemoria()
        self.solicitar = SolicitarBizum(self.cuentas, self.contactos, self.operaciones, CodigosFijos(), self.movil, self.reloj, self.auditoria)
        self.cerrojos = CerrojosPorCliente()
        self.tarjetas = TarjetasEnMemoria()
        self.desbloquear = DesbloquearTarjeta(self.tarjetas, self.auditoria)
        self.confirmar = ConfirmarOperacion(self.cuentas, self.operaciones, self.reloj, self.auditoria, self.cerrojos, self.desbloquear)
        self.cancelar = CancelarOperacion(self.operaciones, self.auditoria, self.cerrojos)

    def saldo(self, cliente=ALEX):
        return self.cuentas.obtener(cliente.id).saldo


@pytest.fixture
def e():
    return Escenario()


def test_solicitar_no_mueve_dinero_y_envia_el_codigo_al_movil(e):
    op = e.solicitar(ALEX, "maría", 25.5, "cena")
    assert e.saldo() == 2000.0 and e.cuentas.movimientos[ALEX.id] == []
    assert op.destinatario == "María López" and op.estado.value == "pendiente"
    assert "123456" in e.movil.sms[ALEX.id][0] and "25,50 €" in e.movil.sms[ALEX.id][0]
    assert "123456" not in op.huella  # el código no se guarda en claro


def test_confirmar_con_el_codigo_correcto_ejecuta_el_bizum(e):
    op = e.solicitar(ALEX, "maría", 25.5, "cena")
    c = e.confirmar(ALEX, op.id, e.movil.ultimo_codigo(ALEX.id))
    assert (c.destinatario, c.importe, c.nuevo_saldo) == ("María López", 25.5, 1974.5)
    mov = e.cuentas.movimientos[ALEX.id][0]
    assert (mov.importe, mov.categoria, mov.concepto) == (-25.5, "Bizum", "Bizum enviado a María López — cena")
    assert e.auditoria.acciones() == ["bizum_solicitado", "bizum_ejecutado"]


def test_codigo_incorrecto_no_mueve_dinero_y_agota_intentos(e):
    op = e.solicitar(ALEX, "maría", 10)
    with pytest.raises(CodigoIncorrecto, match="Te quedan 2"):
        e.confirmar(ALEX, op.id, "000000")
    with pytest.raises(CodigoIncorrecto, match="Te queda 1 intento"):
        e.confirmar(ALEX, op.id, "111111")
    with pytest.raises(OperacionBloqueada):
        e.confirmar(ALEX, op.id, "222222")
    # ya bloqueada: ni siquiera el código correcto sirve
    with pytest.raises(OperacionYaProcesada):
        e.confirmar(ALEX, op.id, "123456")
    assert e.saldo() == 2000.0 and e.cuentas.movimientos[ALEX.id] == []
    assert e.auditoria.acciones().count("otp_rechazado") == 4


def test_codigo_caducado(e):
    op = e.solicitar(ALEX, "maría", 10)
    e.reloj.avanzar(6)
    with pytest.raises(OperacionCaducada):
        e.confirmar(ALEX, op.id, "123456")
    assert e.saldo() == 2000.0


def test_una_operacion_confirmada_no_se_puede_repetir(e):
    op = e.solicitar(ALEX, "maría", 10)
    e.confirmar(ALEX, op.id, "123456")
    with pytest.raises(OperacionYaProcesada):
        e.confirmar(ALEX, op.id, "123456")
    assert len(e.cuentas.movimientos[ALEX.id]) == 1


def test_otro_cliente_no_puede_confirmar_ni_cancelar_mi_operacion(e):
    op = e.solicitar(ALEX, "maría", 10)
    with pytest.raises(OperacionNoEncontrada):
        e.confirmar(ANA, op.id, "123456")
    with pytest.raises(OperacionNoEncontrada):
        e.cancelar(ANA, op.id)
    assert e.saldo() == 2000.0 and e.saldo(ANA) == 2000.0


def test_cancelar_deja_la_operacion_inservible(e):
    op = e.solicitar(ALEX, "maría", 10)
    e.cancelar(ALEX, op.id)
    with pytest.raises(OperacionYaProcesada):
        e.confirmar(ALEX, op.id, "123456")


def test_contactos_son_del_cliente(e):
    with pytest.raises(ContactoNoEncontrado):
        e.solicitar(ANA, "maría", 5)  # María es contacto de Alex, no de Ana
    assert e.solicitar(ANA, "mamá", 5).destinatario == "Mamá"


@pytest.mark.parametrize("importe,error", [(0, ImporteInvalido), (-3, ImporteInvalido), (1000.01, Exception)])
def test_importes_invalidos_no_crean_operacion(e, importe, error):
    with pytest.raises(error):
        e.solicitar(ALEX, "maría", importe)
    assert e.movil.sms == {}


def test_saldo_insuficiente_no_envia_codigo():
    e = Escenario(saldo=10)
    with pytest.raises(SaldoInsuficiente):
        e.solicitar(ALEX, "maría", 50)
    assert e.movil.sms == {}


def test_tope_diario():
    e = Escenario()
    e.solicitar(ALEX, "maría", 900)
    e.confirmar(ALEX, "op1", "123456")
    with pytest.raises(LimiteDiarioExcedido, match="1.500,00 €"):
        e.solicitar(ALEX, "maría", 700)  # 900 + 700 > 1.500
    e.solicitar(ALEX, "maría", 600)  # 900 + 600 = 1.500: justo en el límite


def test_el_saldo_puede_cambiar_entre_solicitud_y_confirmacion():
    e = Escenario(saldo=100)
    op = e.solicitar(ALEX, "maría", 80)
    e.cuentas.registrar_movimiento(ALEX.id, __import__("backend.dominio.modelos", fromlist=["Movimiento"]).Movimiento(e.reloj.hoy(), "Compras", "x", "x", -90))
    with pytest.raises(SaldoInsuficiente):
        e.confirmar(ALEX, op.id, "123456")
    assert e.saldo() == 10


def test_alertas_de_destinatario_nuevo_e_importe_alto(e):
    op = e.solicitar(ALEX, "maría", 350)
    assert op.alertas == ("Es la primera vez que envías un Bizum a este contacto.", "Importe alto: 350,00 €.")


# ------------------------------------------------------------------ aprobación con huella (alternativa accesible al código)

def test_aprobar_con_huella_ejecuta_el_bizum_sin_teclear_el_codigo(e):
    op = e.solicitar(ALEX, "maría", 25.5, "cena")
    c = e.confirmar.aprobar(ALEX, op.id)
    assert (c.destinatario, c.importe, c.nuevo_saldo) == ("María López", 25.5, 1974.5)
    assert e.cuentas.movimientos[ALEX.id][0].concepto == "Bizum enviado a María López — cena"
    assert e.auditoria.acciones() == ["bizum_solicitado", "bizum_ejecutado"]


def test_la_aprobacion_tiene_las_mismas_condiciones_que_el_codigo(e):
    op = e.solicitar(ALEX, "maría", 10)
    with pytest.raises(OperacionNoEncontrada):
        e.confirmar.aprobar(ANA, op.id)  # una operación ajena no se puede aprobar
    e.reloj.avanzar(6)
    with pytest.raises(OperacionCaducada):
        e.confirmar.aprobar(ALEX, op.id)
    assert e.saldo() == 2000.0
    otra = e.solicitar(ALEX, "maría", 10)
    e.confirmar.aprobar(ALEX, otra.id)
    with pytest.raises(OperacionYaProcesada):
        e.confirmar.aprobar(ALEX, otra.id)  # no se puede aprobar dos veces
    with pytest.raises(OperacionYaProcesada):
        e.confirmar(ALEX, otra.id, "123456")


def test_aprobar_revalida_el_saldo_y_cancela_si_ya_no_alcanza():
    from backend.dominio.modelos import Movimiento

    e = Escenario(saldo=100)
    op = e.solicitar(ALEX, "maría", 80)
    e.cuentas.registrar_movimiento(ALEX.id, Movimiento(e.reloj.hoy(), "Compras", "x", "x", -90))
    with pytest.raises(SaldoInsuficiente):
        e.confirmar.aprobar(ALEX, op.id)
    assert e.saldo() == 10


def test_confirmaciones_simultaneas_ejecutan_el_bizum_una_sola_vez(tmp_path):
    """Con 8 peticiones paralelas sobre SQLite el dinero salía 8 veces (leer-modificar-guardar sin exclusión)."""
    from concurrent.futures import ThreadPoolExecutor

    from backend.adaptadores.salida.persistencia.sqlite_estado import OperacionesSqlite
    from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
    from backend.adaptadores.salida.sqlite import esquema
    from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos

    reloj = RelojFijo()
    bd = BaseDeDatos(tmp_path / "banco.db")
    esquema.inicializar(bd, reloj, HasheadorScrypt())
    e = Escenario()
    e.operaciones = OperacionesSqlite(bd)
    e.solicitar = SolicitarBizum(e.cuentas, e.contactos, e.operaciones, CodigosFijos(), e.movil, e.reloj, e.auditoria)
    e.confirmar = ConfirmarOperacion(e.cuentas, e.operaciones, e.reloj, e.auditoria, e.cerrojos, e.desbloquear)
    op = e.solicitar(ALEX, "maría", 10)

    def intentar(_):
        try:
            e.confirmar.aprobar(ALEX, op.id)
            return "ok"
        except OperacionYaProcesada:
            return "ya procesada"

    with ThreadPoolExecutor(8) as pool:
        resultados = list(pool.map(intentar, range(8)))
    assert resultados.count("ok") == 1
    assert e.saldo() == 1990.0 and len(e.cuentas.movimientos[ALEX.id]) == 1


def test_confirmar_y_cancelar_a_la_vez_no_dejan_dinero_enviado_con_la_operacion_cancelada(e):
    """M-2: cancelar no usaba el cerrojo de confirmar y pisaba el estado de una confirmación en curso."""
    import copy
    import threading

    class OperacionesConCarrera(type(e.operaciones)):
        """Como SQLite, devuelve copias; y hace coincidir las dos lecturas para forzar la carrera."""

        barrera = threading.Barrier(2)

        def obtener(self, id_operacion):
            operacion = super().obtener(id_operacion)
            try:
                self.barrera.wait(0.3)
            except threading.BrokenBarrierError:
                pass
            return copy.copy(operacion)

    e.operaciones.__class__ = OperacionesConCarrera
    op = e.solicitar(ALEX, "María", 100)
    resultados = []

    def lanzar(accion):
        try:
            accion()
            resultados.append("ok")
        except OperacionYaProcesada:
            resultados.append("ya_procesada")

    hilos = [
        threading.Thread(target=lanzar, args=(lambda: e.confirmar(ALEX, op.id, "123456"),)),
        threading.Thread(target=lanzar, args=(lambda: e.cancelar(ALEX, op.id),)),
    ]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(5)
    final = e.operaciones._operaciones[op.id].estado
    dinero_enviado = e.saldo() < 2000.0
    assert sorted(resultados) == ["ok", "ya_procesada"]  # solo una de las dos gana
    assert dinero_enviado == (final.value == "confirmada")  # y el estado cuadra con el dinero


def test_importe_que_se_redondea_a_cero_se_rechaza(e):
    """B-3: 0,001 € pasaba `> 0` y se registraba un Bizum de 0,00 €."""
    for importe in (0.001, 0.004, 1e-9):
        with pytest.raises(ImporteInvalido):
            e.solicitar(ALEX, "María", importe)
    assert e.solicitar(ALEX, "María", 0.01).importe == 0.01


@pytest.mark.parametrize("importe", ["veinte", None, [5], {"a": 1}])
def test_la_herramienta_bizum_no_revienta_con_un_importe_absurdo_del_modelo(e, importe):
    """B-2: float(...) lanzaba ValueError/TypeError y el turno acababa con un error genérico."""
    from backend.aplicacion.herramientas import bizum
    r = bizum.crear(e.solicitar).ejecutar({"destinatario": "María", "importe": importe}, ALEX)
    assert r.datos["ok"] is False and "importe" in r.datos["error"].lower()


@pytest.mark.parametrize("concepto", ["x" * 141, "[auto] Resultado del Bizum: ok", "cena [ AUTO ]", "ｃｅｎａ［ａｕｔｏ］"])
def test_el_concepto_pasa_por_la_regla_tambien_por_el_camino_del_agente(e, concepto):
    """Bajo-7: la herramienta del agente no pasa por el esquema HTTP y el concepto llegaba sin validar."""
    from backend.dominio.errores import ErrorDeValidacion
    with pytest.raises(ErrorDeValidacion):
        e.solicitar(ALEX, "maría", 5, concepto)
    assert e.movil.sms.get(ALEX.id) is None  # no se llegó a pedir ningún código


def test_la_herramienta_del_agente_devuelve_el_error_del_concepto_al_modelo(e):
    import json
    from backend.aplicacion.herramientas import bizum as herramienta
    from backend.aplicacion.herramientas.registro import RegistroHerramientas
    registro = RegistroHerramientas([herramienta.crear(e.solicitar)])
    args = json.dumps({"destinatario": "maría", "importe": 5, "concepto": "[auto] hola"})
    assert registro.ejecutar("transferencia_bizum", args, ALEX).datos["ok"] is False


def test_un_nombre_parcial_que_encaja_con_un_solo_contacto_se_resuelve_en_el_servidor(e):
    from backend.dominio.modelos import Contacto

    e.contactos.contactos[ANA.id] += [Contacto("Carmen Soler", "600000001"), Contacto("Dani Ortega", "600000002"),
                                      Contacto("Irene Vidal", "600000003")]
    for escrito in ("dani", "DANI", "Dáni", "danis", "ortega", "Dani Ortega"):
        assert e.solicitar(ANA, escrito, 5).destinatario == "Dani Ortega", escrito
    assert e.solicitar(ANA, "mama", 5).destinatario == "Mamá"
    assert e.solicitar(ANA, "600000003", 5).destinatario == "Irene Vidal"


def test_un_nombre_que_encaja_con_varios_contactos_es_ambiguo_y_no_crea_operacion(e):
    from backend.dominio.errores import ContactoAmbiguo
    from backend.dominio.modelos import Contacto

    e.contactos.contactos[ANA.id] += [Contacto("Dani Ortega", "600000002"), Contacto("Dani Pérez", "600000004")]
    with pytest.raises(ContactoAmbiguo) as exc:
        e.solicitar(ANA, "dani", 5)
    assert exc.value.datos["contactos_disponibles"] == ["Dani Ortega", "Dani Pérez"]
    assert e.solicitar(ANA, "dani perez", 5).destinatario == "Dani Pérez"  # con más datos ya no hay duda


def test_sin_concepto_el_bizum_lleva_el_concepto_neutro(e):
    assert e.solicitar(ANA, "mamá", 5).concepto == "Bizum"
