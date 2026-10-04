import json

from ...dominio.modelos import Cliente
from ..casos_uso.banco import ConsultarMovimientos
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta


def limitar_tamano(datos: dict, max_caracteres: int) -> dict:
    """Recorta las filas hasta que el resultado cabe en `max_caracteres`: todo lo que se devuelve al modelo
    se reenvía en cada ronda y se paga en tokens."""
    filas = datos["filas"]
    while filas and len(json.dumps(datos, ensure_ascii=False)) > max_caracteres:
        filas = filas[: max(1, int(len(filas) * 0.7))]
        datos = {**datos, "filas": filas, "num_filas": len(filas), "truncado": True,
                 "nota": "Resultado recortado por tamaño: pide un resumen o un periodo más concreto."}
        if len(filas) == 1:
            break
    return datos


def crear(consultar_movimientos: ConsultarMovimientos, max_caracteres: int = 6_000) -> Herramienta:
    def ejecutar(args: dict, cliente: Cliente) -> ResultadoHerramienta:
        r = consultar_movimientos(cliente, str(args.get("sql", "")))
        return ResultadoHerramienta(limitar_tamano({
            "ok": True,
            "columnas": r.columnas,
            "filas": r.filas,
            "num_filas": len(r.filas),
            "truncado": r.truncado,
        }, max_caracteres))

    return Herramienta(
        esquema=EsquemaHerramienta(
            "consultar_movimientos",
            "Ejecuta una consulta SQL (SQLite, solo SELECT) sobre el histórico de "
            "movimientos para responder preguntas sobre gastos, ingresos, categorías, "
            "comercios o fechas. Para redondear usa ROUND(x, 2): printf y format no están permitidos.",
            {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "Consulta SELECT en dialecto SQLite"}},
                "required": ["sql"],
            },
        ),
        ejecutar=ejecutar,
        etiqueta="Analizando tus movimientos…",
    )
