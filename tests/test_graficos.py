"""Validación de los gráficos que diseña el LLM (incidencia 46)."""
import json as _json

import pytest

from backend.adaptadores.salida.sqlite.conexion import BaseDeDatos
from backend.adaptadores.salida.sqlite.consultor import ConsultorMovimientosSqlite
from backend.aplicacion.casos_uso.banco import ConsultarMovimientos
from backend.aplicacion.casos_uso.graficos import GenerarGraficoDeFuente, preparar_grafico, sugerir_fuente
from backend.aplicacion.herramientas import grafico as herramienta_grafico
from backend.aplicacion.herramientas.registro import RegistroHerramientas
from backend.dominio.errores import ErrorDeValidacion
from tests.fakes import ALEX, ANA, AuditoriaEnMemoria, RelojFijo


def _config(labels, *series, tipo="bar"):
    return {"type": tipo, "data": {"labels": labels, "datasets": [{"label": n, "data": d} for n, d in series]}}


def test_grafico_con_serie_total_inventada_se_rechaza():
    config = _config(["Ene", "Feb"], ("Comida", [100, 120]), ("Total", [27000, 27000]))
    with pytest.raises(ErrorDeValidacion, match="Total"):
        preparar_grafico("G", config)


@pytest.mark.parametrize("valores", [[1, 2, 3], [1], [1, "2"], [1, float("nan")], [1, float("inf")], [True, 2]])
def test_grafico_con_series_de_longitud_o_valores_invalidos_se_rechaza(valores):
    with pytest.raises(ErrorDeValidacion):
        preparar_grafico("G", _config(["Ene", "Feb"], ("Comida", valores)))


def test_grafico_correcto_y_scatter_siguen_pasando():
    assert preparar_grafico("G", _config(["Ene", "Feb"], ("Comida", [100, 120.5]), ("Ocio", [None, 3]))).titulo == "G"
    dispersion = {"type": "scatter", "data": {"datasets": [{"label": "p", "data": [{"x": 1, "y": 2}]}]}}
    assert preparar_grafico("G", dispersion).config["type"] == "scatter"


def test_scatter_con_x_de_texto_pasa_pero_una_y_invalida_no():
    ok = {"type": "scatter", "data": {"datasets": [{"label": "p", "data": [{"x": "Ene", "y": 2}]}]}}
    assert preparar_grafico("G", ok).config["type"] == "scatter"
    mal = {"type": "scatter", "data": {"datasets": [{"label": "p", "data": [{"x": 1, "y": "2"}]}]}}
    with pytest.raises(ErrorDeValidacion):
        preparar_grafico("G", mal)


def test_una_serie_total_legitima_con_varias_series_tambien_se_rechaza():
    # compromiso aceptado (incidencia 46): no se distingue un «Total» real de uno inventado
    with pytest.raises(ErrorDeValidacion, match="Total"):
        preparar_grafico("G", _config(["Ene"], ("Comida", [1]), ("Total", [1])))


# ------------------------------------------------------------------ gráficos con datos calculados por el servidor (incidencia 71)

