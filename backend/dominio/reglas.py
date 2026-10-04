"""Reglas de negocio puras: sin base de datos, sin red, sin framework."""
import math
import re
import unicodedata
from dataclasses import replace
from datetime import datetime
from urllib.parse import urlsplit

from .errores import (
    ConsultaNoPermitida,
    ErrorDeValidacion,
    ImporteInvalido,
    LimiteBizumExcedido,
    LimiteDiarioExcedido,
    SaldoInsuficiente,
    TarjetaAmbigua,
    TarjetaNoEncontrada,
    TarjetaYaActiva,
    TarjetaYaBloqueada,
)
from .modelos import Contacto, Tarjeta
from .uso import contiene_marca_automatica, quitar_invisibles, sustituir_controles

TOPE_BIZUM = 1000.0  # € por operación
TOPE_DIARIO_BIZUM = 1500.0  # € por cliente y día
UMBRAL_IMPORTE_ALTO = 300.0  # a partir de aquí se avisa al cliente en la confirmación
LIMITE_FILAS_CONSULTA = 60

_PALABRAS_PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|pragma|create|replace|vacuum|reindex)\b",
    re.IGNORECASE,
)


def euros_redondos(importe: float) -> str:
    """1000.0 → «1.000 €» (para topes, sin decimales)."""
    return f"{importe:,.0f}".replace(",", ".") + " €"


def validar_importe_bizum(importe: float) -> float:
    """Comprueba el importe de un Bizum y lo devuelve redondeado a céntimos."""
    if not math.isfinite(importe) or importe <= 0:  # NaN e infinito se saltan las comparaciones con los topes
        raise ImporteInvalido("El importe debe ser un número mayor que 0.")
    if importe > TOPE_BIZUM:
        raise LimiteBizumExcedido(f"Bizum permite un máximo de {euros_redondos(TOPE_BIZUM)} por operación.")
    redondeado = round(importe, 2)
    if redondeado <= 0:  # 0,001 € pasa «> 0» pero se redondea a 0 y se registraría un Bizum de 0,00 €
        raise ImporteInvalido("El importe debe ser de al menos 0,01 €.")
    return redondeado


MAX_CARACTERES_CONCEPTO = 140


def validar_concepto(concepto: str) -> str:
    """Concepto de un Bizum: ≤140 caracteres y sin la marca reservada «[auto]» (el modelo lo manda sin pasar por el esquema HTTP)."""
    # un salto de línea en el concepto saldría en el SMS y en los comprobantes como si fuera otra línea del sistema
    concepto = sustituir_controles(quitar_invisibles(concepto)).strip()
    if len(concepto) > MAX_CARACTERES_CONCEPTO:
        raise ErrorDeValidacion(f"El concepto no puede pasar de {MAX_CARACTERES_CONCEPTO} caracteres.")
    if contiene_marca_automatica(concepto):
        raise ErrorDeValidacion("El concepto no puede contener «[auto]»: es una marca reservada del sistema.")
    return concepto


HOSTS_LOCALES = frozenset({"127.0.0.1", "::1", "localhost"})


def validar_url_ollama(url: str, permitidos: frozenset[str] = frozenset()) -> str:
    """La IA local solo puede estar en esta máquina (o en un host de la lista blanca del .env).

    Sin esta regla, quien tenga acceso a los ajustes podría hacer que el servidor consulte cualquier URL (SSRF).
    """
    try:
        partes = urlsplit(url)
        host = (partes.hostname or "").lower()
        partes.port  # noqa: B018 — lanza ValueError si el puerto no es válido
    except ValueError as e:
        raise ErrorDeValidacion("La URL de Ollama no es válida.") from e
    if partes.scheme not in ("http", "https") or partes.username or partes.password:
        raise ErrorDeValidacion("La URL de Ollama debe ser http(s) sin usuario ni contraseña.")
    if host not in HOSTS_LOCALES and host not in {h.lower() for h in permitidos}:
        raise ErrorDeValidacion(
            "Ollama solo puede estar en esta máquina (localhost, 127.0.0.1 o ::1). "
            "Para otro equipo, el administrador del servidor debe añadirlo a OLLAMA_HOSTS_PERMITIDOS."
        )
    return url


def euros(importe: float) -> str:
    """1234.5 → «1.234,50 €»."""
    return f"{importe:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def validar_tope_diario(enviado_hoy: float, importe: float) -> None:
    if enviado_hoy + importe > TOPE_DIARIO_BIZUM:
        restante = max(TOPE_DIARIO_BIZUM - enviado_hoy, 0)
        raise LimiteDiarioExcedido(
            f"Superarías el límite diario de Bizum ({euros(TOPE_DIARIO_BIZUM)}). "
            f"Hoy aún puedes enviar {euros(restante)}."
        )


