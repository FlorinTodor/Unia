from ..casos_uso.banco import EnviarBizum
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta, Riesgo


def crear(enviar_bizum: EnviarBizum) -> Herramienta:
    def ejecutar(args: dict) -> ResultadoHerramienta:
        comprobante = enviar_bizum(
            str(args.get("destinatario", "")),
            float(args.get("importe", 0)),
            str(args.get("concepto", "")),
        )
        return ResultadoHerramienta({
            "ok": True,
            "destinatario": comprobante.destinatario,
            "telefono": comprobante.telefono,
            "importe": comprobante.importe,
            "concepto": comprobante.concepto,
            "nuevo_saldo": round(comprobante.nuevo_saldo, 2),
        })

    return Herramienta(
        esquema=EsquemaHerramienta(
            "transferencia_bizum",
            "Envía un Bizum a un contacto. SOLO debe llamarse después de que el "
            "usuario haya confirmado explícitamente el destinatario y el importe.",
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
        etiqueta="Procesando Bizum…",
        riesgo=Riesgo.ESCRITURA,
    )
