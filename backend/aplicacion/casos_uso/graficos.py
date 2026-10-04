"""Caso de uso: preparar un gráfico que el LLM ha diseñado (sin plantillas)."""
import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta

from ...dominio.errores import ErrorDeValidacion
from ...dominio.modelos import Cliente
from ..eventos import Grafico
from ..puertos.infraestructura import Reloj
from .banco import ConsultarMovimientos


def preparar_grafico(titulo: str, config: object) -> Grafico:
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            raise ErrorDeValidacion("config no es JSON válido") from None
    if not isinstance(config, dict) or "type" not in config or "data" not in config:
        raise ErrorDeValidacion("config debe incluir 'type' y 'data'")
    _validar_datos(config["data"])
    return Grafico(titulo or "Gráfico", config)


def _validar_datos(datos: object) -> None:
    """El modelo pequeño inventaba series (un «Total» de ~27.000 €) o series más cortas que las etiquetas:
    se rechaza para que el agente corrija con datos reales de `consultar_movimientos`."""
    if not isinstance(datos, dict):
        raise ErrorDeValidacion("config.data debe ser un objeto con 'labels' y 'datasets'")
    series = datos.get("datasets") or []
    etiquetas = datos.get("labels")
    if not isinstance(series, list) or any(not isinstance(s, dict) for s in series):
        raise ErrorDeValidacion("datasets debe ser una lista de series con 'data'")
    for serie in series:
        nombre = str(serie.get("label", "")).strip().lower()
        if nombre == "total" and len(series) > 1:
            raise ErrorDeValidacion(
                "No añadas una serie 'Total' inventada: usa solo las cifras devueltas por consultar_movimientos"
            )
        valores = serie.get("data")
        if not isinstance(valores, list):
            raise ErrorDeValidacion("cada serie necesita 'data' como lista de números")
        for v in valores:
            # scatter/bubble: puntos {x, y, r}; solo y (y r) han de ser numéricos, x puede ser una etiqueta o una fecha
            for numero in ([v.get("y"), v.get("r")] if isinstance(v, dict) else [v]):
                if numero is None:
                    continue
                if isinstance(numero, bool) or not isinstance(numero, (int, float)) or not math.isfinite(numero):
                    raise ErrorDeValidacion("los valores del gráfico deben ser números finitos")
        if isinstance(etiquetas, list) and len(valores) != len(etiquetas) and not any(isinstance(v, dict) for v in valores):
            raise ErrorDeValidacion(
                f"la serie '{serie.get('label', '')}' tiene {len(valores)} valores y hay {len(etiquetas)} etiquetas: deben coincidir"
            )


_RE_BLOQUE_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def extraer_grafico_del_texto(texto: str) -> tuple[str, Grafico | None]:
    """Red de seguridad: a veces el modelo escribe la config Chart.js como bloque ```json en la
    respuesta en vez de llamar a `generar_grafico`. Si el bloque es una config válida se
    convierte en gráfico y se quita del texto; si no, el texto queda intacto."""
    for m in _RE_BLOQUE_JSON.finditer(texto):
        try:
            config = json.loads(m.group(1))
            grafico = preparar_grafico(_titulo(config), config)
        except (json.JSONDecodeError, ErrorDeValidacion):
            continue
        limpio = (texto[: m.start()] + texto[m.end():]).strip()
        return limpio, grafico
    return texto, None


def _titulo(config: dict) -> str:
    titulo = config.get("options", {}).get("plugins", {}).get("title", {}).get("text") if isinstance(config, dict) else None
    return titulo if isinstance(titulo, str) and titulo else "Gráfico"


# ------------------------------------------------------------------ gráficos con los datos calculados por el servidor
# Los modelos pequeños (qwen3:8b) no encadenaban «consultar → generar_grafico» ni construían bien la config. Con una
# FUENTE declarativa el modelo solo elige tipo, título y fuente: el servidor ejecuta la consulta del cliente y construye
# etiquetas y series, de modo que no puede inventar cifras (incidencia 71).
FUENTES = ("gastos_por_categoria", "gastos_por_mes", "ingresos_vs_gastos", "gastos_por_comercio")
PERIODOS = ("todo", "ultimo_mes", "mes_actual", "mes_anterior", "ultimos_3_meses", "ultimos_12_meses", "ultimo_ano")
# Periodo que aplica el SERVIDOR cuando el modelo no dice ninguno (con `todo` explícito se respeta). Antes lo escogía el
# modelo y salía distinto cada vez. Evolución mensual → 12 meses naturales; reparto (categoría, comercio) → últimos 30 días
# (el mes en curso dejaba un gráfico casi vacío los primeros días del mes).
PERIODO_POR_DEFECTO = {
    "gastos_por_mes": "ultimos_12_meses", "ingresos_vs_gastos": "ultimos_12_meses",
    "gastos_por_categoria": "ultimo_mes", "gastos_por_comercio": "ultimo_mes",
}
TIPOS = ("bar", "line", "pie", "doughnut", "radar", "polarArea")
_TIPOS_POR_MINUSCULAS = {t.lower(): t for t in TIPOS}
_ALIAS_TIPO = {
    "barras": "bar", "barra": "bar", "columnas": "bar", "columna": "bar", "bar chart": "bar",
    "linea": "line", "línea": "line", "lineas": "line", "líneas": "line", "evolucion": "line", "evolución": "line",
    "tarta": "pie", "pastel": "pie", "circular": "pie", "queso": "pie", "pie chart": "pie",
    "donut": "doughnut", "anillo": "doughnut", "rosquilla": "doughnut",
    "telaraña": "radar", "tela de araña": "radar", "polar": "polarArea", "polararea": "polarArea",
}
_TIPO_POR_DEFECTO = {"gastos_por_categoria": "bar", "gastos_por_mes": "line", "ingresos_vs_gastos": "bar", "gastos_por_comercio": "bar"}
_TITULO_POR_DEFECTO = {
    "gastos_por_categoria": "Gastos por categoría", "gastos_por_mes": "Gastos por mes",
    "ingresos_vs_gastos": "Ingresos y gastos por mes", "gastos_por_comercio": "Gastos por comercio",
}
MAX_MESES = 24  # tope de meses de un gráfico mensual: si el periodo pedido abarca más, se muestran los 24 más recientes
MAX_COMERCIOS = 10

