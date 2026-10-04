"""Tratamiento de texto puro: limpieza de la salida del modelo y preparación para voz."""
import re

from num2words import num2words

from ..dominio.uso import quitar_invisibles

# los sintetizadores leen los números dígito a dígito, así que se convierten a palabras antes
_RE_IMPORTE = re.compile(r"(?P<entero>\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,(?P<dec>\d{1,2}))?\s*€")
_RE_NUMERO = re.compile(r"\d+")


def limpiar_invisibles(texto: str) -> str:
    """Quita los caracteres de formato (Unicode Cf: ancho cero, U+00AD...) que los modelos cuelan o que disfrazan marcas."""
    return quitar_invisibles(texto)


def _a_palabras_antes_de_sustantivo(n: int) -> str:
    # «veintiuno céntimos» → «veintiún céntimos»; «treinta y uno» → «treinta y un»
    palabras = num2words(n, lang="es")
    if palabras.endswith("uno"):
        palabras = palabras[:-3] + "ún" if palabras.endswith("veintiuno") else palabras[:-1]
    return palabras


def _importe_a_palabras(m: re.Match) -> str:
    entero = int(re.sub(r"[.\s]", "", m.group("entero")))
    frase = "un euro" if entero == 1 else _a_palabras_antes_de_sustantivo(entero) + " euros"
    centimos = int(m.group("dec") or 0)
    if centimos:
        frase += " con " + ("un céntimo" if centimos == 1 else _a_palabras_antes_de_sustantivo(centimos) + " céntimos")
    return frase


def _numero_a_palabras(m: re.Match) -> str:
    # los números largos (teléfonos, IBAN) se dejan tal cual: dígito a dígito
    if len(m.group()) > 7:
        return m.group()
    return num2words(int(m.group()), lang="es")


def normalizar_para_voz(texto: str) -> str:
    texto = _RE_IMPORTE.sub(_importe_a_palabras, texto)
    return _RE_NUMERO.sub(_numero_a_palabras, texto)


_RE_PROMESA = re.compile(r"\b(voy a|vamos a|déjame|dejame|permíteme|un momento|enseguida)\b", re.IGNORECASE)


def promete_sin_hacer(texto: str) -> bool:
    """¿La respuesta termina anunciando algo que aún no ha hecho («Voy a generar… Un momento…»)?

    Los modelos pequeños a veces cierran el turno así, sin llamar a la herramienta: el usuario
    se queda esperando. Solo se mira la última frase y se ignoran las preguntas.
    """
    t = texto.strip()
    if not t or t.endswith("?"):
        return False
    ultima = re.split(r"(?<=[.!…])\s+", t)[-1]
    return bool(_RE_PROMESA.search(ultima))


_RE_ORDEN_BIZUM = re.compile(
    r"^(?!.*\?)"  # una pregunta («¿cuánto he enviado por Bizum?») no es una orden
    r"\W*(?:\w+\W+){0,3}?(?:env[ií]a(?:me|le)?|enviar(?:le|me)?|m[aá]nda(?:me|le)?|mandar(?:le|me)?|haz(?:me|le)?|hacer)\b"
    r"(?=.*\bbizum\b)(?=.*\b(?:a|para)\s+\w{2,})",
    re.IGNORECASE | re.DOTALL,
)
# «mándale 5 a dani»: sin la palabra Bizum solo vale con la forma «-le» (al destinatario) y el importe seguido de «a/para»
_RE_ORDEN_LE = re.compile(
    r"^(?!.*\?)\W*(?:\w+\W+){0,2}?(?:env[ií]ale|m[aá]ndale|enviarle|mandarle)\b(?=.*\d)(?=.*\b(?:a|para)\s+\w{2,})",
    re.IGNORECASE | re.DOTALL,
)
_RE_ORDEN_SIN_VERBO = re.compile(r"^(?!.*\?)\W*(?:un\s+)?bizum\s+de\s+\d.*\b(?:a|para)\s+\w{2,}", re.IGNORECASE | re.DOTALL)
_RE_IMPORTE_EUROS = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?\b|eur\b)", re.IGNORECASE)
# sin unidad: «5 a dani», «para dani 5» no; «bizum de 5 a dani» sí. Los números largos (teléfonos) no son importes
_RE_IMPORTE_SIN_UNIDAD = re.compile(r"(?<![\w.,])(\d{1,6}(?:[.,]\d{1,2})?)(?![\w.,]*\d)(?=\s+(?:a|para)\s+\w)", re.IGNORECASE)
_RE_DESTINATARIO = re.compile(
    r"\b(?:a|para)\s+(?!(?:mi|mis|tu|su)\b)([^\d.,;:!¿?€]{2,40}?)(?=\s+(?:con|de concepto|por concepto|concepto|por|que|y)\b|[.,;:!]|\s*$)",
    re.IGNORECASE,
)
_RE_CONCEPTO = re.compile(r"\bconcepto\s*[:«\"']?\s*([^.,;!?»\"']{1,60})", re.IGNORECASE)
_RE_DIVISA_AJENA = re.compile(r"d[oó]lar|usd|libras?|\$", re.IGNORECASE)


