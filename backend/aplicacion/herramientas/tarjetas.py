"""Herramientas de tarjetas: consultar, bloquear (sin OTP: es lo seguro) y desbloquear (con OTP, como un Bizum).

Las tres devuelven el texto final (`respuesta_final`) y el evento SSE `tarjeta`: el servidor dice qué ha pasado, el modelo
no tiene que narrarlo (el local es débil) ni puede afirmar que algo se bloqueó o desbloqueó si no es verdad.
"""
import re

from ...dominio.errores import TarjetaAmbigua, TarjetaNoEncontrada, TarjetaYaActiva, TarjetaYaBloqueada
from ...dominio.modelos import Cliente, Tarjeta
from ...dominio.uso import MARCA_AUTOMATICA
from ..casos_uso.tarjetas import BloquearTarjeta, ConsultarTarjetas, SolicitarDesbloqueoTarjeta
from ..eventos import OperacionPorConfirmar, TarjetaMostrada
from ..puertos.llm import EsquemaHerramienta
from ..texto import datos_de_tarjeta, es_aclaracion_de_tarjeta, habla_de_tarjetas, pide_bloquear_tarjeta
from .registro import Herramienta, ResultadoHerramienta, Riesgo

_PARAMETROS = {
    "type": "object",
    "properties": {
        "tarjeta": {
            "type": "string",
            "description": "Cómo la nombró el usuario: últimos 4 dígitos, marca (Visa, Mastercard) o tipo (débito, crédito). "
                           "OMÍTELO si solo dijo «mi tarjeta»: el servidor elige si solo hay una posible.",
        },
    },
    "required": [],
}


def _evento(t: Tarjeta) -> TarjetaMostrada:
    return TarjetaMostrada(t.marca, t.tipo, t.ultimos4, t.estado, t.bloqueada_el.isoformat() if t.bloqueada_el else None)


def _datos(t: Tarjeta) -> dict:
    return {"tarjeta": t.etiqueta, "estado": t.estado}


def _consulta(args: dict) -> str:
    return str(args.get("tarjeta") or "").strip()[:200]


AVISO_BLOQUEA_LA_TARJETA = (
    f"{MARCA_AUTOMATICA} El usuario quiere bloquear su tarjeta (la ha perdido, se la han robado o lo ha pedido) y todavía no has "
    "llamado a bloquear_tarjeta. Llámala YA, sin pedir confirmación (bloquear es seguro) y sin decir que está bloqueada antes de "
    "hacerlo. No escribas la marca [auto] en tu respuesta."
)


def _orden_de_bloqueo(pregunta: str) -> dict | None:
    # el servidor extrae solo los datos de la tarjeta (últimos 4 dígitos, marca, tipo), nunca la frase entera; sin datos,
    # elige si solo hay una y, si hay varias, pregunta cuál
    if not pide_bloquear_tarjeta(pregunta):
        return None
    datos = datos_de_tarjeta(pregunta)
    return {"tarjeta": datos} if datos else {}


RECHAZO_SIN_ORDEN_DE_BLOQUEO = (
    'No he bloqueado nada. Si quieres bloquear tu tarjeta, dímelo claro (por ejemplo: "bloquea mi tarjeta").'
)


def _orden_valida(pregunta: str, anterior: str) -> bool:
    """La orden se valida AQUÍ, en el servidor, llame quien llame (el modelo local llama solo ante «a mi madre le han robado la
    tarjeta»): o la última pregunta es una orden clara de bloqueo, o responde a un «¿cuál?» del asistente nombrando la tarjeta."""
    if pide_bloquear_tarjeta(pregunta):
        return True
    return es_aclaracion_de_tarjeta(anterior) and habla_de_tarjetas(pregunta, tras_aclaracion=True) and not _orden_negada(pregunta)


def _orden_negada(pregunta: str) -> bool:
    # «no, la de crédito no»: la respuesta a un «¿cuál?» con negación o duda no elige tarjeta
    return datos_de_tarjeta(pregunta) == "" and bool(re.search(r"\bno\b|\bni\b|\bsi\b", pregunta[:500], re.IGNORECASE))


def _listado(tarjetas: list[Tarjeta]) -> str:
    return ", ".join(f"{t.etiqueta} ({t.estado})" for t in tarjetas)


def _no_encontrada(e: TarjetaNoEncontrada) -> ResultadoHerramienta:
    disponibles = e.datos.get("tarjetas_disponibles")
    extra = f" Tus tarjetas: {', '.join(disponibles)}." if disponibles else ""
    # el mensaje del dominio no repite lo que escribió el cliente (podría ser un número de tarjeta entero)
    return ResultadoHerramienta({"ok": False, "error": e.mensaje, **e.datos}, respuesta_final=f"{e.mensaje}{extra}")


