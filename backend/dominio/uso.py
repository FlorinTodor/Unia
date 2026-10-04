"""Control del gasto de tokens de la IA: medición, presupuestos y reglas de límite."""
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from .errores import ErrorDeValidacion, LimiteDeTokensExcedido, MensajeDemasiadoLargo


@dataclass(frozen=True)
class Uso:
    """Tokens consumidos en una llamada al modelo."""

    entrada: int = 0
    salida: int = 0
    estimado: bool = False  # True si el proveedor no informó y se calculó a partir del texto

    @property
    def total(self) -> int:
        return self.entrada + self.salida

    def __add__(self, otro: "Uso") -> "Uso":
        return Uso(self.entrada + otro.entrada, self.salida + otro.salida, self.estimado or otro.estimado)


@dataclass(frozen=True)
class PresupuestoUso:
    """Límites de uso de la IA. Los valores por defecto caben en el plan gratuito de Groq."""

    tokens_por_dia: int = 80_000  # por cliente
    tokens_por_dia_local: int = 400_000  # tope propio del modelo local (gratis, pero no infinito: evita bucles y abusos)
    tokens_por_turno: int = 30_000  # una pregunta, con todas sus rondas de herramientas
    max_caracteres_mensaje: int = 1_500
    max_tokens_respuesta: int = 4_096  # tope de salida por llamada (incluye el razonamiento de gpt-oss)
    peticiones_por_minuto: int = 20  # por cliente
    max_tokens_historial: int = 3_000  # lo que se reenvía de la conversación anterior
    max_caracteres_resultado: int = 6_000  # un resultado SQL no ocupa más que esto en el contexto