def _importe_de_la_orden(pregunta: str, tope: float) -> float | None:
    """El único importe de la orden (en euros o, si la orden es inequívoca, sin unidad) y dentro del tope."""
    if not any(r.search(pregunta) for r in (_RE_ORDEN_BIZUM, _RE_ORDEN_LE, _RE_ORDEN_SIN_VERBO)) or _RE_DIVISA_AJENA.search(pregunta):
        return None
    if not re.search(r"\bbizum\b", pregunta, re.IGNORECASE) and not _RE_ORDEN_LE.search(pregunta):
        return None
    crudos = _RE_IMPORTE_EUROS.findall(pregunta) or _RE_IMPORTE_SIN_UNIDAD.findall(pregunta)
    importes = {float(m.replace(",", ".")) for m in crudos}
    if len(importes) != 1:  # ninguno o dos distintos: ahí no se adivina
        return None
    importe = importes.pop()
    return importe if 0 < importe <= tope else None


def pide_un_bizum(pregunta: str, tope: float) -> bool:
    """¿Es una ORDEN de Bizum completa y viable (verbo de envío + importe dentro del tope + destinatario)?
    Estrecho a propósito: con un importe en otra divisa, por encima del tope, repetido con otro valor o en forma de
    pregunta no cuenta, porque ahí lo correcto es que el modelo explique en vez de llamar a la herramienta.
    Acepta el importe sin unidad («haz un bizum de 5 a dani», «mándale 5 a dani»)."""
    return _importe_de_la_orden(pregunta, tope) is not None


def datos_de_orden_bizum(pregunta: str, tope: float) -> dict | None:
    """destinatario, importe y (si lo dijo) concepto de una orden inequívoca; None si no hay forma segura de sacarlos."""
    importe = _importe_de_la_orden(pregunta, tope)
    if importe is None:
        return None
    candidatos = [m.group(1).strip() for m in _RE_DESTINATARIO.finditer(pregunta)]
    candidatos = [c for c in candidatos if 0 < len(c.split()) <= 3]
    if not candidatos:
        return None
    datos: dict = {"destinatario": candidatos[0], "importe": importe}
    if concepto := _RE_CONCEPTO.search(pregunta):
        datos["concepto"] = concepto.group(1).strip()
    return datos


_RE_CIFRA = re.compile(r"-?\d+(?:\.\d+)?")


def importes_en(texto: str) -> set[float]:
    """Importes en euros escritos como un humano («1.480,00 €», «96 770,00 €»)."""
    importes = set()
    for m in _RE_IMPORTE.finditer(texto):
        entero = int(re.sub(r"[.\s]", "", m.group("entero")))
        importes.add(round(entero + int((m.group("dec") or "0").ljust(2, "0")) / 100, 2))
    return importes


def cifras_en(texto: str) -> set[float]:
    """Todas las cifras de un texto: importes en euros y números planos de un JSON."""
    return importes_en(texto) | {abs(float(c)) for c in _RE_CIFRA.findall(texto)}


def importes_sin_respaldo(respuesta: str, contexto: str) -> set[float]:
    """Importes de la respuesta que no aparecen en ninguna parte de la conversación."""
    conocidas = cifras_en(contexto)
    return {i for i in importes_en(respuesta) if not any(abs(i - c) <= 0.011 for c in conocidas)}


_RE_AFIRMA_GRAFICO = re.compile(r"\*\*gr[aá]fic[oa][^*]*\*\*|aqu[ií] (tienes|est[aá]) el gr[aá]fic", re.IGNORECASE)


def afirma_haber_hecho_un_grafico(texto: str) -> bool:
    return bool(_RE_AFIRMA_GRAFICO.search(texto))
