"""Bizum con confirmación OTP: el dinero solo se mueve con el código correcto."""
import pytest

from backend.aplicacion.casos_uso.bizum import CancelarOperacion, ConfirmarOperacion, SolicitarBizum
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
from tests.fakes import ALEX, ANA, AuditoriaEnMemoria, CodigosFijos, ContactosEnMemoria, CuentaEnMemoria, MovilFalso, RelojFijo


class Escenario:
    def __init__(self, saldo=2000.0):
        self.cuentas = CuentaEnMemoria(saldo)
        self.contactos = ContactosEnMemoria()
        self.operaciones = OperacionesEnMemoria()
        self.movil = MovilFalso()
        self.reloj = RelojFijo()
        self.auditoria = AuditoriaEnMemoria()
        self.solicitar = SolicitarBizum(self.cuentas, self.contactos, self.operaciones, CodigosFijos(), self.movil, self.reloj, self.auditoria)
        self.confirmar = ConfirmarOperacion(self.cuentas, self.operaciones, self.reloj, self.auditoria)
        self.cancelar = CancelarOperacion(self.operaciones, self.auditoria)

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