_RE_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
_RE_MES = re.compile(r"\b(mes(es)?|mensual(es)?|evoluci[oó]n|mes a mes)\b", re.IGNORECASE)
_RE_INGRESOS = re.compile(r"ingres|n[oó]mina", re.IGNORECASE)
_RE_COMERCIO = re.compile(r"comercio|tienda|establecimiento", re.IGNORECASE)


def sugerir_fuente(pregunta: str) -> str:
    """Fuente más probable según lo que pidió el usuario (para el empujón al modelo). Por defecto, gastos por categoría."""
    if _RE_INGRESOS.search(pregunta) and re.search(r"gasto", pregunta, re.IGNORECASE):
        return "ingresos_vs_gastos"
    if _RE_COMERCIO.search(pregunta):
        return "gastos_por_comercio"
    if re.search(r"categor", pregunta, re.IGNORECASE):
        return "gastos_por_categoria"
    if _RE_MES.search(pregunta):
        return "gastos_por_mes"
    return "gastos_por_categoria"


@dataclass(frozen=True)
class GraficoDeFuente:
    grafico: Grafico
    desde: str | None
    hasta: str | None
    datos: dict[str, object]  # lo que ve el modelo para redactar la conclusión: etiqueta → valor (o {serie: valor})


_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def etiqueta_periodo(ini: date | None, fin: date | None, hoy: date) -> str:
    """Texto corto del periodo aplicado, para el título del gráfico: «oct 2026», «4 sep – 3 oct 2026»..."""
    if ini is None and fin is None:
        return "todo el historial"
    if ini is None:
        return f"hasta el {fin.day} {_MESES[fin.month - 1]} {fin.year}"
    if fin is None:
        return f"desde el {ini.day} {_MESES[ini.month - 1]} {ini.year}"
    siguiente = (fin.replace(day=28) + timedelta(days=4)).replace(day=1)
    mes_completo = ini.day == 1 and ini.month == fin.month and ini.year == fin.year and (fin == siguiente - timedelta(days=1) or fin == hoy)
    if mes_completo:
        return f"{_MESES[ini.month - 1]} {ini.year}"
    desde = f"{ini.day} {_MESES[ini.month - 1]}" + (f" {ini.year}" if ini.year != fin.year else "")
    return f"{desde} – {fin.day} {_MESES[fin.month - 1]} {fin.year}"


def _primer_dia_del_mes(dia: date) -> date:
    return dia.replace(day=1)


