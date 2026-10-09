"""Garantiza la regla de dependencia de la arquitectura hexagonal (análisis estático de imports).

    dominio      → no importa nada del proyecto
    aplicacion   → solo dominio (y su propia capa)
    adaptadores  → dominio y aplicacion; las entradas no conocen las salidas, y viceversa
    composicion  → único lugar que conoce todo
"""
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent / "backend"

# capa → capas del proyecto que NO puede importar
PROHIBIDO = {
    "dominio": {"aplicacion", "adaptadores", "composicion", "main"},
    "aplicacion": {"adaptadores", "composicion", "main"},
    "adaptadores/entrada": {"adaptadores/salida", "composicion", "main"},
    "adaptadores/salida": {"adaptadores/entrada", "composicion", "main"},
}

# librerías de infraestructura que dominio y aplicación no pueden usar
LIBRERIAS_PROHIBIDAS = {
    "dominio": {"fastapi", "starlette", "pydantic", "openai", "sqlite3", "httpx", "piper", "omnivoice", "torch", "dotenv", "uvicorn"},
    "aplicacion": {"fastapi", "starlette", "pydantic", "openai", "sqlite3", "httpx", "piper", "omnivoice", "torch", "dotenv", "uvicorn"},
}


def _capa(ruta: Path) -> str:
    partes = ruta.relative_to(RAIZ).with_suffix("").parts
    if partes[0] == "adaptadores":
        return f"adaptadores/{partes[1]}"
    return partes[0]


def _destino_en_proyecto(ruta: Path, nodo: ast.ImportFrom) -> str | None:
    """Capa del proyecto a la que apunta un `from ... import`, o None si es externo."""
    if nodo.level == 0:
        return None
    paquete = list(ruta.relative_to(RAIZ).with_suffix("").parts[:-1])  # carpeta del módulo
    base = paquete[: len(paquete) - (nodo.level - 1)]
    destino = base + (nodo.module.split(".") if nodo.module else [])
    if not destino:  # `from .. import x` desde la raíz: x es la capa
        destino = [nodo.names[0].name]
    if destino[0] == "adaptadores" and len(destino) > 1:
        return f"adaptadores/{destino[1]}"
    return destino[0]


def _modulos():
    return [(r, _capa(r)) for r in sorted(RAIZ.rglob("*.py")) if r.name != "__init__.py" and len(r.relative_to(RAIZ).parts) > 1]


@pytest.mark.parametrize("ruta,capa", _modulos(), ids=lambda v: str(v.relative_to(RAIZ)) if isinstance(v, Path) else v)
def test_respeta_la_regla_de_dependencia(ruta, capa):
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    prohibidas = PROHIBIDO.get(capa, set())
    externas = LIBRERIAS_PROHIBIDAS.get(capa, set())
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            destino = _destino_en_proyecto(ruta, nodo)
            if destino is not None:
                assert destino not in prohibidas, f"{ruta.name} ({capa}) importa de {destino}"
            elif nodo.module:
                assert nodo.module.split(".")[0] not in externas, f"{ruta.name} ({capa}) usa {nodo.module}"
        elif isinstance(nodo, ast.Import):
            for alias in nodo.names:
                assert alias.name.split(".")[0] not in externas, f"{ruta.name} ({capa}) usa {alias.name}"


def test_el_detector_funciona():
    """Si el analizador no viera nada, la prueba anterior sería un falso positivo."""
    assert _capa(RAIZ / "dominio" / "reglas.py") == "dominio"
    assert _capa(RAIZ / "adaptadores" / "salida" / "sqlite" / "conexion.py") == "adaptadores/salida"
    nodo = ast.parse("from ....aplicacion.puertos.llm import X").body[0]
    destino = _destino_en_proyecto(RAIZ / "adaptadores" / "salida" / "llm" / "openai_compat.py", nodo)
    assert destino == "aplicacion"
    nodo = ast.parse("from ...dominio import reglas").body[0]
    assert _destino_en_proyecto(RAIZ / "aplicacion" / "casos_uso" / "banco.py", nodo) == "dominio"
