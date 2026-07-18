"""Herramientas (function calling) que el LLM puede invocar."""
import json

from . import db

ESQUEMAS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_saldo",
            "description": "Obtiene el saldo actual, el IBAN y el titular de la cuenta.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_contactos_bizum",
            "description": "Lista los contactos disponibles para enviar Bizum (nombre y teléfono).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transferencia_bizum",
            "description": (
                "Envía un Bizum a un contacto. SOLO debe llamarse después de que el "
                "usuario haya confirmado explícitamente el destinatario y el importe."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "destinatario": {"type": "string", "description": "Nombre o teléfono del contacto"},
                    "importe": {"type": "number", "description": "Cantidad en euros"},
                    "concepto": {"type": "string", "description": "Concepto opcional del envío"},
                },
                "required": ["destinatario", "importe"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_movimientos",
            "description": (
                "Ejecuta una consulta SQL (SQLite, solo SELECT) sobre el histórico de "
                "movimientos para responder preguntas sobre gastos, ingresos, categorías, "
                "comercios o fechas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Consulta SELECT en dialecto SQLite"},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generar_grafico",
            "description": (
                "Muestra al usuario un gráfico interactivo. Tú decides el tipo de gráfico "
                "más adecuado a los datos (bar, line, pie, doughnut, radar, scatter...) y "
                "construyes la configuración completa de Chart.js con los datos reales "
                "obtenidos previamente con consultar_movimientos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Título breve del gráfico"},
                    "config": {
                        "type": "object",
                        "description": (
                            "Configuración Chart.js completa y válida en JSON: "
                            "{type, data: {labels, datasets}, options}. Sin funciones JS."
                        ),
                    },
                },
                "required": ["titulo", "config"],
            },
        },
    },
]


def ejecutar(nombre: str, args: dict) -> tuple[dict, dict | None]:
    """Ejecuta una herramienta. Devuelve (resultado_para_el_llm, evento_extra)."""
    if nombre == "consultar_saldo":
        return db.obtener_saldo(), None

    if nombre == "listar_contactos_bizum":
        return {"contactos": db.listar_contactos()}, None

    if nombre == "transferencia_bizum":
        resultado = db.transferir_bizum(
            str(args.get("destinatario", "")),
            float(args.get("importe", 0)),
            str(args.get("concepto", "")),
        )
        return resultado, None

    if nombre == "consultar_movimientos":
        return db.ejecutar_select(str(args.get("sql", ""))), None

    if nombre == "generar_grafico":
        config = args.get("config")
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except json.JSONDecodeError:
                return {"ok": False, "error": "config no es JSON válido"}, None
        if not isinstance(config, dict) or "type" not in config or "data" not in config:
            return {"ok": False, "error": "config debe incluir 'type' y 'data'"}, None
        titulo = str(args.get("titulo", "Gráfico"))
        evento = {"grafico": {"titulo": titulo, "config": config}}
        return {"ok": True, "mensaje": f"Gráfico '{titulo}' mostrado al usuario."}, evento

    return {"ok": False, "error": f"Herramienta desconocida: {nombre}"}, None
