"""Exporta la especificación OpenAPI a docs/openapi.json (sin arrancar el servidor).

    source .venv/bin/activate && python pruebas/exportar_openapi.py

Sirve para la memoria técnica y para importarla en Postman, Insomnia o un generador de clientes.
"""
import json
import os
import sys
from pathlib import Path

os.environ["DOCS_API"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.main import app  # noqa: E402

destino = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"
destino.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{len(app.openapi()['paths'])} rutas → {destino}")
