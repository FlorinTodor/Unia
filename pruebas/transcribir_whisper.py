"""Transcribe WAV con faster-whisper (en CPU) y devuelve el texto y las marcas de tiempo de cada palabra.

Lo usan `grabar_video.py` (dividir un párrafo sintetizado en sus frases) y `disenar_voz.py --desde` (texto de la
voz de referencia). faster-whisper no está en el .venv de la app: se busca un python que lo tenga, por este orden:

    1. variable WHISPER_PY (ruta a un python con faster-whisper)
    2. VIDEO_TMP/whisper-venv/bin/python
    3. el .venv del proyecto

Para crear el venv: python3 -m venv $VIDEO_TMP/whisper-venv && $VIDEO_TMP/whisper-venv/bin/pip install faster-whisper
(el modelo «small» se descarga la primera vez a ~/.cache/huggingface). Va en CPU (int8) para no competir por la GPU
con OmniVoice.

Uso como programa (lo lanza `transcribir()` con el python que tenga faster-whisper):
    stdin  JSON: [{"ruta": "/x.wav", "pista": "texto esperado (opcional, ayuda a acertar)"}, ...]
    stdout JSON: [{"texto": "...", "palabras": [["palabra", ini, fin], ...]}, ...]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MODELO = os.environ.get("WHISPER_MODELO", "small")


def python_whisper():
    """Primer python con faster-whisper instalado, o None."""
    tmp = Path(os.environ.get("VIDEO_TMP", "/tmp/unia_video"))
    candidatos = [os.environ.get("WHISPER_PY"), tmp / "whisper-venv" / "bin" / "python", RAIZ / ".venv" / "bin" / "python"]
    for c in candidatos:
        if c and Path(c).exists():
            r = subprocess.run([str(c), "-c", "import faster_whisper"], capture_output=True)
            if r.returncode == 0:
                return str(c)
    return None


def transcribir(lote):
    """lote = [{"ruta", "pista"}] -> lista de {"texto", "palabras"}. Lanza RuntimeError si no hay faster-whisper."""
    py = python_whisper()
    if not py:
        raise RuntimeError("no encuentro faster-whisper (define WHISPER_PY o crea VIDEO_TMP/whisper-venv; ver "
                           "pruebas/transcribir_whisper.py)")
    r = subprocess.run([py, str(Path(__file__).resolve())], input=json.dumps(lote), capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"faster-whisper falló:\n{r.stderr[-1500:]}")
    return json.loads(r.stdout)


def _audio_16k(ruta):
    """El audio se decodifica con ffmpeg (no con PyAV: según la versión instalada, faster-whisper falla al abrirlo)."""
    import numpy as np
    crudo = subprocess.run(["ffmpeg", "-v", "error", "-i", str(ruta), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                           capture_output=True, check=True).stdout
    return np.frombuffer(crudo, np.float32)


def main():
    from faster_whisper import WhisperModel

    lote = json.load(sys.stdin)
    modelo = WhisperModel(MODELO, device="cpu", compute_type="int8")
    salida = []
    for item in lote:
        segmentos, _ = modelo.transcribe(_audio_16k(item["ruta"]), language="es", beam_size=5, word_timestamps=True,
                                         initial_prompt=item.get("pista") or None, vad_filter=False)
        palabras, textos = [], []
        for s in segmentos:
            textos.append(s.text.strip())
            for w in s.words or []:
                palabras.append([w.word.strip(), round(w.start, 3), round(w.end, 3)])
        salida.append({"texto": " ".join(t for t in textos if t), "palabras": palabras})
        print(f"   whisper: {Path(item['ruta']).name} ({len(palabras)} palabras)", file=sys.stderr, flush=True)
    json.dump(salida, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