def crear(consultar: ConsultarTarjetas, bloquear: BloquearTarjeta, solicitar_desbloqueo: SolicitarDesbloqueoTarjeta) -> list[Herramienta]:
    def ejecutar_consulta(_args: dict, cliente: Cliente) -> ResultadoHerramienta:
        tarjetas = consultar(cliente)
        if not tarjetas:
            return ResultadoHerramienta({"tarjetas": []}, respuesta_final="No tienes tarjetas asociadas a tu cuenta.")
        return ResultadoHerramienta(
            {"tarjetas": [_datos(t) for t in tarjetas]},
            respuesta_final=f"Estas son tus tarjetas: {_listado(tarjetas)}.",
            eventos=tuple(_evento(t) for t in tarjetas),
        )

    def ejecutar_bloqueo(args: dict, cliente: Cliente) -> ResultadoHerramienta:
        try:
            t = bloquear(cliente, _consulta(args))
        except TarjetaYaBloqueada as e:  # no es un fallo: se dice claro y se enseña cómo está
            return ResultadoHerramienta(
                {"ok": True, "estado": "sin_cambios", "mensaje": e.mensaje}, respuesta_final=e.mensaje,
                eventos=tuple(_evento(t) for t in e.tarjetas),
            )
        except TarjetaAmbigua as e:  # el servidor pregunta; no se adivina cuál bloquear
            return ResultadoHerramienta(
                {"ok": False, "error": e.mensaje, **e.datos},
                respuesta_final=f"¿Cuál quieres bloquear? Tienes {_listado(list(e.tarjetas))}. Dime los últimos 4 dígitos, la marca o si es de débito o crédito.",
                eventos=tuple(_evento(t) for t in e.tarjetas),
            )
        except TarjetaNoEncontrada as e:
            return _no_encontrada(e)
        return ResultadoHerramienta(
            {"ok": True, "estado": "bloqueada", **_datos(t)},
            respuesta_final=(
                f"Listo, he bloqueado tu tarjeta {t.etiqueta}: nadie podrá usarla. "
                "Para volver a activarla te pediré confirmarlo con un código."
            ),
            eventos=(_evento(t),),
        )

    def ejecutar_desbloqueo(args: dict, cliente: Cliente) -> ResultadoHerramienta:
        try:
            op = solicitar_desbloqueo(cliente, _consulta(args))
        except TarjetaYaActiva as e:
            return ResultadoHerramienta(
                {"ok": True, "estado": "sin_cambios", "mensaje": e.mensaje}, respuesta_final=e.mensaje,
                eventos=tuple(_evento(t) for t in e.tarjetas),
            )
        except TarjetaAmbigua as e:
            return ResultadoHerramienta(
                {"ok": False, "error": e.mensaje, **e.datos},
                respuesta_final=f"¿Cuál quieres desbloquear? Tienes bloqueadas {_listado(list(e.tarjetas))}.",
                eventos=tuple(_evento(t) for t in e.tarjetas),
            )
        except TarjetaNoEncontrada as e:
            return _no_encontrada(e)
        # como en el Bizum: el modelo NO recibe el código ni puede confirmar
        return ResultadoHerramienta(
            {
                "ok": True, "estado": "pendiente_de_confirmacion", "tarjeta": op.destinatario,
                "mensaje": "La tarjeta NO se ha desbloqueado todavía: el cliente debe confirmarlo con el código de su móvil en la tarjeta de la pantalla.",
            },
            respuesta_final=(
                f"He preparado el desbloqueo de tu tarjeta {op.destinatario}. Confírmalo con el código que te hemos enviado "
                "por SMS al móvil, o aprobándolo con tu huella, desde la tarjeta."
            ),
            eventos=(OperacionPorConfirmar(
                op.id, op.destinatario, op.importe, op.concepto, op.alertas, op.caduca.isoformat(), op.tipo.value,
            ),),
        )

    return [
        Herramienta(
            EsquemaHerramienta(
                "consultar_tarjetas",
                "Lista las tarjetas del cliente (marca, tipo, últimos 4 dígitos y si están activas o bloqueadas).",
                {"type": "object", "properties": {}, "required": []},
            ),
            ejecutar_consulta, "Consultando tus tarjetas…",
        ),
        Herramienta(
            EsquemaHerramienta(
                "bloquear_tarjeta",
                "Bloquea una tarjeta AL INSTANTE (pérdida, robo, sospecha de fraude). No pide confirmación: bloquear es "
                "siempre seguro. Llámala en cuanto el usuario lo pida o diga que la ha perdido, sin preguntar antes. "
                "Si hay varias tarjetas posibles el servidor lo detecta y pregunta cuál.",
                _PARAMETROS,
            ),
            ejecutar_bloqueo, "Bloqueando la tarjeta…", Riesgo.PROTECCION,
            orden_directa=_orden_de_bloqueo, aviso_orden=AVISO_BLOQUEA_LA_TARJETA, pregunta_valida=_orden_valida,
            rechazo_final=RECHAZO_SIN_ORDEN_DE_BLOQUEO,
        ),
        Herramienta(
            EsquemaHerramienta(
                "desbloquear_tarjeta",
                "Pide desbloquear una tarjeta bloqueada. NO la desbloquea: deja una operación pendiente que el cliente "
                "confirma con un código OTP en la tarjeta de la pantalla. Llámala en cuanto lo pida, sin preguntar antes.",
                _PARAMETROS,
            ),
            ejecutar_desbloqueo, "Preparando el desbloqueo…", Riesgo.ESCRITURA,
        ),
    ]
