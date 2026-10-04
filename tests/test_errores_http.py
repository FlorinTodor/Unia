"""Todos los casos de error y su código HTTP."""
import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from backend.adaptadores.entrada.http import errores_http
from backend.adaptadores.salida.voz.whisper import TranscriptorWhisper
from backend.dominio import errores
from backend.dominio.ajustes import Ajustes, ConfigClave
from tests.fakes import AjustesEnMemoria
from tests.test_http import App, bd_base  # noqa: F401  (bd_base es un fixture)


def todas_las_clases():
    pendientes, vistas = [errores.ErrorDeDominio], []
    while pendientes:
        clase = pendientes.pop()
        vistas.append(clase)
        pendientes.extend(clase.__subclasses__())
    return vistas


# ------------------------------------------------------------------ el mapa

def test_ninguna_clase_de_error_cae_en_el_400_generico_por_descuido():
    sin_categoria = [c.__name__ for c in todas_las_clases() if c is not errores.ErrorDeDominio and errores_http.estado_http(c("x")) == 400]
    assert sin_categoria == []


@pytest.mark.parametrize("clase,estado", [
    (errores.ImporteInvalido, 422), (errores.LimiteBizumExcedido, 422), (errores.ConsultaNoPermitida, 422), (errores.CodigoIncorrecto, 422),
    (errores.NoAutenticado, 401), (errores.CredencialesInvalidas, 401),
    (errores.ErrorDeAccesoDenegado, 403),
    (errores.ContactoNoEncontrado, 404), (errores.OperacionNoEncontrada, 404), (errores.TarjetaNoEncontrada, 404),
    (errores.SaldoInsuficiente, 409), (errores.ContactoAmbiguo, 409), (errores.TarjetaAmbigua, 409), (errores.TarjetaYaBloqueada, 409), (errores.TarjetaYaActiva, 409), (errores.LimiteDiarioExcedido, 409), (errores.OperacionYaProcesada, 409),
    (errores.OperacionCaducada, 410),
    (errores.MensajeDemasiadoLargo, 413), (errores.AudioDemasiadoGrande, 413),
    (errores.ErrorTipoNoSoportado, 415),
    (errores.OperacionBloqueada, 423),
    (errores.CuentaBloqueada, 429), (errores.TurnoEnCurso, 429), (errores.DemasiadasPeticiones, 429), (errores.LimiteDeTokensExcedido, 429),
    (errores.ErrorProveedorExterno, 502), (errores.ErrorNoDisponible, 503), (errores.ErrorTiempoAgotado, 504),
    (errores.ErrorDeDominio, 400),
])
def test_cada_error_tiene_su_codigo(clase, estado):
    assert errores_http.estado_http(clase("x")) == estado


# ------------------------------------------------------------------ peticiones mal formadas

def test_json_roto_o_sin_cuerpo_es_400(tmp_path, bd_base):
    c = App(tmp_path, bd_base).cliente("alex")
    roto = c.post("/api/banco/bizum", content=b"{no es json", headers={"Content-Type": "application/json"})
    assert roto.status_code == 400 and roto.json()["detail"] == "La petición no es un JSON válido o está vacía."
    assert c.post("/chat").status_code == 400  # sin cuerpo


def test_campos_invalidos_son_422_con_el_detalle_por_campo(tmp_path, bd_base):
    c = App(tmp_path, bd_base).cliente("alex")
    r = c.post("/api/banco/bizum", json={"destinatario": "María", "importe": "mucho"})
    assert r.status_code == 422 and "importe" in r.json()["detail"]
    assert r.json()["errores"][0]["campo"] == "importe"
    assert c.get("/api/banco/movimientos", params={"limite": 0}).status_code == 422
    assert c.get("/api/banco/movimientos", params={"limite": 500}).status_code == 422
    assert c.get("/api/banco/movimientos", params={"limite": "abc"}).status_code == 422


def test_ruta_inexistente_404_y_metodo_incorrecto_405_con_json(tmp_path, bd_base):
    c = App(tmp_path, bd_base).cliente("alex")
    r404 = c.get("/api/banco/no-existe")
    assert r404.status_code == 404 and r404.json() == {"detail": "No existe ese recurso."}
    r405 = c.delete("/api/banco/saldo")
    assert r405.status_code == 405 and r405.json()["detail"] == "Método no permitido para este recurso." and "allow" in r405.headers


