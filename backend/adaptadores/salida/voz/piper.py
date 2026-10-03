"""Adaptador Sintetizador: voz neuronal local con Piper."""
import io
import os
import wave
from pathlib import Path

RUTA_VOZ_PIPER = Path(__file__).resolve().parents[4] / "data" / "voces" / "es_ES-sharvard-medium.onnx"


class SintetizadorPiper:
    def __init__(self, ruta_modelo: Path = RUTA_VOZ_PIPER):
        self._ruta = ruta_modelo
        self._voz = None
        # escala de duración: menor = habla más rápido (0.78 ≈ 1.2x)
        self._length_scale = float(os.getenv("TTS_LENGTH_SCALE", "0.78"))

    def disponible(self) -> bool:
        return self._ruta.exists()

    def precargar(self) -> None:
        """Carga la voz una sola vez para que la primera respuesta hablada no espere."""
        if self._voz is None and self.disponible():
            from piper import PiperVoice

            self._voz = PiperVoice.load(str(self._ruta))

    def sintetizar(self, texto: str) -> bytes:
        self.precargar()
        from piper import SynthesisConfig

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            self._voz.synthesize_wav(texto, wav, syn_config=SynthesisConfig(length_scale=self._length_scale))
        return buffer.getvalue()