def estimar_tokens(texto: str) -> int:
    """Aproximación para el español: ~3,3 caracteres por token. Solo se usa si el proveedor no informa."""
    return -(-len(texto) * 10 // 33)


# Prefijo de los mensajes que el propio sistema se inyecta (correcciones al modelo, resultado de un Bizum).
# Un usuario no puede escribirlo: pasaría por una instrucción del sistema y no se contaría como pregunta suya.
MARCA_AUTOMATICA = "[auto]"


_ZWJ = "\u200d"  # une las partes de un emoji compuesto (👨‍👩‍👧): quitarlo lo parte en sus trozos


def quitar_invisibles(texto: str) -> str:
    """Quita los caracteres de formato Unicode (categoría Cf): ancho cero, guion blando U+00AD, U+2062...
    Conserva el ZWJ (U+200D): lo que escribe el usuario o responde el modelo puede llevar emoji compuestos. Para
    COMPROBAR la marca reservada se aplica la limpieza completa (`_quitar_todo_formato`)."""
    return "".join(c for c in texto if c == _ZWJ or unicodedata.category(c) != "Cf")


def _quitar_todo_formato(texto: str) -> str:
    return "".join(c for c in texto if unicodedata.category(c) != "Cf")


def sustituir_controles(texto: str) -> str:
    """Los caracteres de control (Cc: saltos de línea, tabuladores...) y los separadores de línea/párrafo pasan a espacio."""
    return "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in texto)


# letras de «auto» que otros alfabetos dibujan igual (cirílico, griego, armenio) y las versalitas latinas (ᴀᴜᴛᴏ)
_CONFUSABLES = str.maketrans({
    "а": "a", "α": "a", "ɑ": "a", "ａ": "a", "ᴀ": "a",
    "υ": "u", "ս": "u", "ц": "u", "ᴜ": "u",
    "т": "t", "τ": "t", "ᴛ": "t",
    "о": "o", "ο": "o", "օ": "o", "σ": "o", "ᴏ": "o", "0": "o",
})
# cualquier corchete de apertura (también ⁅ y 【, que NFKD no convierte, y «\[») seguido de «aut»: no hace falta que
# el modelo de lenguaje lo vea completo como «[auto]» para que lo trate como orden del sistema
_RE_MARCA = re.compile(r"[\[【⁅]\s*aut")


def _normalizar_para_marca(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", _quitar_todo_formato(texto))
    sin_acentos = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return sin_acentos.lower().translate(_CONFUSABLES)


def contiene_marca_automatica(texto: str) -> bool:
    """¿Aparece un corchete seguido de «aut» en CUALQUIER posición («[auto]», «[aut0]», «【auto】», «\\[auto]»...)? Se ve a
    través de invisibles, ancho completo, mayúsculas, espacios, acentos, versalitas y letras de otros alfabetos que
    se dibujan igual. Es deliberadamente amplio: «[autobús]» también se rechaza."""
    return _RE_MARCA.search(_normalizar_para_marca(texto)) is not None


_APERTURAS = "[【⁅"
_CIERRES = "]】⁆"
_LARGO_MAX_MARCA = 12  # «[ auto ]» con espacios e invisibles cabe de sobra; más largo ya no es la marca


def _marca_al_principio(texto: str) -> tuple[str, int]:
    """Mira si `texto` EMPIEZA por la marca reservada. Devuelve ("si", fin) con el índice donde acaba (cierre y espacios
    incluidos), ("no", 0) o ("quizas", 0) si aún no hay letras suficientes para saberlo (streaming troceado)."""
    i = 0
    while i < len(texto) and (texto[i].isspace() or unicodedata.category(texto[i]) == "Cf"):
        i += 1
    if i < len(texto) and texto[i] == "\\":
        i += 1
    if i >= len(texto):
        return "quizas", 0
    if texto[i] not in _APERTURAS:
        return "no", 0
    cierre = next((j for j in range(i + 1, min(len(texto), i + 1 + _LARGO_MAX_MARCA)) if texto[j] in _CIERRES), None)
    interior = _normalizar_para_marca(texto[i + 1 : cierre if cierre is not None else len(texto)]).strip()
    if interior and not (interior.startswith("aut") or "aut".startswith(interior)):
        return "no", 0
    if cierre is None:
        return ("quizas", 0) if len(texto) - i <= _LARGO_MAX_MARCA else ("no", 0)
    if not interior.startswith("aut"):
        return "no", 0
    fin = cierre + 1
    while fin < len(texto) and (texto[fin].isspace() or unicodedata.category(texto[fin]) == "Cf"):
        fin += 1
    return "si", fin


def quitar_marca_inicial(texto: str) -> str:
    """Quita de la SALIDA del modelo el prefijo «[auto]» (y sus variantes) que imita de los avisos del servidor,
    también repetido («[auto] [auto] Hola»). Solo mira el principio: en medio del texto no toca nada."""
    while True:
        estado, fin = _marca_al_principio(texto)
        if estado != "si":
            return texto
        texto = texto[fin:]


class FiltroMarcaInicial:
    """Versión para streaming de `quitar_marca_inicial`: retiene los primeros trozos solo mientras puedan ser el
    comienzo de la marca; en cuanto se sabe que no lo es, deja pasar todo sin más retraso."""

    def __init__(self) -> None:
        self._buffer = ""
        self._decidido = False

    def alimentar(self, trozo: str) -> str:
        if self._decidido:
            return trozo
        self._buffer += trozo
        while True:
            estado, fin = _marca_al_principio(self._buffer)
            if estado == "si":
                self._buffer = self._buffer[fin:]
                if not self._buffer:
                    return ""  # puede venir otra marca pegada: se sigue sin decidir
                continue
            if estado == "quizas":
                return ""
            self._decidido = True
            salida, self._buffer = self._buffer, ""
            return salida

    def terminar(self) -> str:
        """Fin del stream: lo retenido (un «[» suelto, p. ej.) ya no puede ser la marca completa."""
        salida, self._buffer = quitar_marca_inicial(self._buffer), ""
        self._decidido = True
        return salida


def validar_mensaje(texto: str, presupuesto: PresupuestoUso) -> str:
    texto = quitar_invisibles(texto).strip()
    if not texto:
        raise ErrorDeValidacion("Escribe un mensaje.")
    if contiene_marca_automatica(texto):
        raise ErrorDeValidacion("El mensaje no puede contener «[auto]»: es una marca reservada del sistema.")
    if len(texto) > presupuesto.max_caracteres_mensaje:
        raise MensajeDemasiadoLargo(
            f"El mensaje es demasiado largo ({len(texto)} caracteres; máximo {presupuesto.max_caracteres_mensaje}). Resúmelo."
        )
    return texto


def segundos_hasta_medianoche(ahora: datetime) -> int:
    manana = (ahora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((manana - ahora).total_seconds()))


def comprobar_cuota_diaria(tokens_hoy: int, presupuesto: PresupuestoUso, ahora: datetime) -> None:
    if tokens_hoy >= presupuesto.tokens_por_dia:
        raise LimiteDeTokensExcedido(
            f"Has agotado tu uso diario del asistente ({presupuesto.tokens_por_dia:,} tokens). Se renueva a medianoche."
            .replace(",", "."),
            reintentar_en=segundos_hasta_medianoche(ahora),
        )
