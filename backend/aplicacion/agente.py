"""Agente conversacional: bucle de tool calling con streaming y cadena de fallback.

No conoce ningún SDK: habla con el puerto `ProveedorLLM` y con el `RegistroHerramientas`.
`responder` es un generador de `EventoChat` que el adaptador de entrada reenvía al cliente.
"""
import json
import math
import re
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta

from ..dominio.errores import ErrorNoDisponible
from ..dominio.modelos import Cliente, LlamadaHerramienta, Mensaje
from ..dominio.proveedores import OLLAMA, ModeloRef, nombre_proveedor
from ..dominio.reglas import TOPE_BIZUM, concepto_dicho_por_el_usuario
from ..dominio.uso import MARCA_AUTOMATICA, FiltroMarcaInicial, PresupuestoUso, Uso, quitar_marca_inicial
from .casos_uso.graficos import extraer_grafico_del_texto, sugerir_fuente
from .eventos import Aviso, Delta, EventoChat, Fin, Grafico, HerramientaEnUso, UsoConsumido
from .herramientas.registro import RegistroHerramientas, Riesgo
from .texto import afirma_haber_hecho_un_grafico, datos_de_orden_bizum, importes_sin_respaldo, pide_un_bizum, promete_sin_hacer
from .puertos.infraestructura import Reloj, RepositorioAjustes
from .puertos.llm import (
    ClaveInvalida,
    CuotaAgotada,
    DeltaTexto,
    ErrorProveedor,
    GeneracionFallida,
    LimitePorMinuto,
    ModeloNoEncontrado,
    PeticionHerramientas,
    ProveedorInaccesible,
    ProveedorLLM,
    ProveedorNoUtilizable,
    UsoTokens,
)
from .puertos.uso import RegistroUso

MAX_RONDAS = 6
MAX_REINTENTOS_GENERACION = 2
MAX_ESPERA_SEGUNDOS = 20  # un límite por minuto que se libera antes se espera, en vez de bajar a un modelo peor
MAX_ESPERA_TURNO = 40  # tope de espera acumulada por turno: un gráfico necesita varias rondas y chocaba con el límite cada vez
MINUTOS_SIN_CUOTA_POR_DEFECTO = 15  # si el proveedor no dice cuándo vuelve la cuota
MAX_HORAS_SIN_CUOTA = 6  # tope de lo que se recuerda que un modelo está sin cuota (el proveedor puede pedir días)
MAX_EMPUJONES = 1  # veces por turno que se obliga al modelo a cumplir lo que acaba de prometer
AVISO_CONTINUAR = (
    f"{MARCA_AUTOMATICA} Has dicho que ibas a hacer algo pero no has llamado a ninguna herramienta. "
    "Hazlo ahora: llama a la herramienta que necesitas y responde con el resultado, sin anunciarlo."
)
AVISO_HAZ_EL_BIZUM = (
    f"{MARCA_AUTOMATICA} El usuario ya ha dado destinatario e importe de un Bizum. Llama YA a transferencia_bizum con el "
    "nombre del destinatario tal como lo escribió el usuario y ese importe; no pidas confirmación (la tarjeta con el código "
    "es la confirmación: la herramienta no envía el dinero, solo deja la operación pendiente), no preguntes por el contacto "
    "(el servidor lo busca) y no inventes concepto: pásalo solo si el usuario lo dijo. No escribas la marca [auto] en tu respuesta."
)
MENSAJE_LIMITE_TURNO = (
    "Esta consulta ha alcanzado el límite de uso permitido para una sola pregunta. "
    "Pídemelo de forma más concreta (un periodo o una categoría) y lo intento de nuevo."
)
MENSAJE_LIMITE_DIA_LOCAL = "Has alcanzado el límite diario del modelo local. Se renueva a medianoche."
MENSAJE_LIMITE_DIA = "Has alcanzado tu límite diario de uso del asistente. Se renueva a medianoche."
AVISO_SIN_DATOS = (
    f"{MARCA_AUTOMATICA} Tu respuesta incluye cifras o un gráfico que no salen de ningún resultado de herramienta. "
    "Consulta los datos reales con consultar_movimientos (y genera el gráfico con generar_grafico si lo has "
    "mencionado) y responde solo con lo que devuelvan."
)


