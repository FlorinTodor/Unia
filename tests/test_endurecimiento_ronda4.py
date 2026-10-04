"""Cuarta ronda de endurecimiento (4-oct): origen no falsificable, cookie, cupo O(1), marca [auto], gráficos (incidencias 80-88)."""
import json
from datetime import datetime

import pytest
from starlette.requests import Request

from backend.adaptadores.entrada.http.app import _token_de_la_cookie
from backend.adaptadores.entrada.http.rutas_auth import ORIGEN_NO_FIABLE, origen_de
from backend.adaptadores.salida.persistencia.memoria_seguridad import IntentosEnMemoria
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from backend.adaptadores.salida.seguridad.sesiones_auth import SesionesAutenticadasEnMemoria
from backend.aplicacion.agente import pide_un_grafico
from backend.aplicacion.casos_uso.acceso import IniciarSesion
from backend.aplicacion.eventos import Aviso
from backend.aplicacion.herramientas import grafico
from backend.dominio.acceso import MAX_FALLOS, MAX_FALLOS_IP
from backend.dominio.errores import CredencialesInvalidas, CuentaBloqueada, ErrorDeValidacion
from backend.dominio.reglas import validar_concepto
from backend.dominio.uso import PresupuestoUso, quitar_invisibles, validar_mensaje
from tests.fakes import ALEX, ANA, CONTRASENA_ALEX, AuditoriaEnMemoria, LLMGuionizado, RelojFijo, llamada, texto
from tests.test_agente import correr, crear


def _peticion(cabeceras: dict[str, str], cliente=("10.0.0.7", 5000)) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/auth/login", "query_string": b"", "client": cliente,
        "headers": [(k.lower().encode(), v.encode()) for k, v in cabeceras.items()],
    })


# ------------------------------------------------------------------ 80: X-Forwarded-For no cambia el origen

def test_x_forwarded_for_no_cambia_el_origen_sin_proxy_de_confianza():
    """Uvicorn reescribe `client` con esa cabecera desde 127.0.0.1: sin PROXY_DE_CONFIANZA todas comparten un contador."""
    a = origen_de(_peticion({"X-Forwarded-For": "1.1.1.1"}))
    b = origen_de(_peticion({"X-Forwarded-For": "2.2.2.2"}, cliente=("3.3.3.3", 1)))
    c = origen_de(_peticion({"X-Real-IP": "4.4.4.4"}))
    assert a == b == c == ORIGEN_NO_FIABLE
    assert origen_de(_peticion({})) == "10.0.0.7"  # sin cabeceras de proxy, el origen es el de la conexión


def test_con_proxy_de_confianza_se_usa_el_origen_que_ve_uvicorn():
    assert origen_de(_peticion({"X-Forwarded-For": "1.1.1.1"}, cliente=("1.1.1.1", 0)), proxy_de_confianza=True) == "1.1.1.1"


# ------------------------------------------------------------------ 81: la cookie se lee como Starlette

def test_el_middleware_de_stt_lee_la_misma_cookie_que_starlette():
    assert _token_de_la_cookie(b"sesion=malo; sesion=bueno") == "bueno"  # gana la última, como en las rutas
    assert _token_de_la_cookie(b'sesion="entre-comillas"') == "entre-comillas"
    assert _token_de_la_cookie(b"xsesion=1") is None and _token_de_la_cookie(b"") is None


# ------------------------------------------------------------------ 82: cupo O(1) con OrderedDict

def test_al_llenarse_el_cupo_se_expulsa_el_mas_antiguo_y_se_conservan_los_bloqueos():
    ahora = datetime(2026, 10, 3, 12, 0)
    intentos = IntentosEnMemoria(maximo=3)
    for i in range(6):
        intentos.reservar({f"x:n{i}": MAX_FALLOS}, ahora)
    assert [intentos.obtener(f"x:n{i}").fallos for i in range(6)] == [0, 0, 0, 1, 1, 1]  # quedan los 3 más recientes
    intentos.reservar({"x:malo": 1}, ahora)  # un solo fallo bloquea
    intentos.reservar({"x:otro": MAX_FALLOS}, ahora)
    intentos.reservar({"x:otro2": MAX_FALLOS}, ahora)
    assert intentos.obtener("x:malo").bloqueado(ahora) and len(intentos) == 3


# ------------------------------------------------------------------ 83-84: marca [auto] y ZWJ

def test_los_emoji_compuestos_conservan_el_zwj_en_el_mensaje():
    familia = "👨‍👩‍👧"
    assert quitar_invisibles(f"hola {familia}") == f"hola {familia}"
    assert validar_mensaje(f" {familia} ", PresupuestoUso()) == familia
    assert quitar_invisibles("a­b​c") == "abc"  # el resto de invisibles sí se quita


def test_la_marca_se_detecta_aunque_se_esconda_con_zwj():
    with pytest.raises(ErrorDeValidacion):
        validar_mensaje("[a‍u‍to]", PresupuestoUso())


# ------------------------------------------------------------------ 85: caracteres de control en el concepto

def test_el_concepto_cambia_los_saltos_de_linea_y_controles_por_espacios():
    assert validar_concepto("cena\nsegunda línea\r\ty\x00z") == "cena segunda línea  y z"
    assert validar_concepto("\n\nhola\n") == "hola"


# ------------------------------------------------------------------ 86: login_bloqueado una sola vez por bloqueo

class _Clientes:
    def __init__(self):
        self.h = HasheadorScrypt().hashear(CONTRASENA_ALEX)

    def buscar_por_usuario(self, usuario):
        return (ALEX, self.h) if usuario == "alex" else None

    def obtener(self, cliente_id):
        return {ALEX.id: ALEX, ANA.id: ANA}.get(cliente_id)


