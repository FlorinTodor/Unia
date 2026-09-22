"""Servidor FastAPI: frontend estático, chat SSE, voz (Whisper/Piper) y API bancaria."""
import io
import json
import os
import re
import wave
from pathlib import Path

from num2words import num2words

from fastapi import FastAPI, HTTPException, UploadFile
from openai import RateLimitError
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agente, ajustes, ajustes_api, banco_api, db
from .config import get_cliente_stt

RUTA_VOZ_PIPER = Path(__file__).resolve().parent.parent / "data" / "voces" / "es_ES-sharvard-medium.onnx"
# escala de duración de Piper: menor = habla más rápido (0.78 ≈ 1.2x)
TTS_LENGTH_SCALE = float(os.getenv("TTS_LENGTH_SCALE", "0.78"))
_VOZ_PIPER = None

# caracteres unicode de ancho cero que los modelos cuelan a veces en el texto
_RE_INVISIBLES = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")

# Piper lee los números dígito a dígito, así que se convierten a palabras antes
_RE_IMPORTE = re.compile(r"(?P<entero>\d{1,3}(?:[.\s ]\d{3})+|\d+)(?:,(?P<dec>\d{1,2}))?\s*€")
_RE_NUMERO = re.compile(r"\d+")


def _importe_a_palabras(m: re.Match) -> str:
    entero = int(re.sub(r"[.\s ]", "", m.group("entero")))
    frase = "un euro" if entero == 1 else num2words(entero, lang="es") + " euros"
    centimos = int(m.group("dec") or 0)
    if centimos:
        frase += " con " + ("un céntimo" if centimos == 1 else num2words(centimos, lang="es") + " céntimos")
    return frase


def _numero_a_palabras(m: re.Match) -> str:
    # los números largos (teléfonos, IBAN) se dejan tal cual: dígito a dígito
    if len(m.group()) > 7:
        return m.group()
    return num2words(int(m.group()), lang="es")


def _normalizar_para_voz(texto: str) -> str:
    texto = _RE_IMPORTE.sub(_importe_a_palabras, texto)
    return _RE_NUMERO.sub(_numero_a_palabras, texto)


def _voz_piper():
    """Carga (una sola vez) la voz de Piper para el TTS del servidor."""
    global _VOZ_PIPER
    if _VOZ_PIPER is None and RUTA_VOZ_PIPER.exists():
        from piper import PiperVoice

        _VOZ_PIPER = PiperVoice.load(str(RUTA_VOZ_PIPER))
    return _VOZ_PIPER

app = FastAPI(title="Habla con tu dinero — Reto Unicaja/UGR")
app.include_router(banco_api.router)
app.include_router(ajustes_api.router)

RUTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

# Historial de conversación por sesión (en memoria)
SESIONES: dict[str, list[dict]] = {}
MAX_MENSAJES_HISTORIAL = 40


@app.on_event("startup")
def startup():
    db.inicializar()
    _voz_piper()  # precarga la voz para que la primera respuesta hablada no espere


class PeticionChat(BaseModel):
    session_id: str
    mensaje: str


def _compactar_historial(mensajes: list[dict]) -> None:
    """Elimina el tráfico de herramientas (resultados SQL, configs de gráficos)
    de los turnos anteriores al último, dejando solo el texto conversacional.

    Sin esto, cada petición reenvía miles de tokens de historial y agota el
    límite de tokens/minuto del proveedor (429 → reintentos → latencia).
    """
    ultimo_turno = max(
        (i for i, m in enumerate(mensajes) if m["role"] == "user"),
        default=len(mensajes),
    )
    compactados = []
    for i, m in enumerate(mensajes):
        if i >= ultimo_turno or m["role"] in ("system", "user"):
            compactados.append(m)
        elif m["role"] == "assistant" and m.get("content"):
            compactados.append({"role": "assistant", "content": m["content"]})
        # tool y assistant sin texto (solo tool_calls) se descartan
    mensajes[:] = compactados


@app.post("/chat")
def chat(peticion: PeticionChat):
    mensajes = SESIONES.setdefault(
        peticion.session_id,
        [{"role": "system", "content": agente.construir_system_prompt()}],
    )
    _compactar_historial(mensajes)
    # recortar historial conservando el system prompt
    if len(mensajes) > MAX_MENSAJES_HISTORIAL:
        del mensajes[1 : len(mensajes) - MAX_MENSAJES_HISTORIAL + 1]
    mensajes.append({"role": "user", "content": peticion.mensaje})

    def flujo_sse():
        try:
            for tipo, dato in agente.responder(mensajes):
                if isinstance(dato, str):
                    # los modelos a veces cuelan caracteres invisibles (p. ej. "202​​2026")
                    dato = _RE_INVISIBLES.sub("", dato)
                yield f"data: {json.dumps({'tipo': tipo, 'dato': dato}, ensure_ascii=False)}\n\n"
        except RateLimitError:
            aviso = (
                "El proveedor ha alcanzado su límite de tokens por minuto. "
                "Espera unos segundos y vuelve a intentarlo."
            )
            yield f"data: {json.dumps({'tipo': 'error', 'dato': aviso}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 — el error debe llegar al cliente
            yield f"data: {json.dumps({'tipo': 'error', 'dato': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(flujo_sse(), media_type="text/event-stream")


@app.post("/stt")
async def stt(audio: UploadFile):
    """Transcribe audio a texto con Whisper (Groq)."""
    stt_cfg = get_cliente_stt()
    if stt_cfg is None:
        raise HTTPException(
            503, "La voz necesita una clave de Groq u OpenAI (añádela en ⚙️ Ajustes). Mientras, puedes escribir."
        )
    cliente, modelo_stt = stt_cfg
    contenido = await audio.read()
    # audios de menos de ~0,5 s son silencio/ruido: Whisper alucina frases con ellos
    if len(contenido) < 4000:
        raise HTTPException(422, "No se ha detectado voz. Mantén pulsado y habla con claridad.")
    transcripcion = cliente.audio.transcriptions.create(
        model=modelo_stt,
        file=(audio.filename or "audio.webm", contenido),
        language="es",
        temperature=0.0,
        # sesga la transcripción hacia el dominio de la app y reduce alucinaciones
        prompt="Consulta a un asistente bancario en español: saldo, movimientos, gastos, Bizum, gráficos.",
    )
    texto = transcripcion.text.strip()
    if not texto:
        raise HTTPException(422, "No se ha detectado voz en la grabación.")
    return {"texto": texto}


class PeticionTTS(BaseModel):
    texto: str


@app.post("/tts")
def tts(peticion: PeticionTTS):
    """Sintetiza voz en el servidor (Piper) para navegadores sin voces propias."""
    voz = _voz_piper()
    if voz is None:
        raise HTTPException(503, "TTS del servidor no disponible (falta el modelo de voz Piper).")
    texto = peticion.texto.strip()[:1200]
    if not texto:
        raise HTTPException(422, "Texto vacío.")
    texto = _normalizar_para_voz(texto)
    from piper import SynthesisConfig

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        voz.synthesize_wav(texto, wav, syn_config=SynthesisConfig(length_scale=TTS_LENGTH_SCALE))
    return Response(content=buffer.getvalue(), media_type="audio/wav")


@app.get("/estado")
def estado():
    return {
        "ok": True,
        **agente.info_proveedor(),
        "voz_disponible": get_cliente_stt() is not None,
        "tts_servidor": RUTA_VOZ_PIPER.exists(),
        "configurado": ajustes.cargar()["activo"] is not None,
    }


@app.get("/")
def index():
    return FileResponse(RUTA_FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=RUTA_FRONTEND), name="static")