AVISO_RESPONDE = (
    f"{MARCA_AUTOMATICA} Tu respuesta ha llegado vacía. Responde ahora al usuario con un texto breve usando "
    "los datos que ya has obtenido."
)


def aviso_haz_el_grafico(pregunta: str) -> str:
    """Empujón cuando se pidió un gráfico y no se ha generado: nombra la herramienta y la fuente adecuada, porque un
    modelo pequeño ignoraba el aviso genérico (incidencia 71)."""
    return (
        f"{MARCA_AUTOMATICA} El usuario ha pedido un gráfico y todavía no lo has generado. Llama AHORA a generar_grafico "
        f'con fuente="{sugerir_fuente(pregunta)}" (y el tipo y el periodo que haya pedido, si los dijo): el servidor '
        "calcula los datos, no hace falta consultar_movimientos ni escribir cifras. Después añade una frase breve."
    )


MENSAJE_RESPUESTA_VACIA = (
    "No he conseguido redactar la respuesta. Inténtalo de nuevo o pídemelo de otra forma "
    "(por ejemplo, indicando el periodo o la categoría)."
)
# Pide un gráfico = VERBO de petición + OBJETO gráfico en la misma pregunta. Con «represent»/«visualiza» sueltos saltaba en
# «¿Cuánto representa el alquiler sobre mis gastos?»; y se descartan las negaciones y las referencias a un gráfico anterior.
_OBJETO_GRAFICO = r"(?:gr[aá]fic[oa]s?|diagramas?|tartas?|barras|pastel|donut|histograma|(?:en|de) l[ií]neas?)"
_VERBO_PETICION = (
    r"(?:haz\w*|hac(?:er|e|iendo)\w*|gener\w*|dib[uú]j\w*|mu[eé]str\w*|ens[eé]ñ\w*|quier\w*|necesit\w*|quisier\w*|gustar\w*|"
    r"pon\w*|cre[ae]\w*|d[aá]m\w*|dar\w*|sac\w*|prep[aá]r\w*|repres[eé]nt\w*|visualiz\w*|tr[aá]z\w*|ver|mirar|ponerlo)"
)
_RE_PIDE_GRAFICO = re.compile(
    rf"\b{_VERBO_PETICION}\b[^.?!]*?\b{_OBJETO_GRAFICO}\b"  # «hazme un gráfico…», «quiero ver mis gastos en una tarta»
    rf"|\ben\s+(?:un|una|forma de|modo)?\s*{_OBJETO_GRAFICO}\b"  # «muéstramelo en un gráfico»
    rf"|^\W*(?:un\s+|el\s+)?{_OBJETO_GRAFICO}\s+de\b",  # «Gráfico de gastos por mes»
    re.IGNORECASE,
)
_RE_NIEGA_GRAFICO = re.compile(
    rf"\b(?:no|sin|ni|nada de)\b\s+(?:me\s+|lo\s+)?(?:\w+\s+){{0,2}}?{_OBJETO_GRAFICO}\b|\b(?:solo|s[oó]lo)\s+(?:en\s+)?texto|\ben\s+texto\b",
    re.IGNORECASE,
)
_RE_GRAFICO_ANTERIOR = re.compile(
    r"\b(?:de antes|anterior|de hace un rato|que (?:me )?(?:has|hiciste|diste|acabas)|(?:ese|este|aquel|tu)\s+gr[aá]fic)",
    re.IGNORECASE,
)
_RE_OTRO_GRAFICO = re.compile(r"\b(?:otro|otra|nuev[oa]|de nuevo|otra vez)\b", re.IGNORECASE)


