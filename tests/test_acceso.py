"""Login, bloqueo temporal, sesiones y hashing de contraseñas."""
import pytest

from backend.aplicacion.casos_uso.acceso import MENSAJE_CREDENCIALES, CerrarSesion, IdentificarCliente, IniciarSesion
from backend.adaptadores.salida.persistencia.memoria_seguridad import IntentosEnMemoria
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.adaptadores.salida.seguridad.sesiones_auth import SesionesAutenticadasEnMemoria
from backend.dominio.errores import CredencialesInvalidas, CuentaBloqueada, NoAutenticado
from tests.fakes import ALEX, ANA, AuditoriaEnMemoria, RelojFijo

HASHEADOR = HasheadorScrypt()  # scrypt es lento a propósito: se crea una sola vez


class ClientesFalsos:
    def __init__(self):
        self.hash_alex = HASHEADOR.hashear("alex2026")

    def buscar_por_usuario(self, usuario):
        return (ALEX, self.hash_alex) if usuario == "alex" else None

    def obtener(self, cliente_id):
        return {ALEX.id: ALEX, ANA.id: ANA}.get(cliente_id)


@pytest.fixture
def acceso():
    reloj, auditoria = RelojFijo(), AuditoriaEnMemoria()
    clientes, sesiones = ClientesFalsos(), SesionesAutenticadasEnMemoria(reloj)
    iniciar = IniciarSesion(clientes, HASHEADOR, sesiones, IntentosEnMemoria(), reloj, auditoria)
    return iniciar, IdentificarCliente(sesiones, clientes), CerrarSesion(sesiones, auditoria), reloj, auditoria


def test_login_correcto_crea_sesion_y_se_identifica_al_cliente(acceso):
    iniciar, identificar, *_ = acceso
    token, cliente = iniciar(" Alex ", "alex2026")  # el usuario se normaliza
    assert cliente == ALEX and identificar(token) == ALEX


def test_misma_respuesta_para_usuario_inexistente_y_contrasena_erronea(acceso):
    iniciar, *_ = acceso
    with pytest.raises(CredencialesInvalidas) as a:
        iniciar("alex", "mala")
    with pytest.raises(CredencialesInvalidas) as b:
        iniciar("nadie", "mala")
    assert a.value.mensaje == b.value.mensaje == MENSAJE_CREDENCIALES


def test_bloqueo_tras_cinco_fallos_y_desbloqueo_con_el_tiempo(acceso):
    iniciar, _, _, reloj, auditoria = acceso
    for _ in range(4):
        with pytest.raises(CredencialesInvalidas):
            iniciar("alex", "mala")
    with pytest.raises(CuentaBloqueada, match="5 min"):
        iniciar("alex", "mala")  # el 5.º fallo bloquea
    with pytest.raises(CuentaBloqueada):
        iniciar("alex", "alex2026")  # bloqueada: ni la contraseña correcta sirve
    reloj.avanzar(6)
    assert iniciar("alex", "alex2026")[1] == ALEX
    assert "login_bloqueado" in auditoria.acciones()


def test_un_login_correcto_reinicia_el_contador_de_fallos(acceso):
    iniciar, *_ = acceso
    for _ in range(4):
        with pytest.raises(CredencialesInvalidas):
            iniciar("alex", "mala")
    iniciar("alex", "alex2026")
    for _ in range(4):  # otros 4 fallos no bloquean: el contador volvió a cero
        with pytest.raises(CredencialesInvalidas):
            iniciar("alex", "mala")


def test_sin_token_o_con_token_falso_no_hay_identidad(acceso):
    _, identificar, *_ = acceso
    for token in (None, "", "token-inventado"):
        with pytest.raises(NoAutenticado):
            identificar(token)


def test_logout_invalida_la_sesion(acceso):
    iniciar, identificar, cerrar, *_ = acceso
    token, cliente = iniciar("alex", "alex2026")
    cerrar(token, cliente)
    with pytest.raises(NoAutenticado):
        identificar(token)


def test_la_sesion_caduca(acceso):
    iniciar, identificar, _, reloj, _ = acceso
    token, _ = iniciar("alex", "alex2026")
    reloj.avanzar(8 * 60 + 1)
    with pytest.raises(NoAutenticado):
        identificar(token)


def test_hash_con_sal_aleatoria_y_verificacion():
    h1, h2 = HASHEADOR.hashear("clave"), HASHEADOR.hashear("clave")
    assert h1 != h2 and h1.startswith("scrypt$")  # misma contraseña, distinto hash (sal)
    assert "clave" not in h1
    assert HASHEADOR.verificar("clave", h1) and not HASHEADOR.verificar("otra", h1)
    assert not HASHEADOR.verificar("clave", "basura")  # un hash corrupto no rompe nada
