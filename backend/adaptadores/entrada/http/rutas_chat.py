"""POST /chat (SSE), POST /stt, POST /tts y GET /estado."""
from fastapi import APIRouter, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from ....aplicacion.casos_uso.estado import ConsultarEstado
from ....aplicacion.casos_uso.voz import SintetizarVoz, TranscribirAudio
from ....aplicacion.chat import ServicioChat
from . import presentadores
from .sse import a_linea_sse


class PeticionChat(BaseModel):
    session_id: str
    mensaje: str


class PeticionTTS(BaseModel):
    texto: str


def crear_router(
    chat: ServicioChat, transcribir: TranscribirAudio, sintetizar: SintetizarVoz, estado: ConsultarEstado
) -> APIRouter:
    router = APIRouter()

    @router.post("/chat")
    def enviar(peticion: PeticionChat):
        flujo = (a_linea_sse(e) for e in chat.enviar(peticion.session_id, peticion.mensaje))
        return StreamingResponse(flujo, media_type="text/event-stream")

    @router.post("/stt")
    async def stt(audio: UploadFile):
        """Transcribe audio a texto."""
        contenido = await audio.read()
        return {"texto": transcribir(contenido, audio.filename or "audio.webm")}

    @router.post("/tts")
    def tts(peticion: PeticionTTS):
        """Sintetiza voz en el servidor para navegadores sin voces propias."""
        return Response(content=sintetizar(peticion.texto), media_type="audio/wav")

    @router.get("/estado")
    def obtener_estado():
        return presentadores.estado(estado())

    return router