def explicar_fallo(eslabon: ModeloRef, error: ProveedorNoUtilizable) -> str:
    """Traduce el fallo de un eslabón a un mensaje comprensible para el usuario."""
    nombre = nombre_proveedor(eslabon.proveedor)
    if isinstance(error, ClaveInvalida):
        return f"La clave API de {nombre} no es válida (revísala en ⚙️ Ajustes)."
    if isinstance(error, ModeloNoEncontrado):
        return f"El modelo {eslabon.modelo} ya no existe en {nombre} (elige otro en ⚙️ Ajustes)."
    if isinstance(error, LimitePorMinuto):
        return f"{eslabon.modelo} ha alcanzado su límite por minuto (se libera en unos segundos)."
    if isinstance(error, CuotaAgotada):
        return f"{eslabon.modelo} ha agotado su cuota gratuita por ahora."
    if isinstance(error, ProveedorInaccesible) and eslabon.proveedor == OLLAMA:
        return "La IA local no responde: ¿está Ollama en marcha (`ollama serve`)?"
    return f"{eslabon.modelo} ({nombre}) no está disponible."


class _Consumo:
    """Tokens gastados en el turno en curso y en el día antes de empezarlo."""

    def __init__(self, hoy_al_empezar: int, local_hoy_al_empezar: int = 0):
        self.local_hoy_al_empezar = local_hoy_al_empezar
        self.local = Uso()
        self.hoy_al_empezar = hoy_al_empezar  # solo modelos en la nube: el local (Ollama) es gratis y no cuenta
        self.turno = Uso()
        self.nube = Uso()


MOTIVO_SIN_ORDEN = "El cliente no ha pedido eso en su último mensaje: no se ejecuta."


def _ultima_pregunta(mensajes: list[Mensaje]) -> str:
    """La última pregunta real del usuario (no un aviso [auto])."""
    for m in reversed(mensajes):
        if m.rol == "user" and not (m.contenido or "").startswith(MARCA_AUTOMATICA):
            return m.contenido or ""
    return ""


def _es_aclaracion(texto: str) -> bool:
    """¿La respuesta del modelo es una pregunta de aclaración (termina en «?» o contiene «¿…?»)?"""
    t = texto.strip()
    return t.endswith("?") or bool(re.search(r"¿[^?]*\?", t[:1000]))


def _asistente_antes_de_la_pregunta(mensajes: list[Mensaje]) -> str:
    """Lo último que dijo el asistente antes de la última pregunta real del usuario (para saber si esta responde a un «¿cuál?»)."""
    ultima = next(
        (i for i in range(len(mensajes) - 1, -1, -1)
         if mensajes[i].rol == "user" and not (mensajes[i].contenido or "").startswith(MARCA_AUTOMATICA)),
        None,
    )
    if ultima is None:
        return ""
    for m in reversed(mensajes[:ultima]):
        if m.rol == "assistant" and m.contenido:
            return m.contenido
    return ""


def _sin_concepto_inventado(argumentos_json: str, mensajes: list[Mensaje]) -> str:
    """Quita el concepto del Bizum si no sale de lo que escribió el usuario (el modelo inventaba «Pago amigo»)."""
    try:
        args = json.loads(argumentos_json or "{}")
    except json.JSONDecodeError:
        return argumentos_json
    if not isinstance(args, dict) or not args.get("concepto"):
        return argumentos_json
    dicho = " ".join(
        m.contenido or "" for m in mensajes if m.rol == "user" and not (m.contenido or "").startswith(MARCA_AUTOMATICA)
    )
    args["concepto"] = concepto_dicho_por_el_usuario(str(args["concepto"]), dicho)
    return json.dumps(args, ensure_ascii=False)


def pide_un_grafico(pregunta: str) -> bool:
    if not _RE_PIDE_GRAFICO.search(pregunta) or _RE_NIEGA_GRAFICO.search(pregunta):
        return False
    return not _RE_GRAFICO_ANTERIOR.search(pregunta) or bool(_RE_OTRO_GRAFICO.search(pregunta))