def resolver_periodo(periodo: str, hoy: date) -> tuple[date | None, date | None]:
    if periodo == "todo":
        return None, None
    if periodo == "ultimo_mes":  # los últimos 30 días, hoy incluido
        return hoy - timedelta(days=29), hoy
    if periodo == "mes_actual":
        return _primer_dia_del_mes(hoy), hoy
    if periodo == "mes_anterior":
        fin = _primer_dia_del_mes(hoy) - timedelta(days=1)
        return _primer_dia_del_mes(fin), fin
    if periodo == "ultimos_3_meses":
        return hoy - timedelta(days=89), hoy
    if periodo == "ultimos_12_meses":  # 12 meses naturales: el actual y los 11 anteriores, completos
        mes = hoy.year * 12 + hoy.month - 1 - 11
        return date(mes // 12, mes % 12 + 1, 1), hoy
    if periodo == "ultimo_ano":
        return hoy - timedelta(days=364), hoy
    raise ErrorDeValidacion(f"periodo desconocido: usa uno de {', '.join(PERIODOS)} (o desde/hasta en AAAA-MM-DD)")


def _fecha(valor: object, nombre: str) -> date | None:
    if valor in (None, ""):
        return None
    if not isinstance(valor, str) or not _RE_FECHA.fullmatch(valor.strip()):
        raise ErrorDeValidacion(f"{nombre} debe ser una fecha AAAA-MM-DD")
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        raise ErrorDeValidacion(f"{nombre} no es una fecha válida (AAAA-MM-DD)") from None


def normalizar_tipo(tipo: object, fuente: str) -> str:
    if tipo in (None, ""):
        return _TIPO_POR_DEFECTO[fuente]
    clave = str(tipo).strip()
    elegido = _ALIAS_TIPO.get(clave.lower()) or _TIPOS_POR_MINUSCULAS.get(clave.lower())  # «PIE», «Doughnut»...
    if elegido is None:
        raise ErrorDeValidacion(f"tipo desconocido: usa uno de {', '.join(TIPOS)}")
    if fuente == "ingresos_vs_gastos" and elegido not in ("bar", "line"):
        raise ErrorDeValidacion("ingresos_vs_gastos tiene dos series: usa tipo bar o line")
    return elegido


class GenerarGraficoDeFuente:
    """Caso de uso: ejecuta en el servidor la consulta de una fuente declarativa y construye el gráfico Chart.js."""

    def __init__(self, consultar_movimientos: ConsultarMovimientos, reloj: Reloj):
        self._consultar = consultar_movimientos
        self._reloj = reloj

    def __call__(
        self, cliente: Cliente, fuente: object, titulo: str = "", tipo: object = None, periodo: object = None,
        desde: object = None, hasta: object = None,
    ) -> GraficoDeFuente:
        if fuente not in FUENTES:
            raise ErrorDeValidacion(f"fuente desconocida: usa una de {', '.join(FUENTES)}")
        tipo_final = normalizar_tipo(tipo, fuente)
        ini_explicito, fin_explicito = _fecha(desde, "desde"), _fecha(hasta, "hasta")
        if ini_explicito or fin_explicito:
            ini, fin = ini_explicito, fin_explicito
        else:
            ini, fin = resolver_periodo(str(periodo or PERIODO_POR_DEFECTO[fuente]), self._reloj.hoy())
        if ini and fin and ini > fin:
            raise ErrorDeValidacion("desde no puede ser posterior a hasta")

        filtros = ["importe < 0"] if fuente != "ingresos_vs_gastos" else ["1 = 1"]
        if ini:
            filtros.append(f"fecha >= '{ini.isoformat()}'")  # las fechas ya están validadas: solo dígitos y guiones
        if fin:
            filtros.append(f"fecha <= '{fin.isoformat()}'")
        donde = " AND ".join(filtros)
        resultado = self._consultar(cliente, _sql(fuente, donde))
        filas = resultado.filas
        if not filas:
            raise ErrorDeValidacion("No hay movimientos en ese periodo: prueba con otro (o sin periodo).")
        if fuente in ("gastos_por_mes", "ingresos_vs_gastos"):
            filas = list(reversed(filas))  # la consulta trae los meses más recientes primero (acotados a MAX_MESES)

        etiquetas = [str(f[0]) for f in filas]
        if fuente == "ingresos_vs_gastos":
            series = [("Ingresos", [f[1] for f in filas]), ("Gastos", [f[2] for f in filas])]
            datos = {e: {"ingresos": f[1], "gastos": f[2]} for e, f in zip(etiquetas, filas)}
        else:
            nombre = "Gastos (€)"
            series = [(nombre, [f[1] for f in filas])]
            datos = {e: f[1] for e, f in zip(etiquetas, filas)}
        titulo_base = (titulo or "").strip() or _TITULO_POR_DEFECTO[fuente]
        titulo_final = f"{titulo_base} · {etiqueta_periodo(ini, fin, self._reloj.hoy())}"  # el periodo aplicado se ve siempre
        config = {
            "type": tipo_final,
            "data": {"labels": etiquetas, "datasets": [{"label": n, "data": v} for n, v in series]},
        }
        grafico = preparar_grafico(titulo_final, config)
        return GraficoDeFuente(grafico, ini.isoformat() if ini else None, fin.isoformat() if fin else None, datos)


def _sql(fuente: str, donde: str) -> str:
    if fuente == "gastos_por_categoria":
        return (f"SELECT categoria, ROUND(SUM(-importe), 2) AS total FROM movimientos WHERE {donde} "
                "GROUP BY categoria ORDER BY total DESC")
    if fuente == "gastos_por_comercio":
        return (f"SELECT comercio, ROUND(SUM(-importe), 2) AS total FROM movimientos WHERE {donde} "
                f"GROUP BY comercio ORDER BY total DESC LIMIT {MAX_COMERCIOS}")
    if fuente == "gastos_por_mes":
        return (f"SELECT strftime('%Y-%m', fecha) AS mes, ROUND(SUM(-importe), 2) FROM movimientos WHERE {donde} "
                f"GROUP BY mes ORDER BY mes DESC LIMIT {MAX_MESES}")
    return (  # ingresos_vs_gastos
        "SELECT strftime('%Y-%m', fecha) AS mes, "
        "ROUND(SUM(CASE WHEN importe > 0 THEN importe ELSE 0 END), 2), "
        "ROUND(SUM(CASE WHEN importe < 0 THEN -importe ELSE 0 END), 2) "
        f"FROM movimientos WHERE {donde} GROUP BY mes ORDER BY mes DESC LIMIT {MAX_MESES}"
    )
