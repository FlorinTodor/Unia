import pytest

from backend.aplicacion.casos_uso.banco import ConsultarMovimientos, EnviarBizum
from backend.dominio.errores import ConsultaNoPermitida, ContactoNoEncontrado, ImporteInvalido, SaldoInsuficiente
from tests.fakes import CuentaEnMemoria, ConsultorFalso, ContactosEnMemoria, RelojFijo


def crear(saldo=500.0):
    cuentas = CuentaEnMemoria(saldo)
    return cuentas, EnviarBizum(cuentas, ContactosEnMemoria(), RelojFijo())


def test_bizum_registra_movimiento_y_actualiza_saldo():
    cuentas, bizum = crear()
    c = bizum("maría", 25.5, "cena")
    assert (c.destinatario, c.importe, c.nuevo_saldo) == ("María López", 25.5, 474.5)
    mov = cuentas.movimientos[0]
    assert (mov.importe, mov.categoria, mov.fecha.isoformat()) == (-25.5, "Bizum", "2026-10-03")
    assert mov.concepto == "Bizum enviado a María López — cena"


def test_bizum_contacto_inexistente_lista_alternativas():
    cuentas, bizum = crear()
    with pytest.raises(ContactoNoEncontrado) as e:
        bizum("Fulano", 5)
    assert e.value.datos["contactos_disponibles"] == ["María López", "Pablo Ruiz"]
    assert cuentas.movimientos == []


def test_bizum_saldo_insuficiente_no_mueve_dinero():
    cuentas, bizum = crear(saldo=10)
    with pytest.raises(SaldoInsuficiente):
        bizum("María", 50)
    assert cuentas.movimientos == [] and cuentas.cuenta.saldo == 10


def test_bizum_importe_invalido_se_rechaza_antes_de_buscar_contacto():
    _, bizum = crear()
    with pytest.raises(ImporteInvalido):
        bizum("Fulano", -1)


def test_consulta_valida_antes_de_llegar_al_consultor():
    consultor = ConsultorFalso()
    consultar = ConsultarMovimientos(consultor)
    with pytest.raises(ConsultaNoPermitida):
        consultar("DROP TABLE cuenta")
    assert consultor.consultas == []
    consultar("SELECT 1;")
    assert consultor.consultas == [("SELECT 1", 60)]
