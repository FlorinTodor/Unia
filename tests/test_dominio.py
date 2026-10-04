import pytest

from backend.dominio import reglas
from backend.dominio.ajustes import Ajustes, ConfigClave
from backend.dominio.errores import ConsultaNoPermitida, ImporteInvalido, LimiteBizumExcedido, SaldoInsuficiente
from backend.dominio.proveedores import ModeloRef


def test_importe_bizum_se_redondea_a_centimos():
    assert reglas.validar_importe_bizum(10.456) == 10.46


@pytest.mark.parametrize("importe", [0, -5])
def test_importe_bizum_no_positivo(importe):
    with pytest.raises(ImporteInvalido):
        reglas.validar_importe_bizum(importe)


def test_importe_bizum_supera_tope():
    with pytest.raises(LimiteBizumExcedido):
        reglas.validar_importe_bizum(1000.01)
    assert reglas.validar_importe_bizum(1000) == 1000


def test_saldo_insuficiente():
    with pytest.raises(SaldoInsuficiente):
        reglas.validar_saldo_suficiente(10, 10.01)
    reglas.validar_saldo_suficiente(10, 10)


@pytest.mark.parametrize("sql", [
    "DELETE FROM movimientos",
    "SELECT 1; DROP TABLE cuenta",
    "UPDATE cuenta SET saldo = 1e9",
    "WITH x AS (SELECT 1) INSERT INTO movimientos VALUES (1)",
    "PRAGMA writable_schema=1",
])
def test_sql_peligroso_rechazado(sql):
    with pytest.raises(ConsultaNoPermitida):
        reglas.validar_consulta_solo_lectura(sql)


def test_sql_select_permitido_y_limpio():
    assert reglas.validar_consulta_solo_lectura("  SELECT 1 ;  ") == "SELECT 1"
    assert reglas.validar_consulta_solo_lectura("with a as (select 1) select * from a")


def test_cadena_llm_activa_primero_y_local_al_final():
    a = Ajustes(
        activo="openai",
        claves={"groq": ConfigClave("k1", "g1", "g2"), "openai": ConfigClave("k2", "o1", None)},
        ollama_modelo="qwen",
    )
    assert a.cadena_llm() == [
        ModeloRef("openai", "o1"), ModeloRef("groq", "g1"), ModeloRef("groq", "g2"), ModeloRef("ollama", "qwen"),
    ]


def test_cadena_llm_con_ia_local_activa_no_usa_la_nube():
    a = Ajustes(activo="ollama", claves={"groq": ConfigClave("k", "g1")}, ollama_modelo="qwen")
    assert a.cadena_llm() == [ModeloRef("ollama", "qwen")]


def test_cadena_llm_sin_configurar_y_sin_fallback_esta_vacia():
    assert Ajustes(fallback_local=False).cadena_llm() == []


def test_transcripcion_prefiere_groq():
    a = Ajustes(claves={"openai": ConfigClave("k"), "groq": ConfigClave("k")})
    assert a.transcripcion() == ModeloRef("groq", "whisper-large-v3-turbo")
    assert Ajustes(claves={"gemini": ConfigClave("k")}).transcripcion() is None


@pytest.mark.parametrize("importe", [float("nan"), float("inf"), float("-inf")])
def test_bizum_rechaza_importes_no_finitos(importe):
    # NaN no es > TOPE ni <= 0: sin isfinite se colaba como importe válido (incidencia 47)
    with pytest.raises(ImporteInvalido):
        reglas.validar_importe_bizum(importe)
