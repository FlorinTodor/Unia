"""Adaptador Sintetizador: voz neuronal local con OmniVoice (k2-fsa), clonando una voz de referencia fija.

Pesos CC-BY-NC (uso no comercial): válido para el reto; en producción habría que cambiar de modelo, que aquí
es cambiar este adaptador (DECISIONES nº 22).
"""
import importlib.util
import io
import logging
import os
import threading
import wave
from pathlib import Path

log = logging.getLogger(__name__)

RUTA_REFERENCIA = Path(__file__).resolve().parents[4] / "data" / "voces" / "unia_ref.wav"


class SintetizadorOmniVoice:
    def __init__(self, ruta_referencia: Path = RUTA_REFERENCIA):
        self._ref = ruta_referencia
        self._modelo = None
        self._prompt = None
        self._roto = False  # si la carga falló, no se reintenta en cada frase (cada intento tarda segundos)
        self._cerrojo = threading.Lock()  # una sola GPU: las frases se sintetizan de una en una
        # velocidad: < 1 más pausada. Con 0.95 el modelo metía más silencios a mitad de frase (de hasta 1 s)
        self._velocidad = float(os.getenv("TTS_VELOCIDAD", "1.0"))
        self._pasos = int(os.getenv("TTS_PASOS", "16"))  # pasos de decodificación: 32 = algo mejor, el doble de lento

    def disponible(self) -> bool:
        if self._roto or not self._ref.exists() or importlib.util.find_spec("omnivoice") is None:
            return False
        import torch

        return torch.cuda.is_available()  # en CPU tarda varios segundos por frase: mejor Piper

    def precargar(self) -> None:
        with self._cerrojo:
            if self._modelo is not None:
                return
            try:
                texto_ref = self._ref.with_suffix(".txt").read_text(encoding="utf-8").strip()  # antes que la GPU
                import torch
                from omnivoice import OmniVoice

                self._modelo = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)
                self._prompt = self._modelo.create_voice_clone_prompt(str(self._ref), ref_text=texto_ref)
                torch.cuda.empty_cache()  # el modelo ocupa 1,9 GB, pero la carga deja 5 GB reservados: la GPU es de 6
            except Exception:
                self._roto = True
                self._modelo = None
                raise

    def sintetizar(self, texto: str) -> bytes:
        self.precargar()
        from omnivoice.models.omnivoice import OmniVoiceGenerationConfig

        with self._cerrojo:
            audio = self._modelo.generate(
                text=texto, language="es", voice_clone_prompt=self._prompt, speed=self._velocidad,
                generation_config=OmniVoiceGenerationConfig(num_step=self._pasos),
            )[0]
            import torch

            torch.cuda.empty_cache()  # deja sitio a Ollama (qwen3:8b, último eslabón de la cadena LLM) en la misma GPU
        return _a_wav(acortar_silencios(audio, self._modelo.sampling_rate), self._modelo.sampling_rate)


SILENCIO_DB = -40.0  # por debajo, ventana sin voz
HABLA_DB = -30.0  # por encima, habla segura (no un chasquido suelto): marca dónde empieza y acaba la frase
MAX_PAUSA_S = 0.3  # pausas internas más largas se recortan…
PAUSA_S = 0.25  # …a esto: lo que dura una pausa natural de coma
ANTES_S, DESPUES_S = 0.05, 0.15  # silencio que se deja antes de la primera palabra y tras la última


def acortar_silencios(audio, frecuencia: int):
    """OmniVoice a veces se calla 0,3–1 s a mitad de frase («cortes» en las palabras): se dejan en una pausa de coma.
    Los bordes se recortan también: la app encadena frases y cada silencio de más se oiría como un hueco entre ellas.

    Se mide la energía en ventanas de 20 ms."""
    import numpy as np

    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    ventana = int(0.02 * frecuencia)
    n = len(a) // ventana
    if n == 0:
        return a
    energia = 20 * np.log10(np.sqrt((a[: n * ventana].reshape(n, ventana) ** 2).mean(1)) + 1e-9)
    habla = np.flatnonzero(energia > HABLA_DB)
    if len(habla) == 0:
        return a
    inicio = max(0, habla[0] - int(ANTES_S / 0.02))
    while inicio > 0 and energia[inicio - 1] > SILENCIO_DB:  # sin cortar el arranque suave de la palabra
        inicio -= 1
    final = min(n, habla[-1] + 1 + int(DESPUES_S / 0.02))
    a = a[inicio * ventana : final * ventana if final < n else len(a)]
    energia = energia[inicio:final]
    voz = np.flatnonzero(energia > SILENCIO_DB)
    max_ventanas, deja = int(MAX_PAUSA_S / 0.02), int(PAUSA_S / 0.02)
    trozos, desde, i = [], 0, voz[0]
    while i < voz[-1]:
        if energia[i] > SILENCIO_DB:
            i += 1
            continue
        fin = i
        while energia[fin] <= SILENCIO_DB:
            fin += 1
        if fin - i > max_ventanas:  # se conserva la mitad de la pausa a cada lado (sin chasquidos)
            corte_ini, corte_fin = (i + deja // 2) * ventana, (fin - (deja - deja // 2)) * ventana
            trozos.append(a[desde:corte_ini])
            desde = corte_fin
        i = fin
    trozos.append(a[desde:])
    return np.concatenate(trozos)


def _a_wav(audio, frecuencia: int) -> bytes:
    """float32 [-1, 1] → WAV PCM de 16 bits (lo que reproduce cualquier navegador)."""
    import numpy as np

    muestras = (np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(frecuencia)
        wav.writeframes(muestras.tobytes())
    return buffer.getvalue()