def test_una_operacion_con_id_inventado_es_404(tmp_path, bd_base):
    c = App(tmp_path, bd_base).cliente("alex")
    assert c.post("/operaciones/inventada/confirmar", json={"codigo": "123456"}).status_code == 404


# ------------------------------------------------------------------ 5xx sin filtrar detalles internos

def test_un_fallo_inesperado_es_500_con_referencia_y_sin_filtrar_el_error(tmp_path, bd_base):
    a = App(tmp_path, bd_base)

    @a.app.get("/boom")
    def boom():
        raise RuntimeError("clave=secreto-interno /home/florin/ruta")

    r = TestClient(a.app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500 and r.json()["detail"].startswith("Error interno del servidor. Referencia: ")
    assert "secreto-interno" not in r.text and "florin" not in r.text


# ------------------------------------------------------------------ origen (CSRF) y Retry-After

def test_una_escritura_desde_otro_origen_es_403_aunque_haya_cookie(tmp_path, bd_base):
    c = App(tmp_path, bd_base).cliente("alex")
    ajeno = c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 1}, headers={"Origin": "https://sitio-malicioso.example"})
    assert ajeno.status_code == 403 and ajeno.json()["detail"] == "Origen no permitido."
    propio = c.post("/api/banco/bizum", json={"destinatario": "María", "importe": 1}, headers={"Origin": "http://testserver"})
    assert propio.status_code == 200
    assert c.get("/api/banco/saldo", headers={"Origin": "https://otro.example"}).status_code == 200  # las lecturas no mutan


def test_el_login_bloqueado_trae_retry_after(tmp_path, bd_base):
    c = App(tmp_path, bd_base).cliente()
    for _ in range(5):
        r = c.post("/auth/login", json={"usuario": "alex", "contrasena": "mala"})
    assert r.status_code == 429 and r.headers["retry-after"] == "300"


# ------------------------------------------------------------------ voz: 413 y 415

def test_audio_demasiado_grande_413_y_fichero_que_no_es_audio_415(tmp_path, bd_base):
    a = App(tmp_path, bd_base, ajustes=AjustesEnMemoria(Ajustes(claves={"groq": ConfigClave("clave-falsa-groq")})))
    c = a.cliente("alex")
    enorme = c.post("/stt", files={"audio": ("a.webm", b"x" * (4 * 1024 * 1024 + 1), "audio/webm")})
    assert enorme.status_code == 413 and "demasiado largo" in enorme.json()["detail"]
    texto = c.post("/stt", files={"audio": ("nota.txt", b"hola" * 2000, "text/plain")})
    assert texto.status_code == 415
    assert c.post("/stt", files={"audio": ("a.webm", b"x" * 5000, "audio/webm")}).status_code == 200


# ------------------------------------------------------------------ Whisper: errores del proveedor

class _ClientesQueFallan:
    def __init__(self, error):
        self.error = error

    def cliente(self, _proveedor):
        error = self.error

        class _Transcripciones:
            @staticmethod
            def create(**_):
                raise error

        class _Cliente:
            audio = type("A", (), {"transcriptions": _Transcripciones})

        return _Cliente()


def _peticion():
    return httpx.Request("POST", "https://api.example/v1/audio")


def _status(clase, codigo):
    return clase("x", response=httpx.Response(codigo, request=_peticion()), body=None)


@pytest.mark.parametrize("error,esperado,estado", [
    (_status(openai.AuthenticationError, 401), errores.ErrorNoDisponible, 503),
    (_status(openai.RateLimitError, 429), errores.ErrorLimiteExcedido, 429),
    (openai.APITimeoutError(request=_peticion()), errores.ErrorTiempoAgotado, 504),
    (openai.APIConnectionError(request=_peticion()), errores.ErrorProveedorExterno, 502),
    (_status(openai.InternalServerError, 500), errores.ErrorProveedorExterno, 502),
])
def test_los_errores_de_whisper_se_traducen_a_errores_de_dominio(error, esperado, estado):
    ajustes = AjustesEnMemoria(Ajustes(claves={"groq": ConfigClave("clave-falsa-groq")}))
    with pytest.raises(esperado) as e:
        TranscriptorWhisper(ajustes, _ClientesQueFallan(error)).transcribir(b"x" * 5000, "a.webm")
    assert errores_http.estado_http(e.value) == estado
    assert "clave-falsa" not in e.value.mensaje  # el mensaje no filtra datos del proveedor
