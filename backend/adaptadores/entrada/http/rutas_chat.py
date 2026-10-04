"""POST /chat (SSE), POST /stt, POST /tts y GET /estado."""
from collections.abc import Callable

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response, StreamingResponse

from ....aplicacion.casos_uso.estado import ConsultarEstado
from ....aplicacion.casos_uso.voz import MAX_BYTES_AUDIO, SintetizarVoz, TranscribirAudio
from ....aplicacion.chat import ServicioChat
from ....dominio.errores import ErrorTipoNoSoportado
from ....dominio.modelos import Cliente
from . import esquemas, presentadores
from .sse import a_linea_sse

_EJEMPLO_SSE = (
    'data: {"tipo": "herramienta", "dato": "consultar_saldo", "etiqueta": "Consultando saldo…"}\n\n'
    'data: {"tipo": "delta", "dato": "Tu saldo es "}\n\n'
    'data: {"tipo": "fin", "dato": "Tu saldo es 4.200,00 €."}\n\n'
)

_DESCRIPCION_CHAT = """Conversación con el asistente. La respuesta es un flujo **Server-Sent Events**: cada evento es
`data: {"tipo": ..., "dato": ...}` seguido de una línea en blanco.

| tipo | dato | significado |
|---|---|---|
| `delta` | texto | fragmento de la respuesta en streaming |
| `herramienta` | nombre (+ `etiqueta`) | el agente está ejecutando una herramienta |
| `aviso` | texto | nota informativa (p. ej. cambio de modelo) |
| `grafico` | `{titulo, config}` | configuración Chart.js completa |
| `operacion` | `{id, destinatario, importe, concepto, alertas, caduca}` | operación por confirmar con el código OTP (nunca incluye el código) |
| `uso` | `{tokens_turno, tokens_hoy, limite_dia}` | gasto de tokens de la consulta y del día (llega justo antes de `fin`) |
| `fin` | texto | respuesta completa |
| `error` | texto | fallo legible para el usuario |

Antes de abrir el flujo se comprueban los límites de uso y se responde con un error HTTP normal:
**422** mensaje vacío, **413** mensaje demasiado largo, **429** demasiadas peticiones por minuto o cuota diaria de
tokens agotada (con `Retry-After`).

Swagger no puede mostrar el streaming: usa `curl -N` o la interfaz web."""


def crear_router(
    chat: ServicioChat,
    transcribir: TranscribirAudio,
    sintetizar: SintetizarVoz,
    estado: ConsultarEstado,
    cliente_actual: Callable[..., Cliente],
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(cliente_actual)], responses=esquemas.NO_AUTENTICADO)  # todo requiere sesión

    @router.post(
        "/chat", tags=["chat"], summary="Enviar un mensaje al asistente (SSE)", description=_DESCRIPCION_CHAT,
        response_class=StreamingResponse,
        responses={
            200: {"description": "Flujo de eventos SSE.", "content": {"text/event-stream": {"example": _EJEMPLO_SSE}}},
            **esquemas.PETICION_INVALIDA, **esquemas.VALIDACION, **esquemas.LIMITE,
            413: {"model": esquemas.ErrorOut, "description": "El mensaje supera el máximo de caracteres."},
        },
    )
    def enviar(peticion: esquemas.PeticionChat, cliente: Cliente = Depends(cliente_actual)):
        flujo = (a_linea_sse(e) for e in chat.enviar(cliente, peticion.session_id, peticion.mensaje))
        return StreamingResponse(flujo, media_type="text/event-stream")

    @router.post(
        "/stt", tags=["voz"], response_model=esquemas.TranscripcionOut, summary="Transcribir voz a texto (Whisper)",
        description="Sube un audio (webm). Menos de ~0,5 s se rechaza para evitar alucinaciones de Whisper.",
        responses={
            **esquemas.VALIDACION, **esquemas.LIMITE, **esquemas.PROVEEDOR,
            413: {"model": esquemas.ErrorOut, "description": "El audio supera los 4 MB."},
            415: {"model": esquemas.ErrorOut, "description": "El fichero no es un audio."},
            503: {"model": esquemas.ErrorOut, "description": "No hay clave con voz (Groq u OpenAI)."},
        },
    )
    async def stt(audio: UploadFile, cliente: Cliente = Depends(cliente_actual)):
        if audio.content_type and not audio.content_type.startswith(("audio/", "video/webm", "application/octet-stream")):
            raise ErrorTipoNoSoportado("El fichero debe ser un audio (webm, wav, mp3...).")
        # el middleware `LimiteSubidaAudio` ya acotó la subida (sesión, Content-Length y bytes reales); un byte de más
        # basta para que el caso de uso rechace el audio por grande
        contenido = await audio.read(MAX_BYTES_AUDIO + 1)
        return {"texto": transcribir(cliente, contenido, audio.filename or "audio.webm")}

    @router.post(
        "/tts", tags=["voz"], summary="Sintetizar voz en el servidor (Piper)",
        description="Devuelve audio WAV. Los números se convierten a palabras antes de sintetizar.",
        response_class=Response,
        responses={
            200: {"description": "Audio WAV.", "content": {"audio/wav": {}}},
            **esquemas.VALIDACION, **esquemas.LIMITE,
            503: {"model": esquemas.ErrorOut, "description": "Falta el modelo de voz Piper."},
        },
    )
    def tts(peticion: esquemas.PeticionTTS, cliente: Cliente = Depends(cliente_actual)):
        return Response(content=sintetizar(cliente, peticion.texto), media_type="audio/wav")

    @router.get("/estado", tags=["estado"], response_model=esquemas.EstadoOut, summary="Estado del asistente",
                description="Modelo en uso, cadena de respaldo y disponibilidad de la voz.")
    def obtener_estado():
        return presentadores.estado(estado())

    return router
