"""Tratamiento de texto puro: limpieza de la salida del modelo y preparación para voz."""
import re

from num2words import num2words

# caracteres unicode de ancho cero que los modelos cuelan a veces en el texto
_RE_INVISIBLES = re.compile("[​‌‍⁠﻿]")

# los sintetizadores leen los números dígito a dígito, así que se convierten a palabras antes
_RE_IMPORTE = re.compile(r"(?P<entero>\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,(?P<dec>\d{1,2}))?\s*€")
_RE_NUMERO = re.compile(r"\d+")


def limpiar_invisibles(texto: str) -> str:
    return _RE_INVISIBLES.sub("", texto)


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