def alertas_bizum(importe: float, envios_previos_al_destinatario: int) -> tuple[str, ...]:
    """Avisos que se muestran al cliente junto al código (no bloquean la operación)."""
    alertas = []
    if envios_previos_al_destinatario == 0:
        alertas.append("Es la primera vez que envías un Bizum a este contacto.")
    if importe >= UMBRAL_IMPORTE_ALTO:
        alertas.append(f"Importe alto: {euros(importe)}.")
    return tuple(alertas)


def validar_saldo_suficiente(saldo: float, importe: float) -> None:
    if saldo < importe:
        raise SaldoInsuficiente(f"Saldo insuficiente ({euros(saldo)}) para enviar {euros(importe)}.")


def validar_consulta_solo_lectura(sql: str) -> str:
    """Valida el SQL que escribe el LLM y lo devuelve limpio.

    Primera barrera (lista blanca de forma + lista negra de palabras). La segunda
    es del adaptador: abre la base de datos en modo solo lectura.
    """
    limpia = sql.strip().rstrip(";").strip()
    if ";" in limpia:
        raise ConsultaNoPermitida("Solo se permite una única sentencia SQL.")
    if not limpia.lower().startswith(("select", "with")):
        raise ConsultaNoPermitida("Solo se permiten consultas SELECT.")
    if _PALABRAS_PROHIBIDAS.search(limpia):
        raise ConsultaNoPermitida("La consulta contiene palabras no permitidas.")
    return limpia


CONCEPTO_POR_DEFECTO = "Bizum"


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos ni signos, espacios simples: «Mamá!» y «mama» son lo mismo."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9ñ]+", " ", sin_acentos.casefold()).split())


def _raiz(palabra: str) -> str:
    """Quita un plural sencillo («danis» → «dani», «carmenes» → «carmen») para comparar."""
    if len(palabra) > 4 and palabra.endswith("es"):
        return palabra[:-2]
    return palabra[:-1] if len(palabra) > 3 and palabra.endswith("s") else palabra


def buscar_contactos(contactos: list[Contacto], consulta: str) -> list[Contacto]:
    """Contactos que encajan con lo que escribió el usuario (el servidor decide, no el modelo).

    Por teléfono exacto; si no, por nombre: exacto, luego palabra a palabra («dani» → «Dani Ortega») y, como último
    recurso, trozo suelto. Devuelve más de uno solo si de verdad hay varios candidatos."""
    cifras = re.sub(r"\D", "", consulta)
    if len(cifras) >= 6:
        return [c for c in contactos if re.sub(r"\D", "", c.telefono).endswith(cifras)]
    q = _normalizar(consulta)
    if not q:
        return []
    exactos = [c for c in contactos if _normalizar(c.nombre) == q]
    if exactos:
        return exactos
    raices_q = [_raiz(p) for p in q.split()]
    por_palabras = [
        c for c in contactos
        if all(any(_raiz(n).startswith(r) for n in _normalizar(c.nombre).split()) for r in raices_q)
    ]
    if por_palabras:
        return por_palabras
    return [c for c in contactos if q in _normalizar(c.nombre)]


def concepto_dicho_por_el_usuario(concepto: str, lo_que_dijo: str) -> str:
    """El concepto solo vale si lo dijo el usuario (todas sus palabras aparecen en lo que escribió): un modelo pequeño
    inventaba «Pago amigo». Si no, se devuelve vacío y se usará el concepto neutro."""
    palabras = _normalizar(concepto).split()
    dicho = set(_normalizar(lo_que_dijo).split())
    return concepto if palabras and all(p in dicho for p in palabras) else ""


# ------------------------------------------------------------------ tarjetas

_MARCAS_CONOCIDAS = {"visa": "Visa", "mastercard": "Mastercard", "maestro": "Maestro"}
_TIPOS_CONOCIDOS = {"debito": "débito", "credito": "crédito", "prepago": "prepago"}


def _pedido_de_tarjeta(tarjetas: list[Tarjeta], consulta: str) -> tuple[list[str], set[str], set[str]]:
    """Lo que el usuario pidió: cifras, marcas y tipos (conocidos o que tenga, aunque no los tenga: pedir una
    Mastercard a quien solo tiene Visa no debe equivaler a «cualquiera»)."""
    palabras = set(_normalizar(consulta).split())
    cifras = re.findall(r"\d{4}", re.sub(r"(?<=\d)[\s•*.-]+(?=\d)", "", consulta))
    marcas = ({t.marca.casefold() for t in tarjetas} | set(_MARCAS_CONOCIDAS)) & palabras
    tipos = ({_normalizar(t.tipo) for t in tarjetas} | set(_TIPOS_CONOCIDOS)) & palabras
    return cifras, marcas, tipos


