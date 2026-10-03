"""Agente conversacional: bucle de tool calling con streaming y cadena de fallback.

No conoce ningún SDK: habla con el puerto `ProveedorLLM` y con el `RegistroHerramientas`.
`responder` es un generador de `EventoChat` que el adaptador de entrada reenvía al cliente.
"""
import json
from collections.abc import Iterator

from ..dominio.errores import ErrorNoDisponible
from ..dominio.modelos import LlamadaHerramienta, Mensaje
from ..dominio.proveedores import OLLAMA, ModeloRef, nombre_proveedor
from .eventos import Aviso, Delta, EventoChat, Fin, HerramientaEnUso
from .herramientas.registro import RegistroHerramientas
from .puertos.infraestructura import RepositorioAjustes
from .puertos.llm import (
    ClaveInvalida,
    CuotaAgotada,
    DeltaTexto,
    ErrorProveedor,
    GeneracionFallida,
    ModeloNoEncontrado,
    PeticionHerramientas,
    ProveedorInaccesible,
    ProveedorLLM,
    ProveedorNoUtilizable,
)

MAX_RONDAS = 6
MAX_REINTENTOS_GENERACION = 2


def explicar_fallo(eslabon: ModeloRef, error: ProveedorNoUtilizable) -> str:
    """Traduce el fallo de un eslabón a un mensaje comprensible para el usuario."""
    nombre = nombre_proveedor(eslabon.proveedor)
    if isinstance(error, ClaveInvalida):
        return f"La clave API de {nombre} no es válida (revísala en ⚙️ Ajustes)."
    if isinstance(error, ModeloNoEncontrado):
        return f"El modelo {eslabon.modelo} ya no existe en {nombre} (elige otro en ⚙️ Ajustes)."
    if isinstance(error, CuotaAgotada):
        return f"{eslabon.modelo} ha agotado su cuota gratuita por ahora."
    if isinstance(error, ProveedorInaccesible) and eslabon.proveedor == OLLAMA:
        return "La IA local no responde: ¿está Ollama en marcha (`ollama serve`)?"
    return f"{eslabon.modelo} ({nombre}) no está disponible."


class Agente:
    def __init__(self, llm: ProveedorLLM, herramientas: RegistroHerramientas, ajustes: RepositorioAjustes):
        self._llm = llm
        self._herramientas = herramientas
        self._ajustes = ajustes

    def responder(self, mensajes: list[Mensaje]) -> Iterator[EventoChat]:
        """Ejecuta el bucle del agente sobre `mensajes` (se amplía in situ).

        Si un eslabón falla (cuota, clave, red) se pasa al siguiente de la cadena y la
        conversación continúa. Los cambios de eslabón y los reintentos NO consumen rondas.
        """
        cadena = self._ajustes.cargar().cadena_llm()
        if not cadena:
            raise ErrorNoDisponible(
                "No hay ningún motor de IA disponible. Abre ⚙️ Ajustes y añade tu clave de Groq "
                "o activa la IA local (Ollama)."
            )
        posicion = 0
        reintentos_generacion = 0
        rondas = 0

        while rondas < MAX_RONDAS:
            partes: list[str] = []
            llamadas: tuple[LlamadaHerramienta, ...] = ()
            try:
                for evento in self._llm.completar(cadena[posicion], mensajes, self._herramientas.esquemas()):
                    if isinstance(evento, DeltaTexto):
                        partes.append(evento.texto)
                        yield Delta(evento.texto)
                    elif isinstance(evento, PeticionHerramientas):
                        llamadas = evento.llamadas
            except ProveedorNoUtilizable as e:
                motivo = explicar_fallo(cadena[posicion], e)
                posicion += 1
                if posicion >= len(cadena):
                    raise ErrorNoDisponible(motivo) from e
                siguiente = cadena[posicion]
                yield Aviso(f"{motivo} Cambiando a {siguiente.modelo} ({nombre_proveedor(siguiente.proveedor)}).")
                continue
            except GeneracionFallida:
                # fallo esporádico del modelo: se reintenta la ronda en silencio
                reintentos_generacion += 1
                if reintentos_generacion > MAX_REINTENTOS_GENERACION:
                    raise
                continue

            rondas += 1
            texto = "".join(partes)

            if not llamadas:
                mensajes.append(Mensaje.asistente(texto))
                yield Fin(texto)
                return

            mensajes.append(Mensaje.asistente(texto or None, llamadas))
            for llamada in llamadas:
                yield HerramientaEnUso(llamada.nombre, self._herramientas.etiqueta(llamada.nombre))
                resultado = self._herramientas.ejecutar(llamada.nombre, llamada.argumentos)
                yield from resultado.eventos
                mensajes.append(
                    Mensaje.resultado_herramienta(llamada.id, json.dumps(resultado.datos, ensure_ascii=False))
                )

        yield from self._respuesta_final_sin_herramientas(cadena[posicion], mensajes)

    def _respuesta_final_sin_herramientas(self, eslabon: ModeloRef, mensajes: list[Mensaje]) -> Iterator[EventoChat]:
        """Se agotaron las rondas: se fuerza una respuesta SIN herramientas para que el
        usuario reciba al menos un resumen de lo conseguido."""
        partes: list[str] = []
        try:
            for evento in self._llm.completar(eslabon, mensajes, None):
                if isinstance(evento, DeltaTexto):
                    partes.append(evento.texto)
                    yield Delta(evento.texto)
        except ErrorProveedor:
            partes = []
        texto = "".join(partes).strip() or "Lo siento, no he podido completar la operación. ¿Puedes reformularla?"
        mensajes.append(Mensaje.asistente(texto))
        yield Fin(texto)
