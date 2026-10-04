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


_TARJETA = r"(?:tarjetas?|visa|mastercard)"
# solo se analiza el principio del mensaje: acota el coste de las expresiones regulares (un mensaje de 20.000 caracteres
# no debe tardar segundos) y una orden real de bloqueo cabe de sobra en 500
_MAX_ANALIZADO = 500
_DET = r"(?:(?:mi|mis|la|las|el|una?|todas\s+mis)\s+)?"
# primera persona en tiempo actual o perfecto, con la tarjeta a pocas palabras del verbo (3 como mucho entre medias)
_RE_PERDIDA_O_ROBO = re.compile(
    r"\b(?:he\s+perdido|perd[ií]|me\s+(?:han\s+|has\s+)?(?:robad\w+|clonad\w+)|me\s+(?:robaron|clonaron)|extravi[eé])"
    rf"(?:[\s,]+\w+){{0,3}}?[\s,]+{_DET}{_TARJETA}\b"
    rf"|\bno\s+encuentro\s+(?:mi|la)\s+{_TARJETA}\b",
    re.IGNORECASE,
)
# imperativo («bloquea(me)», «bloquéala», «congela») o «quiero bloquear»; el infinitivo suelto («bloquear») no cuenta
_ORDEN = r"(?:bloqu[eé]a(?:me|la|lo|las)?|cong[eé]la(?:me|la|lo|las)?|quiero\s+bloquear(?:me|la|lo)?)"
_RE_ORDEN_BLOQUEO = re.compile(
    rf"\b{_ORDEN}\b(?:[\s,]+\w+){{0,5}}?[\s,]+{_TARJETA}\b|\b{_TARJETA}\b(?:[\s,]+\w+){{0,3}}?[\s,]+{_ORDEN}\b",
    re.IGNORECASE,
)
# lo que convierte una frase en pregunta, explicación o hipótesis: ahí el servidor NO bloquea
_RE_NO_ES_ORDEN = re.compile(
    r"\bc[oó]mo\b|\bexpl[ií]c\w*|\bse\s+puede\b|\bpuedo\b|\bquiero\s+saber\b|\bqu[eé]\s+pasa\b|\bno\s+s[eé]\b|\bsi\b"
    r"|\bantes\s+de\b|\bdespu[eé]s\s+de\b|\bcu[aá]nto\b|\bpero\b|\bsin\s+bloquear\b"
    r"|\bla\s+(?:he\s+)?encontr\w+|\bya\s+la\s+tengo\b|\bapareci\w+"
    rf"|\b{_TARJETA}\s+no\b|\bno\s+(?:quiero|bloquees|hace\s+falta|he\s+perdido|me\s+(?:han|la))\b"
    r"|\bdesbloque\w*|\breact[ií]v\w*|\bvolver\s+a\s+usar"
    r"|\bact[ií]v(?:a|e|o)(?:me|la|lo)?\b|\bactivar\w*|\bactivad[ao]s?\b",
    re.IGNORECASE,
)
_RE_PREGUNTAS = re.compile(r"¿[^?]*(?:\?|$)|[^.!?¿\n]*\?")
# lo que NO es una orden aunque mencione la pérdida o el bloqueo: otra tarjeta, otra persona, algo aplazado, una
# rectificación, un hecho antiguo o una cita
_OTRAS_TARJETAS = r"sanitaria|sim|regalo|transporte|metro|embarque|gimnasio|fidelidad|puntos|descuento|socio|biblioteca|monedero"
_FAMILIA = (
    r"madre|padre|hermano|hermana|hijo|hija|mujer|marido|esposa|esposo|pareja|novi[oa]|abuel[oa]|t[ií][oa]|prim[oa]|"
    r"suegr[oa]|amig[oa]|jefe|jefa|vecin[oa]|compa[ñn]er[oa]|ni[ñn][oa]|sobrin[oa]|cu[ñn]ad[oa]|yerno|nuera"
)
_RE_NO_ES_ORDEN_DE_ESTE_CLIENTE = re.compile(
    rf"\b{_TARJETA}\s+(?:de|del|para)\s+(?!d[eé]bito\b|cr[eé]dito\b)\w+|\b{_TARJETA}\s+(?:{_OTRAS_TARJETAS})\b"
    rf"|\b(?:mi|su|tu|mis)\s+(?:{_FAMILIA})\b|\b(?:de|del)\s+(?:{_FAMILIA})\b"
    r"|\bcuando\b|\bma[ñn]ana\b|\bluego\b|\bm[aá]s\s+(?:tarde|adelante)\b|\bdespu[eé]s\b|\besta\s+(?:noche|tarde)\b"
    r"|\bera\s+(?:una\s+)?(?:prueba|broma)\b|\bprueba\b|\bno\s+lo\s+hagas\b|\bbroma\b|\bmentira\b"
    r"|\bmejor\s+(?:espera|no|d[eé]jalo)\b|\bd[eé]jalo\b|\bolv[ií]d\w+|\bcancela\w*"
    r"|\ben\s+(?:19\d\d|20[01]\d|202[0-5])\b|\bhace\s+(?:\w+\s+)?(?:a[ñn]os?|meses|tiempo)\b|\bel\s+a[ñn]o\s+pasado\b"
    r"|[:«»\"“”]|\b(?:dice|dijo|dicen|dijeron|escribi[oó]|pone)\b",
    re.IGNORECASE,
)