def buscar_tarjetas(tarjetas: list[Tarjeta], consulta: str) -> list[Tarjeta]:
    """Tarjetas que encajan con lo que dijo el usuario: 4 últimos dígitos, marca («visa») y/o tipo («débito»).

    Las palabras que no discriminan («mi», «tarjeta», «perdida»…) se ignoran: sin ningún dato, encajan todas. Si pide
    una marca o un tipo que no tiene, no encaja ninguna."""
    cifras, marcas, tipos = _pedido_de_tarjeta(tarjetas, consulta)
    return [
        t for t in tarjetas
        if (not cifras or t.ultimos4 in cifras)
        and (not marcas or t.marca.casefold() in marcas)
        and (not tipos or _normalizar(t.tipo) in tipos)
    ]


def _descripcion_pedida(tarjetas: list[Tarjeta], consulta: str) -> str:
    """«Mastercard crédito» a partir de lo que se reconoce en la consulta; nunca el texto libre (podría ser un número)."""
    _, marcas, tipos = _pedido_de_tarjeta(tarjetas, consulta)
    nombres = {t.marca.casefold(): t.marca for t in tarjetas} | _MARCAS_CONOCIDAS
    tipos_ = {_normalizar(t.tipo): t.tipo for t in tarjetas} | _TIPOS_CONOCIDOS
    return " ".join([*(nombres[m] for m in sorted(marcas)), *(tipos_[t] for t in sorted(tipos))])


def elegir_tarjeta(tarjetas: list[Tarjeta], consulta: str, *, para_bloquear: bool) -> Tarjeta:
    """La tarjeta sobre la que actuar (el servidor decide, no el modelo).

    Solo cuentan las que pueden cambiar de estado (activas si se bloquea, bloqueadas si se desbloquea): si el cliente
    solo tiene una candidata y dice «mi tarjeta», es esa. Varias → `TarjetaAmbigua`; ninguna que encaje →
    `TarjetaNoEncontrada`; las que encajan ya están en el estado pedido → `TarjetaYaBloqueada` / `TarjetaYaActiva`."""
    if not tarjetas:
        raise TarjetaNoEncontrada("No tienes ninguna tarjeta asociada a tu cuenta.")
    encajan = buscar_tarjetas(tarjetas, consulta)
    if not encajan:
        pedida = _descripcion_pedida(tarjetas, consulta)
        raise TarjetaNoEncontrada(
            f"No encuentro una tarjeta {pedida} entre las tuyas." if pedida else "No encuentro ninguna tarjeta que encaje con lo que me has dicho.",
            tarjetas_disponibles=[t.etiqueta for t in tarjetas],
        )
    aptas = [t for t in encajan if t.bloqueada != para_bloquear]
    if len(aptas) == 1:
        return aptas[0]
    if aptas:
        raise TarjetaAmbigua(
            "Tienes varias tarjetas que encajan: pregunta a cuál se refiere.",
            tuple(aptas), tarjetas_disponibles=[t.etiqueta for t in aptas],
        )
    if para_bloquear:
        raise TarjetaYaBloqueada(_ya_en_estado(encajan, "bloqueada"), tuple(encajan))
    raise TarjetaYaActiva(_ya_en_estado(encajan, "activa"), tuple(encajan))


def _ya_en_estado(tarjetas: list[Tarjeta], estado: str) -> str:
    if len(tarjetas) == 1:
        return f"Tu tarjeta {tarjetas[0].etiqueta} ya estaba {estado}."
    return f"Tus tarjetas ya estaban {estado}s."


def bloquear_tarjeta(tarjeta: Tarjeta, ahora: datetime) -> Tarjeta:
    if tarjeta.bloqueada:
        raise TarjetaYaBloqueada(_ya_en_estado([tarjeta], "bloqueada"), (tarjeta,))
    return replace(tarjeta, bloqueada=True, bloqueada_el=ahora)


def desbloquear_tarjeta(tarjeta: Tarjeta) -> Tarjeta:
    if not tarjeta.bloqueada:
        raise TarjetaYaActiva(_ya_en_estado([tarjeta], "activa"), (tarjeta,))
    return replace(tarjeta, bloqueada=False, bloqueada_el=None)
