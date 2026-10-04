from ...dominio.modelos import Cliente
from ...dominio.reglas import euros
from ..casos_uso.bizum import SolicitarBizum
from ..eventos import OperacionPorConfirmar
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta, Riesgo


def crear(solicitar_bizum: SolicitarBizum) -> Herramienta:
    def ejecutar(args: dict, cliente: Cliente) -> ResultadoHerramienta:
        try:
            importe = float(args.get("importe", 0))
        except (ValueError, TypeError, OverflowError):  # el modelo puede mandar «veinte», una lista o null
            return ResultadoHerramienta({"ok": False, "error": "El importe debe ser un número en euros (p. ej. 25 o 25.50)."})
        operacion = solicitar_bizum(
            cliente,
            str(args.get("destinatario", "")),
            importe,
            str(args.get("concepto") or ""),
        )
        # el LLM NO recibe el código ni puede confirmar: solo sabe que la operación espera al cliente
        return ResultadoHerramienta(
            {
                "ok": True,
                "estado": "pendiente_de_confirmacion",
                "destinatario": operacion.destinatario,
                "importe": operacion.importe,
                "mensaje": (
                    "El Bizum NO se ha enviado todavía. El cliente ha recibido un código en su móvil y debe "
                    "confirmarlo en la tarjeta que ve en pantalla. No pidas ni menciones el código."
                ),
            },
            respuesta_final=(
                f"He preparado el Bizum de {euros(operacion.importe)} a {operacion.destinatario}. "
                "Confírmalo con el código que te hemos enviado por SMS al móvil, o aprobándolo con tu huella, desde la tarjeta."
            ),
            eventos=(
                OperacionPorConfirmar(
                    operacion.id, operacion.destinatario, operacion.importe, operacion.concepto,
                    operacion.alertas, operacion.caduca.isoformat(),
                ),
            ),
        )

    return Herramienta(
        esquema=EsquemaHerramienta(
            "transferencia_bizum",
            "Inicia un Bizum a un contacto. NO lo envía: deja una operación pendiente que el cliente confirma con un "
            "código OTP en la tarjeta. Llámala en cuanto el usuario dé destinatario e importe, sin pedir confirmación "
            "antes: la tarjeta ya es la confirmación. El servidor busca el contacto por el nombre tal cual lo escribió.",
            {
                "type": "object",
                "properties": {
                    "destinatario": {"type": "string", "description": "Nombre (o parte) o teléfono del contacto, tal como lo escribió el usuario"},
                    "importe": {"type": "number", "description": "Cantidad en euros"},
                    "concepto": {"type": "string", "description": "Solo si el usuario lo dijo; si no, OMÍTELO (nunca lo inventes)"},
                },
                "required": ["destinatario", "importe"],
            },
        ),
        ejecutar=ejecutar,
        etiqueta="Preparando el Bizum…",
        riesgo=Riesgo.ESCRITURA,
    )
