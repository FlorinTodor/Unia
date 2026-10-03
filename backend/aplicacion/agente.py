"""Agente conversacional: bucle de tool calling con streaming y cadena de fallback.

No conoce ningún SDK: habla con el puerto `ProveedorLLM` y con el `RegistroHerramientas`.
`responder` es un generador de `EventoChat` que el adaptador de entrada reenvía al cliente.
"""
import json
import math
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta

from ..dominio.errores import ErrorNoDisponible
from ..dominio.modelos import Cliente, LlamadaHerramienta, Mensaje
from ..dominio.proveedores import OLLAMA, ModeloRef, nombre_proveedor
from ..dominio.uso import PresupuestoUso, Uso
from .casos_uso.graficos import extraer_grafico_del_texto
from .eventos import Aviso, Delta, EventoChat, Fin, Grafico, HerramientaEnUso, UsoConsumido
from .herramientas.registro import RegistroHerramientas
from .texto import afirma_haber_hecho_un_grafico, importes_sin_respaldo, promete_sin_hacer
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
MAX_ESPERA_SEGUNDOS = 20
MINUTOS_SIN_CUOTA_POR_DEFECTO = 15  # si el proveedor no dice cuándo vuelve la cuota
MAX_HORAS_SIN_CUOTA = 6  # un límite por minuto que se libera antes se espera, en vez de bajar a un modelo peor
MAX_EMPUJONES = 1  # veces por turno que se obliga al modelo a cumplir lo que acaba de prometer
MARCA_AUTOMATICA = "[auto]"
AVISO_CONTINUAR = (
    f"{MARCA_AUTOMATICA} Has dicho que ibas a hacer algo pero no has llamado a ninguna herramienta. "
    "Hazlo ahora: llama a la herramienta que necesitas y responde con el resultado, sin anunciarlo."
)
MENSAJE_LIMITE_TURNO = (
    "Esta consulta ha alcanzado el límite de uso permitido para una sola pregunta. "
    "Pídemelo de forma más concreta (un periodo o una categoría) y lo intento de nuevo."
)
MENSAJE_LIMITE_DIA = "Has alcanzado tu límite diario de uso del asistente. Se renueva a medianoche."
AVISO_SIN_DATOS = (
    f"{MARCA_AUTOMATICA} Tu respuesta incluye cifras o un gráfico que no salen de ningún resultado de herramienta. "
    "Consulta los datos reales con consultar_movimientos (y genera el gráfico con generar_grafico si lo has "
    "mencionado) y responde solo con lo que devuelvan."
)


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


PROVEEDOR_LOCAL = "ollama"