def _pide_grafico(mensajes: list[Mensaje]) -> bool:
    return pide_un_grafico(_ultima_pregunta(mensajes))


class Agente:
    def __init__(
        self,
        llm: ProveedorLLM,
        herramientas: RegistroHerramientas,
        ajustes: RepositorioAjustes,
        registro_uso: RegistroUso,
        presupuesto: PresupuestoUso,
        reloj: Reloj,
        esperar: Callable[[float], None] = time.sleep,
    ):
        self._llm = llm
        self._herramientas = herramientas
        self._ajustes = ajustes
        self._registro_uso = registro_uso
        self._presupuesto = presupuesto
        self._reloj = reloj
        self._esperar = esperar
        self._cerrojo_cuota = threading.Lock()  # los turnos corren en hilos distintos y comparten _sin_cuota
        self._sin_cuota: dict[ModeloRef, datetime] = {}  # modelo → hasta cuándo no merece la pena intentarlo

    def tiene_respaldo_local(self) -> bool:
        """¿Hay un modelo local (gratis) en la cadena? Entonces la cuota de la nube no impide atender."""
        return any(m.proveedor == OLLAMA for m in self._ajustes.cargar().cadena_llm())

    def responder(self, mensajes: list[Mensaje], cliente: Cliente) -> Iterator[EventoChat]:
        """Ejecuta el bucle del agente y, justo antes de la respuesta final, informa del gasto de tokens."""
        hoy = self._reloj.hoy()
        consumo = _Consumo(self._registro_uso.tokens_del_dia(cliente.id, hoy), self._registro_uso.tokens_locales_del_dia(cliente.id, hoy))
        for evento in self._bucle(mensajes, cliente, consumo):
            if isinstance(evento, Fin):
                yield UsoConsumido(consumo.turno.total, consumo.hoy_al_empezar + consumo.nube.total, self._presupuesto.tokens_por_dia)
            yield evento

    def _bucle(self, mensajes: list[Mensaje], cliente: Cliente, consumo: "_Consumo") -> Iterator[EventoChat]:
        """Ejecuta el bucle del agente sobre `mensajes` (se amplía in situ), en nombre de `cliente`.

        Si un eslabón falla (cuota, clave, red) se pasa al siguiente de la cadena y la
        conversación continúa. Los cambios de eslabón y los reintentos NO consumen rondas.
        """
        cadena = self._ajustes.cargar().cadena_llm()
        ahora = self._reloj.ahora()
        # un modelo al que ya se le acabó la cuota del día no se vuelve a intentar hasta que el proveedor la devuelva:
        # cada intento fallido costaba una espera inútil de hasta 20 s
        with self._cerrojo_cuota:
            sin_cuota = dict(self._sin_cuota)
        disponibles = [m for m in cadena if sin_cuota.get(m, ahora) <= ahora]
        if cadena and not disponibles:
            vuelve = min(sin_cuota[m] for m in cadena)
            raise ErrorNoDisponible(
                "Ahora mismo no puedo atenderte: todos los modelos de IA se han quedado sin cuota. "
                f"Vuelve a probar sobre las {vuelve.strftime('%H:%M')}."
            )
        cadena = disponibles
        nube_agotada = consumo.hoy_al_empezar >= self._presupuesto.tokens_por_dia
        local_agotado = consumo.local_hoy_al_empezar >= self._presupuesto.tokens_por_dia_local
        if nube_agotada:
            # cuota diaria de la nube agotada: se sigue atendiendo solo con el modelo local, que es gratis
            cadena = [m for m in cadena if m.proveedor == OLLAMA]
        if local_agotado:
            cadena = [m for m in cadena if m.proveedor != OLLAMA]  # el local ya gastó su tope de hoy
        if (nube_agotada or local_agotado) and not cadena:
            # si la nube también está agotada, lo que el cliente necesita saber es el límite general
            raise ErrorNoDisponible(MENSAJE_LIMITE_DIA if nube_agotada else MENSAJE_LIMITE_DIA_LOCAL)
        if not cadena:
            raise ErrorNoDisponible(
                "No hay ningún motor de IA disponible. Abre ⚙️ Ajustes y añade tu clave de Groq "
                "o activa la IA local (Ollama)."
            )
        posicion = 0
        reintentos_generacion = 0
        rondas = 0
        empujones = 0
        con_herramientas = False  # ¿se ha ejecutado alguna herramienta en este turno?
        con_grafico = False
        grafico_llamado = False  # generar_grafico se llamó (aunque fallara, p. ej. periodo vacío): no se vuelve a empujar
        esperado = 0.0  # segundos esperados en este turno por límites por minuto (tope MAX_ESPERA_TURNO)
        proteccion_ejecutada = False  # solo UNA acción de protección (bloquear una tarjeta) por turno

        while rondas < MAX_RONDAS:
            partes: list[str] = []
            filtro = FiltroMarcaInicial()  # el modelo imita el «[auto]» de los avisos del servidor: no sale al cliente
            llamadas: tuple[LlamadaHerramienta, ...] = ()
            try:
                for evento in self._llm.completar(
                    cadena[posicion], mensajes, self._herramientas.esquemas(), self._presupuesto.max_tokens_respuesta
                ):
                    if isinstance(evento, DeltaTexto):
                        partes.append(evento.texto)
                        if visible := filtro.alimentar(evento.texto):
                            yield Delta(visible)
                    elif isinstance(evento, PeticionHerramientas):
                        llamadas = evento.llamadas
                    elif isinstance(evento, UsoTokens):
                        self._contar(consumo, cliente, cadena[posicion], evento.uso)
            except ProveedorNoUtilizable as e:
                espera = e.espera if isinstance(e, LimitePorMinuto) else None
                if espera is not None and espera <= MAX_ESPERA_SEGUNDOS and esperado + espera + 0.5 <= MAX_ESPERA_TURNO:
                    if not esperado:  # se avisa la primera vez; las siguientes esperas del turno van en silencio
                        yield Aviso(
                            f"{cadena[posicion].modelo} ha alcanzado su límite por minuto. "
                            f"Espero {math.ceil(espera)} s y lo reintento."
                        )
                    esperado += espera + 0.5
                    self._esperar(espera + 0.5)
                    continue
                motivo = explicar_fallo(cadena[posicion], e)
                if isinstance(e, CuotaAgotada) and not isinstance(e, LimitePorMinuto):
                    espera = e.espera if e.espera is not None else MINUTOS_SIN_CUOTA_POR_DEFECTO * 60
                    vuelve = self._reloj.ahora() + timedelta(seconds=min(espera, MAX_HORAS_SIN_CUOTA * 3600))
                    with self._cerrojo_cuota:
                        self._sin_cuota[cadena[posicion]] = vuelve
                    motivo += f" No lo intentaré de nuevo hasta las {vuelve.strftime('%H:%M')}."
                posicion += 1
                if posicion >= len(cadena):
                    raise ErrorNoDisponible(self._mensaje_sin_modelos(cadena[-1], e)) from e
                siguiente = cadena[posicion]
                yield Aviso(f"{motivo} Cambiando a {siguiente.modelo} ({nombre_proveedor(siguiente.proveedor)}).")
                continue
            except GeneracionFallida:
                # fallo esporádico del modelo: se reintenta la ronda en silencio
                reintentos_generacion += 1
                if reintentos_generacion > MAX_REINTENTOS_GENERACION:
                    raise
                continue

            if resto := filtro.terminar():
                yield Delta(resto)
            rondas += 1
            texto = quitar_marca_inicial("".join(partes))  # también lo que se guarda en el historial va sin la marca

            if not llamadas:
                texto, grafico = extraer_grafico_del_texto(texto)  # red de seguridad: gráfico escrito como ```json
                correccion = self._correccion_necesaria(
                    texto, mensajes, con_herramientas, con_grafico or grafico is not None, grafico_llamado
                )
                llamada_del_servidor = self._llamada_del_servidor(correccion, mensajes, texto) if empujones >= MAX_EMPUJONES else None
                if llamada_del_servidor:
                    # tras el empujón el modelo sigue sin llamar a la herramienta: la llama el servidor. Solo crea la
                    # operación PENDIENTE (el OTP sigue siendo imprescindible) o ejecuta lo que es seguro (bloquear una tarjeta)
                    llamadas = (llamada_del_servidor,)
                    texto = ""
                else:
                    if correccion and empujones < MAX_EMPUJONES:
                        empujones += 1
                        if texto.strip():  # un mensaje de asistente vacío lo rechazan algunos proveedores
                            mensajes.append(Mensaje.asistente(texto))
                        mensajes.append(Mensaje.usuario(correccion))
                        continue
                    if grafico:
                        yield grafico
                    if not texto.strip():  # tras el reintento sigue vacía: nunca se cierra el turno sin decir nada
                        texto = "Aquí tienes el gráfico." if (grafico or con_grafico) else MENSAJE_RESPUESTA_VACIA
                    mensajes.append(Mensaje.asistente(texto))
                    yield Fin(texto)
                    return

            limite = self._limite_superado(consumo, cadena[posicion])
            if limite == MENSAJE_LIMITE_DIA:
                # la nube se agotó a mitad de turno: si queda un eslabón local (gratis) se sigue con él
                local = self._siguiente_local(cadena, posicion, consumo)
                if local is not None:
                    posicion = local
                    yield Aviso(f"Has agotado el límite diario de la nube. Continúo con {cadena[posicion].modelo} (local).")
                    limite = None
            if limite:  # el modelo pide otra ronda, pero ya se ha gastado lo permitido: se corta aquí
                mensajes.append(Mensaje.asistente(limite))
                yield Fin(limite)
                return

            mensajes.append(Mensaje.asistente(texto or None, llamadas))
            respuestas_fijas: list[str] = []
            rechazadas = 0
            for llamada in llamadas:
                motivo = self._rechazo_de_proteccion(llamada.nombre, mensajes, proteccion_ejecutada)
                if motivo:
                    # un modelo engañado no encadena bloqueos ni bloquea sin una orden clara del cliente
                    mensajes.append(Mensaje.resultado_herramienta(llamada.id, json.dumps({"ok": False, "error": motivo}, ensure_ascii=False)))
                    if motivo == MOTIVO_SIN_ORDEN and (fijo := self._herramientas.rechazo_final(llamada.nombre)):
                        respuestas_fijas.append(fijo)  # texto fijo del servidor: el modelo no se entera ni puede contradecirlo
                    else:
                        rechazadas += 1
                    continue
                yield HerramientaEnUso(llamada.nombre, self._herramientas.etiqueta(llamada.nombre))
                argumentos = llamada.argumentos
                if llamada.nombre == "transferencia_bizum":
                    argumentos = _sin_concepto_inventado(argumentos, mensajes)
                resultado = self._herramientas.ejecutar(llamada.nombre, argumentos, cliente)
                proteccion_ejecutada = proteccion_ejecutada or self._herramientas.riesgo(llamada.nombre) is Riesgo.PROTECCION
                con_herramientas = True
                grafico_llamado = grafico_llamado or llamada.nombre == "generar_grafico"
                con_grafico = con_grafico or any(isinstance(e, Grafico) for e in resultado.eventos)
                yield from resultado.eventos
                mensajes.append(
                    Mensaje.resultado_herramienta(llamada.id, json.dumps(resultado.datos, ensure_ascii=False))
                )
                if resultado.respuesta_final:
                    respuestas_fijas.append(resultado.respuesta_final)

            # las herramientas ya saben qué decir: no hace falta otra vuelta al modelo, pero solo si lo saben TODAS
            # (si alguna devuelve datos para el modelo, el modelo tiene que verlos)
            if respuestas_fijas and len(respuestas_fijas) == len(llamadas) - rechazadas:
                respuesta_fija = respuestas_fijas[-1]
                if rechazadas:
                    respuesta_fija += " Solo puedo bloquear una tarjeta por petición: dime cuál quieres bloquear ahora si es otra."
                final = f"{texto.strip()}\n\n{respuesta_fija}".strip() if texto.strip() else respuesta_fija
                mensajes.append(Mensaje.asistente(final))
                yield Fin(final)
                return

        yield from self._respuesta_final_sin_herramientas(cadena[posicion], mensajes, cliente, consumo)

    def _rechazo_de_proteccion(self, nombre: str, mensajes: list[Mensaje], ya_ejecutada: bool) -> str | None:
        """Por qué NO se ejecuta una herramienta de protección que pide el modelo (None si puede ejecutarse)."""
        if self._herramientas.riesgo(nombre) is not Riesgo.PROTECCION:
            return None
        if ya_ejecutada:
            return "Ya se ha ejecutado una acción de protección en esta petición: solo se permite una por turno."
        if not self._herramientas.permite(nombre, _ultima_pregunta(mensajes), _asistente_antes_de_la_pregunta(mensajes)):
            return MOTIVO_SIN_ORDEN
        return None

    def _llamada_del_servidor(self, correccion: str | None, mensajes: list[Mensaje], texto: str = "") -> LlamadaHerramienta | None:
        pregunta = _ultima_pregunta(mensajes)
        if correccion == AVISO_HAZ_EL_BIZUM:
            orden = datos_de_orden_bizum(pregunta, TOPE_BIZUM)
            return LlamadaHerramienta("auto-bizum", "transferencia_bizum", json.dumps(orden, ensure_ascii=False)) if orden else None
        directa = self._herramientas.orden_directa(pregunta)
        if directa and _es_aclaracion(texto):
            return None  # el modelo pregunta («¿te refieres a la del gimnasio?»): el servidor no anula una duda razonable
        if directa and correccion == directa.aviso:
            return LlamadaHerramienta(f"auto-{directa.nombre}", directa.nombre, json.dumps(directa.argumentos, ensure_ascii=False))
        return None

    def _correccion_necesaria(
        self, texto: str, mensajes: list[Mensaje], con_herramientas: bool, con_grafico: bool, grafico_llamado: bool = False
    ) -> str | None:
        """Detecta respuestas sin respaldo (el modelo promete y no hace, o inventa cifras o gráficos) o vacías."""
        pide_grafico = not con_grafico and not grafico_llamado and _pide_grafico(mensajes)
        if not con_herramientas and pide_un_bizum(_ultima_pregunta(mensajes), TOPE_BIZUM):
            return AVISO_HAZ_EL_BIZUM  # orden de Bizum completa y válida, y el modelo no ha llamado a la herramienta
        if not con_herramientas and (directa := self._herramientas.orden_directa(_ultima_pregunta(mensajes))):
            return directa.aviso  # orden inequívoca de otra herramienta (p. ej. «he perdido la tarjeta») sin llamarla
        if not texto.strip():
            if pide_grafico:
                return aviso_haz_el_grafico(_ultima_pregunta(mensajes))
            return AVISO_RESPONDE if con_herramientas else None  # sin herramientas y vacía: lo cubre el mensaje fijo
        if promete_sin_hacer(texto):
            return AVISO_CONTINUAR
        if afirma_haber_hecho_un_grafico(texto) and not con_grafico:
            return aviso_haz_el_grafico(_ultima_pregunta(mensajes)) if pide_grafico else AVISO_SIN_DATOS
        if pide_grafico and con_herramientas:  # consultó datos y los vuelca en texto en vez de dibujarlos
            return aviso_haz_el_grafico(_ultima_pregunta(mensajes))
        if not con_herramientas:
            contexto = " ".join(m.contenido or "" for m in mensajes)
            if importes_sin_respaldo(texto, contexto):
                return AVISO_SIN_DATOS
        return None

    @staticmethod
    def _mensaje_sin_modelos(ultimo: ModeloRef, error: ProveedorNoUtilizable) -> str:
        mensaje = (
            "Ahora mismo no puedo atenderte: todos los modelos de IA han alcanzado su límite o no responden. "
            "Espera un minuto e inténtalo de nuevo."
        )
        if ultimo.proveedor == OLLAMA and isinstance(error, ProveedorInaccesible):
            mensaje += " La IA local tampoco responde: ¿está Ollama en marcha (`ollama serve`)?"
        elif ultimo.proveedor == OLLAMA and isinstance(error, ModeloNoEncontrado):
            mensaje += f" Ollama está en marcha pero no tiene el modelo {ultimo.modelo}: ejecuta `ollama pull {ultimo.modelo}`."
        return mensaje

    def _contar(self, consumo: "_Consumo", cliente: Cliente, eslabon: ModeloRef, uso: Uso) -> None:
        consumo.turno += uso
        if eslabon.proveedor != OLLAMA:
            consumo.nube += uso
        else:
            consumo.local += uso
        self._registro_uso.registrar(cliente.id, eslabon.proveedor, eslabon.modelo, uso, self._reloj.ahora())

    def _limite_superado(self, consumo: "_Consumo", eslabon: ModeloRef) -> str | None:
        """Cada tope solo vale para el proveedor que atiende: el de la nube no corta al local ni al revés."""
        if consumo.turno.total >= self._presupuesto.tokens_por_turno:
            return MENSAJE_LIMITE_TURNO
        if eslabon.proveedor == OLLAMA:
            if self._local_agotado(consumo):
                return MENSAJE_LIMITE_DIA_LOCAL
        elif consumo.hoy_al_empezar + consumo.nube.total >= self._presupuesto.tokens_por_dia:
            return MENSAJE_LIMITE_DIA
        return None

    def _local_agotado(self, consumo: "_Consumo") -> bool:
        return consumo.local_hoy_al_empezar + consumo.local.total >= self._presupuesto.tokens_por_dia_local

    def _siguiente_local(self, cadena: list[ModeloRef], posicion: int, consumo: "_Consumo") -> int | None:
        if self._local_agotado(consumo):
            return None
        return next((i for i in range(posicion + 1, len(cadena)) if cadena[i].proveedor == OLLAMA), None)

    def _respuesta_final_sin_herramientas(
        self, eslabon: ModeloRef, mensajes: list[Mensaje], cliente: Cliente, consumo: "_Consumo"
    ) -> Iterator[EventoChat]:
        """Se agotaron las rondas: se fuerza una respuesta SIN herramientas para que el
        usuario reciba al menos un resumen de lo conseguido."""
        partes: list[str] = []
        filtro = FiltroMarcaInicial()
        try:
            for evento in self._llm.completar(eslabon, mensajes, None, self._presupuesto.max_tokens_respuesta):
                if isinstance(evento, DeltaTexto):
                    partes.append(evento.texto)
                    if visible := filtro.alimentar(evento.texto):
                        yield Delta(visible)
                elif isinstance(evento, UsoTokens):
                    self._contar(consumo, cliente, eslabon, evento.uso)
            if resto := filtro.terminar():
                yield Delta(resto)
        except ErrorProveedor:
            partes = []
        texto = quitar_marca_inicial("".join(partes)).strip() or "Lo siento, no he podido completar la operación. ¿Puedes reformularla?"
        mensajes.append(Mensaje.asistente(texto))
        yield Fin(texto)
