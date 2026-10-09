"""Diseña voces candidatas con OmniVoice para elegir la de Unia.

    python pruebas/disenar_voz.py                  # genera candidatas en VIDEO_TMP/voces_candidatas/
    python pruebas/disenar_voz.py --elegir 3       # copia la nº 3 como referencia: data/voces/unia_ref.wav (+ .txt)
    python pruebas/disenar_voz.py --elegir 6 --nombre cliente   # otras voces del vídeo: data/voces/cliente_ref.wav

OmniVoice no tiene «acento de España» entre sus atributos: se generan varias combinaciones y semillas, se escuchan
y la elegida se guarda como audio de referencia. A partir de ella la app y el vídeo CLONAN siempre la misma voz
(diseñar en cada frase daría una voz distinta cada vez).
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = Path(os.environ.get("VIDEO_TMP", "/tmp/unia_video")) / "voces_candidatas"
DESTINO = RAIZ / "data" / "voces" / "unia_ref.wav"

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


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--elegir", type=int)
    p.add_argument("--nombre", default="unia", help="unia (la de la app) u otro papel del vídeo: cliente, movil…")
    a = p.parse_args()
    elegir(a.elegir, a.nombre) if a.elegir else generar()