@pytest.fixture
def acceso():
    reloj, auditoria = RelojFijo(), AuditoriaEnMemoria()
    iniciar = IniciarSesion(_Clientes(), HasheadorScrypt(), SesionesAutenticadasEnMemoria(reloj), IntentosEnMemoria(), reloj, auditoria)
    return iniciar, reloj, auditoria


def test_insistir_contra_una_cuenta_bloqueada_se_audita_una_sola_vez(acceso):
    iniciar, reloj, auditoria = acceso
    for _ in range(MAX_FALLOS):
        with pytest.raises((CredencialesInvalidas, CuentaBloqueada)):
            iniciar("alex", "mala")
    for _ in range(10):
        with pytest.raises(CuentaBloqueada):
            iniciar("alex", "mala")
    assert auditoria.acciones().count("login_bloqueado") == 1
    reloj.avanzar(6)  # el bloqueo caduca; otro bloqueo posterior vuelve a registrarse
    for _ in range(MAX_FALLOS):
        with pytest.raises((CredencialesInvalidas, CuentaBloqueada)):
            iniciar("alex", "mala")
    for _ in range(3):
        with pytest.raises(CuentaBloqueada):
            iniciar("alex", "mala")
    assert auditoria.acciones().count("login_bloqueado") == 2


# ------------------------------------------------------------------ 87: mensaje neutro si lo bloqueado es el origen

def test_si_se_bloquea_el_origen_el_mensaje_no_dice_cuenta_bloqueada(acceso):
    iniciar, *_ = acceso
    for i in range(MAX_FALLOS_IP - 1):
        with pytest.raises(CredencialesInvalidas):
            iniciar(f"u{i}", "mala", "10.0.0.9")
    with pytest.raises(CuentaBloqueada) as e:
        iniciar("alex", "mala", "10.0.0.9")  # el 100.º fallo bloquea el origen, no la cuenta de alex
    assert "Cuenta bloqueada" not in e.value.mensaje and e.value.mensaje.startswith("Demasiados intentos")
    for _ in range(MAX_FALLOS - 1):
        with pytest.raises(CredencialesInvalidas):
            iniciar("ana", "mala", "10.0.1.1")
    with pytest.raises(CuentaBloqueada) as e:  # el bloqueo de la cuenta sí lo dice
        iniciar("ana", "mala", "10.0.1.1")
    assert "Cuenta bloqueada" in e.value.mensaje


# ------------------------------------------------------------------ 88: cuándo se considera que se pide un gráfico

@pytest.mark.parametrize("pregunta", [
    "Hazme un gráfico de mis gastos por categoría", "Dibújame un gráfico de barras de mis gastos por categoría",
    "Quiero ver mis gastos en una tarta", "Genera un diagrama de tarta", "Muéstramelo en un gráfico",
    "Gráfico de gastos por mes", "¿Puedes hacerme una tarta con mis gastos?", "Represéntame mis gastos en un diagrama",
    "Hazme otro gráfico como el gráfico de antes",
])
def test_estas_frases_si_piden_un_grafico(pregunta):
    assert pide_un_grafico(pregunta)


@pytest.mark.parametrize("pregunta", [
    "¿Cuánto representa el alquiler sobre mis gastos?", "No me hagas gráfico, dímelo en texto",
    "¿Por qué el gráfico de antes sale tan alto?", "Visualiza mi saldo", "Dímelo sin gráfico",
    "Explícame el gráfico anterior", "Quiero ver el gráfico que me has hecho", "¿Cuánto gasto en comida?",
])
def test_estas_frases_no_piden_un_grafico(pregunta):
    assert not pide_un_grafico(pregunta)


def test_el_agente_no_empuja_si_generar_grafico_ya_se_llamo_aunque_fallara():
    """«No hay movimientos en ese periodo» es un error de la herramienta: empujar otra vez solo gasta tokens."""
    config = {"type": "bar", "data": {"labels": ["a", "b"], "datasets": [{"label": "X", "data": [1]}]}}  # 1 valor para 2 etiquetas
    llm = LLMGuionizado(llamada("generar_grafico", json.dumps({"titulo": "G", "config": config})), texto("No hay datos de ese periodo."))
    eventos, mensajes = correr(crear(llm, extra=[grafico.crear()]), "Hazme un gráfico de mis gastos por categoría")
    assert len(llm.llamadas) == 2  # ni un empujón extra
    assert not any(m.rol == "user" and (m.contenido or "").startswith("[auto]") for m in mensajes)
    assert eventos[-1].texto == "No hay datos de ese periodo."


def test_la_herramienta_ignora_la_config_del_modelo_si_llega_fuente():
    """Con `fuente` la rama de config no se ejecuta: ni siquiera se valida (incidencia 71, matizada)."""
    from backend.aplicacion.casos_uso.graficos import GenerarGraficoDeFuente
    llamado = {}

    class Falso(GenerarGraficoDeFuente):
        def __init__(self):
            pass

        def __call__(self, cliente, fuente, *args):
            llamado["fuente"] = fuente
            from backend.aplicacion.casos_uso.graficos import GraficoDeFuente
            from backend.aplicacion.eventos import Grafico
            return GraficoDeFuente(Grafico("T", {"type": "bar", "data": {}}), None, None, {})

    r = grafico.crear(Falso()).ejecutar({"titulo": "T", "fuente": "gastos_por_mes", "config": "basura {"}, ALEX)
    assert llamado == {"fuente": "gastos_por_mes"} and r.eventos[0].config["data"] == {}
