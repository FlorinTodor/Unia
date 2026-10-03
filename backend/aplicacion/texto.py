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