class _Consumo:
    """Tokens gastados en el turno en curso y en el día antes de empezarlo."""

    def __init__(self, hoy_al_empezar: int):
        self.hoy_al_empezar = hoy_al_empezar  # solo modelos en la nube: el local (Ollama) es gratis y no cuenta
        self.turno = Uso()
        self.nube = Uso()


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
        self._sin_cuota: dict[ModeloRef, datetime] = {}  # modelo → hasta cuándo no merece la pena intentarlo

    def tiene_respaldo_local(self) -> bool:
        """¿Hay un modelo local (gratis) en la cadena? Entonces la cuota de la nube no impide atender."""
        return any(m.proveedor == PROVEEDOR_LOCAL for m in self._ajustes.cargar().cadena_llm())

    def responder(self, mensajes: list[Mensaje], cliente: Cliente) -> Iterator[EventoChat]:
        """Ejecuta el bucle del agente y, justo antes de la respuesta final, informa del gasto de tokens."""
        consumo = _Consumo(self._registro_uso.tokens_del_dia(cliente.id, self._reloj.hoy()))
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
        disponibles = [m for m in cadena if self._sin_cuota.get(m, ahora) <= ahora]
        if cadena and not disponibles:
            vuelve = min(self._sin_cuota[m] for m in cadena)
            raise ErrorNoDisponible(
                "Ahora mismo no puedo atenderte: todos los modelos de IA se han quedado sin cuota. "
                f"Vuelve a probar sobre las {vuelve.strftime('%H:%M')}."
            )
        cadena = disponibles
        if consumo.hoy_al_empezar >= self._presupuesto.tokens_por_dia:
            # cuota diaria de la nube agotada: se sigue atendiendo solo con el modelo local, que es gratis
            cadena = [m for m in cadena if m.proveedor == PROVEEDOR_LOCAL]
            if not cadena:
                raise ErrorNoDisponible(MENSAJE_LIMITE_DIA)
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
        con_espera: set[int] = set()  # posiciones de la cadena a las que ya se esperó una vez

        while rondas < MAX_RONDAS:
            partes: list[str] = []
            llamadas: tuple[LlamadaHerramienta, ...] = ()
            try:
                for evento in self._llm.completar(
                    cadena[posicion], mensajes, self._herramientas.esquemas(), self._presupuesto.max_tokens_respuesta
                ):
                    if isinstance(evento, DeltaTexto):
                        partes.append(evento.texto)
                        yield Delta(evento.texto)
                    elif isinstance(evento, PeticionHerramientas):
                        llamadas = evento.llamadas
                    elif isinstance(evento, UsoTokens):
                        self._contar(consumo, cliente, cadena[posicion], evento.uso)
            except ProveedorNoUtilizable as e:
                espera = e.espera if isinstance(e, LimitePorMinuto) else None
                if espera is not None and espera <= MAX_ESPERA_SEGUNDOS and posicion not in con_espera:
                    con_espera.add(posicion)
                    yield Aviso(
                        f"{cadena[posicion].modelo} ha alcanzado su límite por minuto. "
                        f"Espero {math.ceil(espera)} s y lo reintento."
                    )
                    self._esperar(espera + 0.5)
                    continue
                motivo = explicar_fallo(cadena[posicion], e)
                if isinstance(e, CuotaAgotada) and not isinstance(e, LimitePorMinuto):
                    espera = e.espera if e.espera is not None else MINUTOS_SIN_CUOTA_POR_DEFECTO * 60
                    vuelve = self._reloj.ahora() + timedelta(seconds=min(espera, MAX_HORAS_SIN_CUOTA * 3600))
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

            rondas += 1
            texto = "".join(partes)

            if not llamadas:
                texto, grafico = extraer_grafico_del_texto(texto)  # red de seguridad: gráfico escrito como ```json
                correccion = self._correccion_necesaria(texto, mensajes, con_herramientas, con_grafico or grafico is not None)
                if correccion and empujones < MAX_EMPUJONES:
                    empujones += 1
                    mensajes.append(Mensaje.asistente(texto))
                    mensajes.append(Mensaje.usuario(correccion))
                    continue
                if grafico:
                    yield grafico
                mensajes.append(Mensaje.asistente(texto))
                yield Fin(texto)
                return

            limite = self._limite_superado(consumo)
            if limite:  # el modelo pide otra ronda, pero ya se ha gastado lo permitido: se corta aquí
                mensajes.append(Mensaje.asistente(limite))
                yield Fin(limite)
                return

            mensajes.append(Mensaje.asistente(texto or None, llamadas))
            respuesta_fija = None
            for llamada in llamadas:
                yield HerramientaEnUso(llamada.nombre, self._herramientas.etiqueta(llamada.nombre))
                resultado = self._herramientas.ejecutar(llamada.nombre, llamada.argumentos, cliente)
                con_herramientas = True
                con_grafico = con_grafico or any(isinstance(e, Grafico) for e in resultado.eventos)
                yield from resultado.eventos
                mensajes.append(
                    Mensaje.resultado_herramienta(llamada.id, json.dumps(resultado.datos, ensure_ascii=False))
                )
                respuesta_fija = resultado.respuesta_final or respuesta_fija

            if respuesta_fija:  # la herramienta ya sabe qué decir: no hace falta otra vuelta al modelo
                final = f"{texto.strip()}\n\n{respuesta_fija}".strip() if texto.strip() else respuesta_fija
                mensajes.append(Mensaje.asistente(final))
                yield Fin(final)
                return

        yield from self._respuesta_final_sin_herramientas(cadena[posicion], mensajes, cliente, consumo)

    @staticmethod
    def _correccion_necesaria(texto: str, mensajes: list[Mensaje], con_herramientas: bool, con_grafico: bool) -> str | None:
        """Detecta respuestas sin respaldo (el modelo promete y no hace, o inventa cifras o gráficos)."""
        if promete_sin_hacer(texto):
            return AVISO_CONTINUAR
        if afirma_haber_hecho_un_grafico(texto) and not con_grafico:
            return AVISO_SIN_DATOS
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
        if eslabon.proveedor != PROVEEDOR_LOCAL:
            consumo.nube += uso
        self._registro_uso.registrar(cliente.id, eslabon.proveedor, eslabon.modelo, uso, self._reloj.ahora())

    def _limite_superado(self, consumo: "_Consumo") -> str | None:
        if consumo.turno.total >= self._presupuesto.tokens_por_turno:
            return MENSAJE_LIMITE_TURNO
        if consumo.hoy_al_empezar + consumo.nube.total >= self._presupuesto.tokens_por_dia:
            return MENSAJE_LIMITE_DIA
        return None

    def _respuesta_final_sin_herramientas(
        self, eslabon: ModeloRef, mensajes: list[Mensaje], cliente: Cliente, consumo: "_Consumo"
    ) -> Iterator[EventoChat]:
        """Se agotaron las rondas: se fuerza una respuesta SIN herramientas para que el
        usuario reciba al menos un resumen de lo conseguido."""
        partes: list[str] = []
        try:
            for evento in self._llm.completar(eslabon, mensajes, None, self._presupuesto.max_tokens_respuesta):
                if isinstance(evento, DeltaTexto):
                    partes.append(evento.texto)
                    yield Delta(evento.texto)
                elif isinstance(evento, UsoTokens):
                    self._contar(consumo, cliente, eslabon, evento.uso)
        except ErrorProveedor:
            partes = []
        texto = "".join(partes).strip() or "Lo siento, no he podido completar la operación. ¿Puedes reformularla?"
        mensajes.append(Mensaje.asistente(texto))
        yield Fin(texto)
