from ...dominio.modelos import Cliente
from ..casos_uso.bizum import SolicitarBizum
from ..eventos import OperacionPorConfirmar
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta, Riesgo


def crear(solicitar_bizum: SolicitarBizum) -> Herramienta:
    def ejecutar(args: dict, cliente: Cliente) -> ResultadoHerramienta:
        operacion = solicitar_bizum(
            cliente,
            str(args.get("destinatario", "")),
            float(args.get("importe", 0)),
            str(args.get("concepto", "")),
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
            "Inicia un Bizum a un contacto. NO lo envía: el cliente debe confirmarlo con un código OTP. "
            "SOLO debe llamarse después de que el usuario haya confirmado explícitamente el destinatario "
            "y el importe.",
            {
                "type": "object",
                "properties": {
                    "destinatario": {"type": "string", "description": "Nombre o teléfono del contacto"},
                    "importe": {"type": "number", "description": "Cantidad en euros"},
                    "concepto": {"type": "string", "description": "Concepto opcional del envío"},
                },
                "required": ["destinatario", "importe"],
            },
        ),
        ejecutar=ejecutar,
        etiqueta="Preparando el Bizum…",
        riesgo=Riesgo.ESCRITURA,
    )
