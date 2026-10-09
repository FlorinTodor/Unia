"""Síntesis de voz: OmniVoice como principal y Piper de reserva (sin GPU ni modelos: con dobles)."""
import io
import wave

import pytest

from backend.adaptadores.salida.voz.omnivoice import SintetizadorOmniVoice, _a_wav
from backend.adaptadores.salida.voz.reserva import SintetizadorConReserva


class VozFalsa:
    def __init__(self, nombre, disponible=True, falla=False):
        self.nombre, self._disponible, self._falla = nombre, disponible, falla
        self.precargada = False

    def disponible(self):
        return self._disponible

    def precargar(self):
        if self._falla:
            raise RuntimeError("sin memoria de GPU")
        self.precargada = True

    def sintetizar(self, texto):
        if self._falla:
            raise RuntimeError("sin memoria de GPU")
        return f"{self.nombre}:{texto}".encode()


def test_habla_con_la_principal_si_esta():
    voz = SintetizadorConReserva(VozFalsa("omni"), VozFalsa("piper"))
    voz.precargar()
    assert voz.sintetizar("hola") == b"omni:hola"


def test_sin_principal_usa_la_reserva_y_solo_precarga_esa():
    principal, reserva = VozFalsa("omni", disponible=False), VozFalsa("piper")
    voz = SintetizadorConReserva(principal, reserva)
    voz.precargar()
    assert not principal.precargada and reserva.precargada
    assert voz.sintetizar("hola") == b"piper:hola"


def test_si_la_principal_falla_la_app_arranca_y_habla_con_la_reserva():
    reserva = VozFalsa("piper")
    voz = SintetizadorConReserva(VozFalsa("omni", falla=True), reserva)
    voz.precargar()  # no lanza: el servidor arranca igual
    assert reserva.precargada
    assert voz.sintetizar("hola") == b"piper:hola"


def test_disponible_si_lo_esta_cualquiera_de_las_dos():
    assert SintetizadorConReserva(VozFalsa("o", disponible=False), VozFalsa("p")).disponible()
    assert not SintetizadorConReserva(VozFalsa("o", disponible=False), VozFalsa("p", disponible=False)).disponible()


def test_omnivoice_sin_voz_de_referencia_no_esta_disponible(tmp_path):
    assert not SintetizadorOmniVoice(tmp_path / "no_existe.wav").disponible()


def test_omnivoice_tras_un_fallo_de_carga_deja_de_estar_disponible(tmp_path):
    """Si la carga falla no se reintenta en cada frase (cada intento tarda segundos): pasa a la reserva."""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")  # sin .txt al lado: la carga falla antes de tocar la GPU
    voz = SintetizadorOmniVoice(ref)
    with pytest.raises(Exception):
        voz.precargar()
    assert not voz.disponible()


def test_wav_de_16_bits_mono_y_recorta_picos():
    datos = _a_wav([0.0, 0.5, -2.0, 2.0], 24000)
    with wave.open(io.BytesIO(datos)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 24000, 4)
        muestras = w.readframes(4)
    assert int.from_bytes(muestras[4:6], "little", signed=True) == -32767
    assert int.from_bytes(muestras[6:8], "little", signed=True) == 32767


def test_acorta_los_silencios_largos_a_mitad_de_frase_y_los_bordes():
    from backend.adaptadores.salida.voz.omnivoice import acortar_silencios

    fr = 1000  # 20 muestras por ventana de 20 ms
    voz, nada = [0.5] * 200, [0.0]
    audio = nada * 300 + voz + nada * 800 + voz + nada * 200 + voz + nada * 100  # 0,8 s y 0,2 s de silencio interno
    salida = acortar_silencios(audio, fr)
    # principio: de 0,3 s a 0,04 s (2 ventanas); la pausa de 0,8 s queda en 0,24 s; la de 0,2 s y el final (< 0,15 s) intactos
    assert len(salida) == len(audio) - (300 - 40) - (800 - 240)
    assert list(salida[:40]) == nada * 40 and salida[40] == 0.5
    assert list(salida[-100:]) == nada * 100


def test_un_chasquido_suelto_no_cuenta_como_inicio_de_la_frase():
    from backend.adaptadores.salida.voz.omnivoice import acortar_silencios

    chasquido = [0.02] * 20  # -34 dB: por encima del silencio, por debajo del habla
    audio = chasquido + [0.0] * 500 + [0.5] * 200
    assert len(acortar_silencios(audio, 1000)) == 40 + 200  # 0,04 s antes de hablar


def test_acortar_silencios_sin_voz_no_rompe():
    from backend.adaptadores.salida.voz.omnivoice import acortar_silencios

    assert len(acortar_silencios([0.0] * 500, 1000)) == 500
    assert len(acortar_silencios([], 1000)) == 0