@pytest.fixture
def bd_con_movimientos(tmp_path):
    """BD mínima con dos clientes: el gráfico solo debe ver los movimientos del cliente de la sesión."""
    bd = BaseDeDatos(tmp_path / "g.db")
    con = bd.abrir()
    con.executescript(
        "CREATE TABLE movimientos(id INTEGER PRIMARY KEY, cliente_id INT, fecha TEXT, categoria TEXT, concepto TEXT, comercio TEXT, importe REAL);"
        "CREATE TABLE cuenta(cliente_id INT, iban TEXT, titular TEXT, saldo REAL);"
        "CREATE TABLE contactos_bizum(cliente_id INT, nombre TEXT, telefono TEXT);"
    )
    filas = [
        (ALEX.id, "2026-09-20", "Supermercado", "Compra", "Mercadona", -100.0),
        (ALEX.id, "2026-09-25", "Supermercado", "Compra", "Mercadona", -50.0),
        (ALEX.id, "2026-09-28", "Ocio", "Cine", "Cinesa", -30.0),
        (ALEX.id, "2026-10-01", "Bizum", "Bizum enviado", "Bizum", -25.0),
        (ALEX.id, "2026-10-01", "Bizum", "Bizum recibido", "Bizum", 40.0),
        (ALEX.id, "2026-09-01", "Nómina", "Nómina", "Empresa", 1500.0),
        (ALEX.id, "2026-08-10", "Ropa", "Camisa", "Zara", -60.0),
        (ANA.id, "2026-09-20", "Vivienda", "Alquiler", "Casero", -700.0),
    ]
    con.executemany("INSERT INTO movimientos(cliente_id, fecha, categoria, concepto, comercio, importe) VALUES (?,?,?,?,?,?)", filas)
    con.commit()
    con.close()
    return bd


@pytest.fixture
def servicio(bd_con_movimientos):
    consultor = ConsultorMovimientosSqlite(bd_con_movimientos)
    return GenerarGraficoDeFuente(ConsultarMovimientos(consultor, AuditoriaEnMemoria()), RelojFijo())


def _ejecutar(servicio, **args):
    registro = RegistroHerramientas([herramienta_grafico.crear(servicio)])
    return registro.ejecutar("generar_grafico", _json.dumps({"titulo": "T", **args}), ALEX)


def test_el_servidor_calcula_los_gastos_por_categoria(servicio):
    r = _ejecutar(servicio, fuente="gastos_por_categoria", periodo="todo")
    assert r.datos["ok"] is True and len(r.eventos) == 1
    config = r.eventos[0].config
    assert config["type"] == "bar"
    assert dict(zip(config["data"]["labels"], config["data"]["datasets"][0]["data"])) == {"Supermercado": 150.0, "Ropa": 60.0, "Ocio": 30.0, "Bizum": 25.0}
    assert "Vivienda" not in config["data"]["labels"]  # los datos de otro cliente no existen para el gráfico
    assert r.datos["datos"]["Supermercado"] == 150.0  # el modelo ve las cifras reales para su conclusión


def test_el_modelo_no_puede_colar_cifras_con_fuente(servicio):
    """Con `fuente` la `config` del modelo se ignora: las cifras son las del servidor."""
    falsa = {"type": "bar", "data": {"labels": ["Inventado"], "datasets": [{"label": "x", "data": [999999]}]}}
    r = _ejecutar(servicio, fuente="gastos_por_categoria", config=falsa)
    assert "Inventado" not in r.eventos[0].config["data"]["labels"]


def test_periodo_y_fechas_filtran(servicio):
    # RelojFijo = 3-oct-2026: el último mes son 4-sep..3-oct (30 días, hoy incluido); el movimiento de agosto queda fuera
    r = _ejecutar(servicio, fuente="gastos_por_categoria", periodo="ultimo_mes")
    assert "Ropa" not in r.eventos[0].config["data"]["labels"] and r.datos["desde"] == "2026-09-04"
    r = _ejecutar(servicio, fuente="gastos_por_categoria", desde="2026-08-01", hasta="2026-08-31")
    assert r.eventos[0].config["data"]["labels"] == ["Ropa"]


def test_meses_ingresos_y_gastos_y_tipos_en_castellano(servicio):
    r = _ejecutar(servicio, fuente="ingresos_vs_gastos", tipo="barras")
    config = r.eventos[0].config
    assert config["data"]["labels"] == sorted(config["data"]["labels"]) and config["type"] == "bar"
    assert [s["label"] for s in config["data"]["datasets"]] == ["Ingresos", "Gastos"]
    assert _ejecutar(servicio, fuente="gastos_por_mes").eventos[0].config["type"] == "line"
    assert _ejecutar(servicio, fuente="gastos_por_categoria", tipo="tarta").eventos[0].config["type"] == "pie"


