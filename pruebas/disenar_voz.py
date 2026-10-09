"""Diseña voces candidatas con OmniVoice para elegir la de Unia.

    python pruebas/disenar_voz.py                  # genera candidatas en VIDEO_TMP/voces_candidatas/
    python pruebas/disenar_voz.py --elegir 3       # copia la nº 3 como referencia: data/voces/unia_ref.wav (+ .txt)
    python pruebas/disenar_voz.py --elegir 6 --nombre cliente   # otras voces del vídeo: data/voces/cliente_ref.wav
    python pruebas/disenar_voz.py --desde grabacion.m4a --nombre narrador   # referencia desde TU voz grabada
    python pruebas/disenar_voz.py --desde grabacion.wav --nombre narrador --texto "lo que dices en la grabación"
    python pruebas/disenar_voz.py --autotest       # prueba sin GPU del recorte (WAV sintético con ffmpeg)

OmniVoice no tiene «acento de España» entre sus atributos: se generan varias combinaciones y semillas, se escuchan
y la elegida se guarda como audio de referencia. A partir de ella la app y el vídeo CLONAN siempre la misma voz
(diseñar en cada frase daría una voz distinta cada vez).

Referencia desde una grabación real (`--desde`, sin GPU): suena mucho menos a IA que una voz diseñada.
Qué grabar: 20-30 s leyendo en voz alta un párrafo del guion (pruebas/guion_locucion.json, por ejemplo el de la
arquitectura), con tu voz natural y el ritmo de una explicación, sin música ni ruido de fondo, con el micrófono (o el
móvil) a unos 20 cm de la boca y en una habitación sin eco (mejor con cortinas, sofá o armarios que en una cocina o un
baño). Vale WAV, M4A (notas de voz del móvil) u OGG.
El script la pasa a mono 24 kHz, quita el silencio de los bordes, normaliza el nivel (loudnorm) y se queda como mucho con
los primeros 15 s de voz, cortando en una pausa (OmniVoice clona mejor con 8-15 s limpios). Después transcribe el
fragmento con faster-whisper (ver pruebas/transcribir_whisper.py; WHISPER_PY = python con faster-whisper) porque
OmniVoice NECESITA el texto exacto de la referencia: revisa la transcripción que muestra y, si tiene errores, corrígela
en data/voces/<nombre>_ref.txt o repite con --texto "…". No sobrescribe una referencia que ya exista salvo con --forzar.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = Path(os.environ.get("VIDEO_TMP", "/tmp/unia_video")) / "voces_candidatas"
DESTINO = RAIZ / "data" / "voces" / "unia_ref.wav"
MAX_REF = 15.0   # s: OmniVoice clona mejor con 8-15 s limpios
MIN_REF = 8.0

# frase de referencia: tono de asistente, con números y una pregunta (lo que más se oye en la app)
FRASE = ("Hola, soy Unia, tu asistente de Unicaja. Este mes llevas gastados trescientos doce euros en supermercados, "
         "un poco menos que en septiembre. ¿Quieres que te enseñe el detalle?")

DISENOS = [
    "female, middle-aged, low pitch",
    "female, middle-aged, moderate pitch",
    "female, young adult, low pitch",
    "female, young adult, moderate pitch",
    "male, middle-aged, low pitch",
    "male, young adult, moderate pitch",
]
SEMILLAS = [7, 21]


def generar():
    import soundfile as sf
    import torch
    from omnivoice import OmniVoice

    CARPETA.mkdir(parents=True, exist_ok=True)
    modelo = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0", dtype=torch.float16)
    indice = {}
    n = 0
    for diseno in DISENOS:
        for semilla in SEMILLAS:
            n += 1
            torch.manual_seed(semilla)
            audio = modelo.generate(text=FRASE, language="es", instruct=diseno, speed=0.95)[0]
            ruta = CARPETA / f"{n:02d}.wav"
            sf.write(ruta, audio, modelo.sampling_rate)
            indice[n] = {"diseno": diseno, "semilla": semilla}
            print(f"{n:02d}  {diseno}  (semilla {semilla})", flush=True)
    (CARPETA / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1))


def elegir(n: int, nombre: str = "unia"):
    destino = DESTINO.with_name(f"{nombre}_ref.wav")
    origen = CARPETA / f"{n:02d}.wav"
    if not origen.exists():
        sys.exit(f"No existe {origen}: genera primero las candidatas.")
    shutil.copy(origen, destino)
    destino.with_suffix(".txt").write_text(FRASE + "\n")
    print(f"Referencia guardada en {destino.relative_to(RAIZ)}")


def _ff(*args):
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-nostats", *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg falló:\n{r.stderr[-1200:]}")
    return r.stderr


def _duracion(ruta):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                                capture_output=True, text=True, check=True).stdout)


def _pausas(ruta):
    """[(inicio, fin)] de las pausas de al menos 0,25 s (silencedetect)."""
    log = _ff("-i", ruta, "-af", "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-")
    inicios = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    fines = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    return list(zip(inicios, fines))


def punto_final(pausas, total, maximo=MAX_REF, minimo=MIN_REF):
    """Dónde acaba la referencia: todo si cabe; si no, en la primera pausa larga (≥ 1 s) tras `minimo` o, si no hay,
    en la última pausa antes de `maximo` (nunca a mitad de palabra salvo que no haya ninguna pausa)."""
    if total <= maximo:
        return total
    medios = [((a + b) / 2, b - a) for a, b in pausas if (a + b) / 2 <= maximo]
    largas = [m for m, d in medios if d >= 1.0 and m >= minimo]
    if largas:
        return largas[0]
    utiles = [m for m, _ in medios if m >= 3.0]
    return utiles[-1] if utiles else maximo


def preparar_referencia(origen, salida):
    """origen (wav/m4a/ogg…) -> salida: mono 24 kHz, sin silencio en los bordes, nivel normalizado y ≤ 15 s."""
    with tempfile.TemporaryDirectory() as d:
        limpio = Path(d) / "limpio.wav"
        bordes = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08"
        _ff("-i", origen, "-af", f"aformat=channel_layouts=mono,highpass=f=60,{bordes},areverse,{bordes},areverse,"
            "loudnorm=I=-18:TP=-2:LRA=11", "-ar", 24000, "-ac", 1, limpio)
        total = _duracion(limpio)
        fin = punto_final(_pausas(limpio), total)
        _ff("-i", limpio, "-af", f"atrim=0:{fin:.3f},afade=t=out:st={max(0, fin - 0.05):.3f}:d=0.05",
            "-ar", 24000, "-ac", 1, "-c:a", "pcm_s16le", salida)
    return _duracion(salida)


def desde_grabacion(origen, nombre, texto=None, carpeta=None, forzar=False):
    carpeta = Path(carpeta) if carpeta else DESTINO.parent
    destino = carpeta / f"{nombre}_ref.wav"
    if not Path(origen).exists():
        sys.exit(f"No existe {origen}")
    if destino.exists() and not forzar:
        sys.exit(f"Ya existe {destino}: usa otro --nombre o --forzar para sustituirla.")
    carpeta.mkdir(parents=True, exist_ok=True)
    provisional = carpeta / f".{nombre}_ref.provisional.wav"
    segundos = preparar_referencia(origen, provisional)
    print(f"Referencia: {segundos:.1f} s, mono 24 kHz, nivel normalizado")
    if segundos < MIN_REF:
        print(f"AVISO: menos de {MIN_REF:.0f} s de voz; OmniVoice clona mejor con 8-15 s (graba algo más largo).")
    if texto is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from transcribir_whisper import transcribir
        try:
            texto = transcribir([{"ruta": str(provisional)}])[0]["texto"].strip()
        except Exception as e:
            print(f"AVISO: no he podido transcribir ({e}).")
            texto = ""
    provisional.replace(destino)
    destino.with_suffix(".txt").write_text(texto + "\n")
    print(f"Guardada en {destino} (+ .txt)")
    print(f"Transcripción: «{texto}»")
    if texto:
        print(f"Revísala: debe ser EXACTAMENTE lo que se oye. Si no, corrige {destino.with_suffix('.txt')} "
              "o repite con --texto \"…\" --forzar.")
    else:
        print("AVISO: la transcripción está vacía y OmniVoice la necesita: escríbela en el .txt o repite con --texto.")
    return destino


def autotest():
    """Sin GPU: un M4A sintético (1 s de silencio, 25 s de «voz» con pausas, 1 s de silencio) debe quedar en un WAV mono
    24 kHz de 8-15 s que empieza con sonido."""
    d = Path(tempfile.mkdtemp(prefix="unia_autotest_voz_"))
    tono = "aevalsrc='0.3*sin(2*PI*200*t)*(0.6+0.4*sin(2*PI*3*t))':s=44100:d=2.4"
    partes = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=1"]
    for _ in range(10):   # 10 x (2,4 s de tono + 0,4 s de pausa) = 28 s
        partes += ["-f", "lavfi", "-i", tono, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=0.4"]
    n = len(partes) // 4
    entradas = "".join(f"[{i}:a]aformat=channel_layouts=stereo:sample_rates=44100[s{i}];" for i in range(n))
    _ff(*partes, "-filter_complex", entradas + "".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1",
        "-c:a", "aac", d / "grabacion.m4a")
    ref = desde_grabacion(d / "grabacion.m4a", "prueba", texto="", carpeta=d)
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels", "-of", "csv=p=0",
                           str(ref)], capture_output=True, text=True, check=True).stdout.strip()
    segundos = _duracion(ref)
    assert info == "24000,1", info
    assert MIN_REF <= segundos <= MAX_REF, segundos
    assert _pausas(ref)[:1] == [] or _pausas(ref)[0][0] > 0.05, "empieza con silencio"
    print(f"autotest correcto: {ref} ({info.replace(',', ' Hz, ')} canal, {segundos:.2f} s)")
    print(f"punto_final: {punto_final([(9.6, 10.0), (12.4, 12.8), (15.2, 15.6)], 28):.2f} s (esperado 12.60)")
    assert abs(punto_final([(9.6, 10.0), (12.4, 12.8), (15.2, 15.6)], 28) - 12.6) < 1e-6
    assert abs(punto_final([(4.0, 4.2), (9.0, 10.4)], 28) - 9.7) < 1e-6   # pausa larga tras 8 s: corta ahí
    assert punto_final([], 12) == 12


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--elegir", type=int)
    p.add_argument("--nombre", default="unia", help="unia (la de la app) u otro papel del vídeo: cliente, movil, narrador…")
    p.add_argument("--desde", help="grabación tuya (wav, m4a, ogg…) para crear la referencia sin diseñar la voz")
    p.add_argument("--texto", help="con --desde: texto exacto de la grabación (si no, se transcribe con faster-whisper)")
    p.add_argument("--forzar", action="store_true", help="con --desde: sustituye una referencia que ya exista")
    p.add_argument("--autotest", action="store_true")
    a = p.parse_args()
    if a.autotest:
        autotest()
    elif a.desde:
        desde_grabacion(a.desde, a.nombre, a.texto, forzar=a.forzar)
    elif a.elegir:
        elegir(a.elegir, a.nombre)
    else:
        generar()