def pide_bloquear_tarjeta(pregunta: str) -> bool:
    """¿Dice en primera persona que ha perdido la tarjeta o que se la han robado/clonado, o pide bloquearla?

    Estrecho a propósito (el servidor bloquea de verdad si el modelo no lo hace): las preguntas («¿cómo bloqueo mi
    tarjeta?», con o sin signos), las explicaciones, las hipótesis («si…»), los desbloqueos, las negaciones, las
    rectificaciones («pero la encontré») y lo que le pasa a otra persona no cuentan. Las frases que son pregunta se
    descartan y se mira el resto, así que «he perdido la tarjeta. ¿Qué hago?» sí es una orden."""
    pregunta = pregunta[:_MAX_ANALIZADO]
    if _RE_NO_ES_ORDEN.search(pregunta) or _RE_NO_ES_ORDEN_DE_ESTE_CLIENTE.search(pregunta):
        return False
    resto = _RE_PREGUNTAS.sub(" ", pregunta)
    return bool(_RE_PERDIDA_O_ROBO.search(resto) or _RE_ORDEN_BLOQUEO.search(resto))


_RE_HABLA_DE_TARJETAS = re.compile(r"\b(?:tarjeta|visa|mastercard|bloquea\w*|bloquear\w*|bloqu[eé]ala|cong[eé]l\w*)\b|••", re.IGNORECASE)
# datos que solo valen como respuesta a «¿Cuál quieres bloquear?»: 4 dígitos, «débito», «crédito»
_RE_DATO_SUELTO = re.compile(r"\b\d{4}\b|\b(?:d[eé]bito|cr[eé]dito)\b", re.IGNORECASE)
_RE_ACLARACION_DE_TARJETA = re.compile(r"¿[^?]{0,200}\b(?:cu[aá]l(?:es)?|tarjeta)\b[^?]{0,200}\?", re.IGNORECASE)


def es_aclaracion_de_tarjeta(mensaje_del_asistente: str) -> bool:
    """¿El asistente acaba de preguntar a qué tarjeta se refiere («¿Cuál quieres bloquear? Tienes…»)?"""
    return bool(_RE_ACLARACION_DE_TARJETA.search(mensaje_del_asistente[:_MAX_ANALIZADO * 2]))


def habla_de_tarjetas(pregunta: str, tras_aclaracion: bool = False) -> bool:
    """¿La pregunta menciona una tarjeta o un bloqueo? Los 4 dígitos o «débito»/«crédito» sueltos (la respuesta a
    «¿cuál?»: «la de débito», «la 4821») solo cuentan si el asistente acababa de preguntar cuál."""
    pregunta = pregunta[:_MAX_ANALIZADO]
    return bool(_RE_HABLA_DE_TARJETAS.search(pregunta) or (tras_aclaracion and _RE_DATO_SUELTO.search(pregunta)))


_RE_NUMERO_LARGO = re.compile(r"\d(?:[\s\-./_–—•*]{0,3}\d){11,}")


def enmascarar_numeros_largos(texto: str) -> str:
    """Oculta las secuencias de 12 o más dígitos con cualquier separador corriente (espacios, NBSP, puntos, guiones,
    barras…): un número de tarjeta no debe quedar auditado."""
    return _RE_NUMERO_LARGO.sub("[número oculto]", texto)


_RE_ULTIMOS4 = re.compile(r"(?:terminad[ao]|acabad[ao]|acaba|que\s+acaba)\s+en\s+(\d{4})\b|(?<![*•])(?:•{2,}+|\*{2,}+)\s*(\d{4})\b", re.IGNORECASE)
_RE_DUDA_O_NEGACION = re.compile(r"\bno\b|\bni\b|\bsalvo\b|\bexcepto\b|\bmenos\b|\bsi\b|\bo\s+(?:la|el)\b|\bcualquiera\b", re.IGNORECASE)
_RE_MARCA = re.compile(r"\b(visa|mastercard)\b", re.IGNORECASE)
_RE_TIPO = re.compile(r"\b(d[eé]bito|cr[eé]dito)\b", re.IGNORECASE)


def datos_de_tarjeta(pregunta: str) -> str:
    """Solo lo que sirve para elegir tarjeta: últimos 4 dígitos (junto a «terminada en»/«••»), marca y tipo.

    Nunca la frase entera (un año o un importe de 4 cifras no es una tarjeta, y «no la de crédito» no es «la de crédito»).
    Con negación, duda o datos contradictorios devuelve «»: el servidor pregunta cuál en vez de adivinar."""
    pregunta = pregunta[:_MAX_ANALIZADO]
    if _RE_DUDA_O_NEGACION.search(pregunta):
        return ""
    cifras = {a or b for a, b in _RE_ULTIMOS4.findall(pregunta)}
    marcas = {m.casefold() for m in _RE_MARCA.findall(pregunta)}
    tipos = {t.casefold() for t in _RE_TIPO.findall(pregunta)}
    if len(cifras) > 1 or len(marcas) > 1 or len(tipos) > 1:
        return ""
    return " ".join([*marcas, *tipos, *cifras])
