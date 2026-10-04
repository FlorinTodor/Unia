"""Casos de uso de voz: transcribir lo que dice el usuario y sintetizar la respuesta."""
from ...dominio.errores import AudioDemasiadoGrande, DemasiadasPeticiones, ErrorDeValidacion, ErrorNoDisponible
from ...dominio.modelos import Cliente
from ..puertos.infraestructura import Reloj, RepositorioAjustes
from ..puertos.uso import LimitadorPeticiones
from ..puertos.voz import Sintetizador, Transcriptor
from ..texto import normalizar_para_voz

# audios de menos de ~0,5 s son silencio/ruido: Whisper alucina frases con ellos
MIN_BYTES_AUDIO = 4000
MAX_BYTES_AUDIO = 4 * 1024 * 1024  # ~10 min de webm/opus: más es un abuso, no una consulta
MAX_CARACTERES_TTS = 1200


def _limitar(limitador: LimitadorPeticiones, reloj: Reloj, cliente: Cliente) -> None:
    """La voz gasta cuota de Whisper o CPU de Piper: sin límite, un cliente podía agotarlas a base de peticiones."""
    espera = limitador.permitir(cliente.id, reloj.ahora())
    if espera:
        raise DemasiadasPeticiones(f"Demasiadas peticiones de voz. Espera {espera} s.", reintentar_en=espera)


class TranscribirAudio:
    def __init__(self, transcriptor: Transcriptor, ajustes: RepositorioAjustes, limitador: LimitadorPeticiones, reloj: Reloj):
        self._transcriptor = transcriptor
        self._ajustes = ajustes
        self._limitador = limitador
        self._reloj = reloj

    def disponible(self) -> bool:
        return self._ajustes.cargar().transcripcion() is not None

    def __call__(self, cliente: Cliente, audio: bytes, nombre_fichero: str = "audio.webm") -> str:
        _limitar(self._limitador, self._reloj, cliente)
        if not self.disponible():
            raise ErrorNoDisponible(
                "La voz necesita una clave de Groq u OpenAI (añádela en ⚙️ Ajustes). Mientras, puedes escribir."
            )
        if len(audio) > MAX_BYTES_AUDIO:
            raise AudioDemasiadoGrande("El audio es demasiado largo. Graba un mensaje más corto.")
        if len(audio) < MIN_BYTES_AUDIO:
            raise ErrorDeValidacion("No se ha detectado voz. Mantén pulsado y habla con claridad.")
        texto = self._transcriptor.transcribir(audio, nombre_fichero).strip()
        if not texto:
            raise ErrorDeValidacion("No se ha detectado voz en la grabación.")
        return texto


class SintetizarVoz:
    def __init__(self, sintetizador: Sintetizador, limitador: LimitadorPeticiones, reloj: Reloj):
        self._sintetizador = sintetizador
        self._limitador = limitador
        self._reloj = reloj

    def disponible(self) -> bool:
        return self._sintetizador.disponible()

    def __call__(self, cliente: Cliente, texto: str) -> bytes:
        _limitar(self._limitador, self._reloj, cliente)
        if not self._sintetizador.disponible():
            raise ErrorNoDisponible("TTS del servidor no disponible (falta el modelo de voz Piper).")
        texto = texto.strip()[:MAX_CARACTERES_TTS]
        if not texto:
            raise ErrorDeValidacion("Texto vacío.")
        return self._sintetizador.sintetizar(normalizar_para_voz(texto))
