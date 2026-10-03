from ...dominio.modelos import Cliente
from ..casos_uso.graficos import preparar_grafico
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta


def ejecutar(args: dict, _cliente: Cliente) -> ResultadoHerramienta:
    grafico = preparar_grafico(str(args.get("titulo", "Gráfico")), args.get("config"))
    return ResultadoHerramienta(
        {"ok": True, "mensaje": f"Gráfico '{grafico.titulo}' mostrado al usuario."},
        eventos=(grafico,),
    )


def crear() -> Herramienta:
    return Herramienta(
        esquema=EsquemaHerramienta(
            "generar_grafico",
            "Muestra al usuario un gráfico interactivo. Tú decides el tipo de gráfico "
            "más adecuado a los datos (bar, line, pie, doughnut, radar, scatter...) y "
            "construyes la configuración completa de Chart.js con los datos reales "
            "obtenidos previamente con consultar_movimientos.",
            {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Título breve del gráfico"},
                    "config": {
                        "type": "object",
                        "description": "Configuración Chart.js completa y válida en JSON: "
                        "{type, data: {labels, datasets}, options}. Sin funciones JS.",
                    },
                },
                "required": ["titulo", "config"],
            },
        ),
        ejecutar=ejecutar,
        etiqueta="Generando gráfico…",
    )
