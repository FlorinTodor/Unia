from ..casos_uso.banco import ConsultarMovimientos
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta


def crear(consultar_movimientos: ConsultarMovimientos) -> Herramienta:
    def ejecutar(args: dict) -> ResultadoHerramienta:
        r = consultar_movimientos(str(args.get("sql", "")))
        return ResultadoHerramienta({
            "ok": True,
            "columnas": r.columnas,
            "filas": r.filas,
            "num_filas": len(r.filas),
            "truncado": r.truncado,
        })

    return Herramienta(
        esquema=EsquemaHerramienta(
            "consultar_movimientos",
            "Ejecuta una consulta SQL (SQLite, solo SELECT) sobre el histórico de "
            "movimientos para responder preguntas sobre gastos, ingresos, categorías, "
            "comercios o fechas.",
            {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "Consulta SELECT en dialecto SQLite"}},
                "required": ["sql"],
            },
        ),
        ejecutar=ejecutar,
        etiqueta="Analizando tus movimientos…",
    )
