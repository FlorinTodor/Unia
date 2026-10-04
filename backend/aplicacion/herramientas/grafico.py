from ...dominio.modelos import Cliente
from ..casos_uso.graficos import FUENTES, PERIODOS, TIPOS, GenerarGraficoDeFuente, preparar_grafico
from ..puertos.llm import EsquemaHerramienta
from .registro import Herramienta, ResultadoHerramienta


def crear(desde_fuente: GenerarGraficoDeFuente | None = None) -> Herramienta:
    """`generar_grafico`: con `fuente` el SERVIDOR calcula los datos (el modelo no puede inventar cifras); con `config`
    el modelo aporta una configuración Chart.js propia, para lo que ninguna fuente cubre. Sin `desde_fuente` solo vale `config`.
    Si llega `fuente`, `config` se IGNORA por completo (rama de arriba): las cifras son siempre las del servidor."""

    def ejecutar(args: dict, cliente: Cliente) -> ResultadoHerramienta:
        if desde_fuente is not None and args.get("fuente"):
            hecho = desde_fuente(
                cliente, args.get("fuente"), str(args.get("titulo") or ""), args.get("tipo"), args.get("periodo"),
                args.get("desde"), args.get("hasta"),
            )
            return ResultadoHerramienta(
                {
                    "ok": True,
                    "mensaje": f"Gráfico '{hecho.grafico.titulo}' mostrado al usuario con datos calculados por el servidor. "
                               "Resume la conclusión principal en una o dos frases, sin repetir todas las cifras.",
                    "desde": hecho.desde, "hasta": hecho.hasta, "datos": hecho.datos,
                },
                eventos=(hecho.grafico,),
            )
        grafico = preparar_grafico(str(args.get("titulo", "Gráfico")), args.get("config"))
        return ResultadoHerramienta(
            {"ok": True, "mensaje": f"Gráfico '{grafico.titulo}' mostrado al usuario."},
            eventos=(grafico,),
        )

    propiedades = {"titulo": {"type": "string", "description": "Título breve del gráfico"}}
    requeridos = ["titulo"]
    if desde_fuente is not None:
        descripcion = (
            "Muestra al usuario un gráfico interactivo. LLÁMALA DIRECTAMENTE con `fuente`: el servidor consulta los "
            "datos reales del cliente y construye el gráfico, así que NO hace falta consultar_movimientos antes y "
            "no hay que escribir cifras. Fuentes: gastos_por_categoria, gastos_por_mes, ingresos_vs_gastos, "
            "gastos_por_comercio. Solo si ninguna fuente encaja, pasa `config` (Chart.js completa, con datos reales "
            "obtenidos antes con consultar_movimientos)."
        )
        propiedades |= {
            "fuente": {"type": "string", "enum": list(FUENTES), "description": "De dónde salen los datos (los calcula el servidor)"},
            "tipo": {"type": "string", "enum": list(TIPOS),
                     "description": "Tipo de gráfico: bar (por defecto), line (evolución), pie/doughnut (proporciones), radar..."},
            "periodo": {"type": "string", "enum": list(PERIODOS),
                        "description": "Periodo: ultimo_mes = últimos 30 días; mes_anterior = el mes natural pasado; "
                                       "ultimos_12_meses = 12 meses naturales; todo = sin filtro (solo si el usuario pide todo el historial). "
                                       "Si el usuario no dice un periodo, NO lo pases: el servidor usa 12 meses para gráficos "
                                       "mensuales y 30 días para categorías/comercios"},
            "desde": {"type": "string", "description": "Opcional: fecha inicial AAAA-MM-DD (sustituye a periodo)"},
            "hasta": {"type": "string", "description": "Opcional: fecha final AAAA-MM-DD (sustituye a periodo)"},
        }
    else:
        descripcion = (
            "Muestra al usuario un gráfico interactivo. Tú decides el tipo de gráfico "
            "más adecuado a los datos (bar, line, pie, doughnut, radar, scatter...) y "
            "construyes la configuración completa de Chart.js con los datos reales "
            "obtenidos previamente con consultar_movimientos."
        )
        requeridos.append("config")
    propiedades["config"] = {
        "type": "object",
        "description": "Configuración Chart.js completa y válida en JSON: {type, data: {labels, datasets}, options}. "
                       "Sin funciones JS." + (" Solo si no usas `fuente`." if desde_fuente is not None else ""),
    }
    return Herramienta(
        esquema=EsquemaHerramienta(
            "generar_grafico", descripcion, {"type": "object", "properties": propiedades, "required": requeridos},
        ),
        ejecutar=ejecutar,
        etiqueta="Generando gráfico…",
    )