@pytest.mark.parametrize("args", [
    {"fuente": "ventas"}, {"fuente": "gastos_por_categoria", "tipo": "cubo"},
    {"fuente": "gastos_por_categoria", "periodo": "ayer"}, {"fuente": "gastos_por_categoria", "desde": "2026-13-45"},
    {"fuente": "gastos_por_categoria", "desde": "' OR 1=1 --"}, {"fuente": "ingresos_vs_gastos", "tipo": "pie"},
    {"fuente": "gastos_por_categoria", "desde": "2027-01-01"},
])
def test_entradas_invalidas_se_devuelven_al_modelo_como_error(servicio, args):
    r = _ejecutar(servicio, **args)
    assert r.datos["ok"] is False and not r.eventos


def test_sugerir_fuente_segun_la_pregunta():
    assert sugerir_fuente("Hazme un gráfico de mis gastos por categoría del último mes") == "gastos_por_categoria"
    assert sugerir_fuente("Dibújame la evolución mes a mes") == "gastos_por_mes"
    assert sugerir_fuente("gráfico de ingresos y gastos") == "ingresos_vs_gastos"
    assert sugerir_fuente("gráfico por comercio") == "gastos_por_comercio"
    assert sugerir_fuente("un gráfico") == "gastos_por_categoria"


# ------------------------------------------------------------------ periodo por defecto y título (incidencia 90)

def test_sin_periodo_el_servidor_aplica_un_valor_determinista_segun_la_fuente(servicio):
    """Antes lo elegía el modelo y salía distinto cada vez: categorías/comercios → últimos 30 días; meses → 12 meses naturales."""
    r = _ejecutar(servicio, fuente="gastos_por_categoria")
    assert (r.datos["desde"], r.datos["hasta"]) == ("2026-09-04", "2026-10-03")
    assert "Ropa" not in r.eventos[0].config["data"]["labels"]  # agosto queda fuera del último mes
    r = _ejecutar(servicio, fuente="gastos_por_comercio")
    assert r.datos["desde"] == "2026-09-04"
    r = _ejecutar(servicio, fuente="gastos_por_mes")
    assert (r.datos["desde"], r.datos["hasta"]) == ("2025-11-01", "2026-10-03")
    assert "2026-08" in r.eventos[0].config["data"]["labels"]
    assert _ejecutar(servicio, fuente="ingresos_vs_gastos").datos["desde"] == "2025-11-01"


def test_el_titulo_muestra_el_periodo_aplicado(servicio):
    assert _ejecutar(servicio, fuente="gastos_por_categoria").eventos[0].titulo == "T · 4 sep – 3 oct 2026"
    assert _ejecutar(servicio, fuente="gastos_por_categoria", periodo="mes_anterior").eventos[0].titulo == "T · sep 2026"
    assert _ejecutar(servicio, fuente="gastos_por_categoria", periodo="mes_actual").eventos[0].titulo == "T · oct 2026"
    assert _ejecutar(servicio, fuente="gastos_por_categoria", periodo="todo").eventos[0].titulo == "T · todo el historial"
    assert _ejecutar(servicio, fuente="gastos_por_mes").eventos[0].titulo == "T · 1 nov 2025 – 3 oct 2026"


def test_un_periodo_explicito_se_respeta_sobre_el_defecto(servicio):
    r = _ejecutar(servicio, fuente="gastos_por_categoria", periodo="todo")
    assert r.datos["desde"] is None and "Ropa" in r.eventos[0].config["data"]["labels"]


@pytest.mark.parametrize("tipo, esperado", [("PIE", "pie"), ("Doughnut", "doughnut"), ("POLARAREA", "polarArea"), ("Barras", "bar")])
def test_los_tipos_en_ingles_no_distinguen_mayusculas(servicio, tipo, esperado):
    assert _ejecutar(servicio, fuente="gastos_por_categoria", tipo=tipo).eventos[0].config["type"] == esperado
