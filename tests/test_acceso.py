"""Login, bloqueo temporal, sesiones y hashing de contraseñas."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from backend.aplicacion.casos_uso.acceso import MENSAJE_CREDENCIALES, CerrarSesion, IdentificarCliente, IniciarSesion
from backend.adaptadores.salida.persistencia.memoria_seguridad import IntentosEnMemoria
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.adaptadores.salida.seguridad.sesiones_auth import SesionesAutenticadasEnMemoria
from backend.dominio.acceso import MAX_FALLOS, MAX_FALLOS_IP, EstadoIntentos, clave_usuario
from backend.dominio.errores import CredencialesInvalidas, CuentaBloqueada, NoAutenticado
from tests.fakes import CONTRASENA_ALEX, ALEX, ANA, AuditoriaEnMemoria, RelojFijo

HASHEADOR = HasheadorScrypt()  # scrypt es lento a propósito: se crea una sola vez


class ClientesFalsos:
    def __init__(self):
        self.hash_alex = HASHEADOR.hashear(CONTRASENA_ALEX)

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
    token, cliente = iniciar(" Alex ", CONTRASENA_ALEX)  # el usuario se normaliza
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
        iniciar("alex", CONTRASENA_ALEX)  # bloqueada: ni la contraseña correcta sirve
    reloj.avanzar(6)
    assert iniciar("alex", CONTRASENA_ALEX)[1] == ALEX
    assert "login_bloqueado" in auditoria.acciones()


def test_un_login_correcto_reinicia_el_contador_de_fallos(acceso):
    iniciar, *_ = acceso
    for _ in range(4):
        with pytest.raises(CredencialesInvalidas):
            iniciar("alex", "mala")
    iniciar("alex", CONTRASENA_ALEX)
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
    token, cliente = iniciar("alex", CONTRASENA_ALEX)
    cerrar(token, cliente)
    with pytest.raises(NoAutenticado):
        identificar(token)


def test_la_sesion_caduca(acceso):
    iniciar, identificar, _, reloj, _ = acceso
    token, _ = iniciar("alex", CONTRASENA_ALEX)
    reloj.avanzar(8 * 60 + 1)
    with pytest.raises(NoAutenticado):
        identificar(token)


def test_hash_con_sal_aleatoria_y_verificacion():
    h1, h2 = HASHEADOR.hashear("clave"), HASHEADOR.hashear("clave")
    assert h1 != h2 and h1.startswith("scrypt$")  # misma contraseña, distinto hash (sal)
    assert "clave" not in h1
    assert HASHEADOR.verificar("clave", h1) and not HASHEADOR.verificar("otra", h1)
    assert not HASHEADOR.verificar("clave", "basura")  # un hash corrupto no rompe nada


def test_los_intentos_con_usuarios_inventados_no_crecen_sin_tope():
    """M-3: cada usuario inexistente dejaba una entrada para siempre en memoria."""
    ahora = datetime(2026, 10, 3, 12, 0)
    intentos = IntentosEnMemoria(maximo=50)
    for i in range(5_000):
        intentos.reservar({f"x:inventado{i}": MAX_FALLOS}, ahora)
    assert len(intentos) <= 50
    intentos.reservar({"u:alex": 1}, ahora)  # un solo fallo ya bloquea
    bloqueado = intentos.obtener("u:alex")
    assert bloqueado.bloqueado(ahora)
    for i in range(5_000):
        intentos.reservar({f"u:otro{i}": MAX_FALLOS}, ahora)
    assert intentos.obtener("u:alex") == bloqueado  # un bloqueo activo no se expulsa por inundación de contadores


def test_un_mismo_origen_probando_muchos_usuarios_queda_bloqueado(acceso):
    """B-6: el bloqueo era solo por usuario; rotando usuarios se podía probar contraseñas sin límite."""
    iniciar, _, _, reloj, _ = acceso
    for i in range(MAX_FALLOS_IP - 1):
        with pytest.raises(CredencialesInvalidas):
            iniciar(f"usuario{i}", "mala", "10.0.0.9")
    with pytest.raises(CuentaBloqueada):
        iniciar("usuario_final", "mala", "10.0.0.9")  # el último fallo desde ese origen bloquea
    with pytest.raises(CuentaBloqueada):
        iniciar("alex", CONTRASENA_ALEX, "10.0.0.9")  # ni con credenciales buenas desde ese origen
    assert iniciar("alex", CONTRASENA_ALEX, "10.0.0.10")[1] == ALEX  # otro origen no se ve afectado
    reloj.avanzar(6)
    assert iniciar("alex", CONTRASENA_ALEX, "10.0.0.9")[1] == ALEX


def test_un_acierto_no_reinicia_el_limite_del_origen(acceso):
    """Login-4: con una cuenta propia se podía reiniciar el contador de la IP tras cada acierto."""
    iniciar, _, _, reloj, _ = acceso
    for i in range(MAX_FALLOS_IP - 1):
        with pytest.raises(CredencialesInvalidas):
            iniciar(f"usuario{i}", "mala", "10.0.0.7")
    assert iniciar("alex", CONTRASENA_ALEX, "10.0.0.7")[1] == ALEX
    with pytest.raises(CuentaBloqueada):
        iniciar("otro", "mala", "10.0.0.7")
    reloj.avanzar(6)
    iniciar("alex", CONTRASENA_ALEX, "10.0.0.7")


def test_los_fallos_sueltos_del_origen_caducan_por_ventana(acceso):
    iniciar, _, _, reloj, _ = acceso
    for i in range(MAX_FALLOS_IP - 1):
        with pytest.raises(CredencialesInvalidas):
            iniciar(f"usuario{i}", "mala", "10.0.0.8")
    reloj.avanzar(20)
    with pytest.raises(CredencialesInvalidas):  # la ventana venció: vuelve a contar desde cero
        iniciar("otro", "mala", "10.0.0.8")


def test_un_usuario_con_nombre_de_ip_no_bloquea_esa_ip(acceso):
    """Login-3: usuarios e IP compartían diccionario con la clave `ip:...`."""
    iniciar, *_ = acceso
    for _ in range(5):
        with pytest.raises((CredencialesInvalidas, CuentaBloqueada)):
            iniciar("ip:10.0.0.5", "mala")
    assert iniciar("alex", CONTRASENA_ALEX, "10.0.0.5")[1] == ALEX


class HasheadorContador:
    """Cuenta cuántas contraseñas llegan a verificarse (y tarda un poco, como scrypt, para dar pie a la carrera)."""

    def __init__(self):
        self.verificaciones = 0
        self._cerrojo = threading.Lock()

    def verificar(self, contrasena, hash_guardado):
        with self._cerrojo:
            self.verificaciones += 1
        time.sleep(0.01)
        return False

    def gastar_tiempo(self, contrasena):
        self.verificar(contrasena, "")


def _iniciar_con_contador():
    reloj, auditoria = RelojFijo(), AuditoriaEnMemoria()
    clientes, sesiones, hasheador = ClientesFalsos(), SesionesAutenticadasEnMemoria(reloj), HasheadorContador()
    return IniciarSesion(clientes, hasheador, sesiones, IntentosEnMemoria(), reloj, auditoria), hasheador


def _intentar(iniciar, usuario, origen):
    try:
        iniciar(usuario, "mala", origen)
    except (CredencialesInvalidas, CuentaBloqueada):
        pass


def test_intentos_en_paralelo_no_superan_el_limite_por_usuario():
    """Alto-1: el contador se leía antes de scrypt y se guardaba después; 40 intentos a la vez pasaban todos."""
    for _ in range(6):
        iniciar, hasheador = _iniciar_con_contador()
        with ThreadPoolExecutor(max_workers=40) as pool:
            list(pool.map(lambda _: _intentar(iniciar, "alex", "10.0.0.1"), range(40)))
        assert hasheador.verificaciones <= MAX_FALLOS


def test_intentos_en_paralelo_no_superan_el_limite_por_origen():
    from backend.dominio import acceso as dominio_acceso
    iniciar, hasheador = _iniciar_con_contador()
    with ThreadPoolExecutor(max_workers=40) as pool:  # cada intento con un usuario distinto: solo frena el origen
        list(pool.map(lambda i: _intentar(iniciar, f"u{i}", "10.0.0.2"), range(40 * 6)))
    assert hasheador.verificaciones <= dominio_acceso.MAX_FALLOS_IP


def test_el_bloqueo_por_origen_conserva_la_ventana():
    """Medio-5: al bloquear se reiniciaba el contador y el tope real era ~100 por bloqueo (5 min), no por ventana (15)."""
    ahora = datetime(2026, 10, 3, 12, 0)
    estado = EstadoIntentos()
    for _ in range(MAX_FALLOS_IP):
        estado = estado.tras_fallo(ahora, MAX_FALLOS_IP, conservar_ventana=True)
    assert estado.bloqueado(ahora)
    tras_bloqueo = ahora + timedelta(minutes=6)  # el bloqueo (5 min) ha caducado, la ventana (15) no
    assert not estado.bloqueado(tras_bloqueo)
    assert estado.tras_fallo(tras_bloqueo, MAX_FALLOS_IP, conservar_ventana=True).bloqueado(tras_bloqueo)  # un fallo más y otra vez
    despues = ahora + timedelta(minutes=16)  # pasada la ventana empieza de cero
    assert not estado.tras_fallo(despues, MAX_FALLOS_IP, conservar_ventana=True).bloqueado(despues)


def test_un_usuario_se_bloquea_con_cinco_fallos_aunque_el_origen_este_limpio():
    """Compromiso aceptado (DECISIONES nº 18): cualquiera puede bloquear 5 min a un usuario concreto a propósito."""
    iniciar, hasheador = _iniciar_con_contador()
    for i in range(MAX_FALLOS):
        _intentar(iniciar, "alex", f"10.0.1.{i}")  # orígenes distintos
    with pytest.raises(CuentaBloqueada):
        iniciar("alex", CONTRASENA_ALEX, "10.0.1.99")


def test_inundar_usuarios_inventados_no_expulsa_el_contador_de_una_cuenta_real(acceso):
    """Bajo-6: el cupo era común y 10.000 usuarios inventados expulsaban los fallos de `alex`."""
    iniciar, *_ = acceso
    intentos = IntentosEnMemoria(maximo=20)
    reloj, auditoria = RelojFijo(), AuditoriaEnMemoria()
    clientes = ClientesFalsos()
    iniciar = IniciarSesion(clientes, HASHEADOR, SesionesAutenticadasEnMemoria(reloj), intentos, reloj, auditoria)
    with pytest.raises(CredencialesInvalidas):
        iniciar("alex", "mala")
    for i in range(200):
        with pytest.raises(CredencialesInvalidas):
            iniciar(f"inventado{i}", "mala")
    assert intentos.obtener(clave_usuario("alex")).fallos == 1
    assert len(intentos) <= 21
