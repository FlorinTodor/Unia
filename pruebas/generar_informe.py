"""Genera docs/estado.html a partir de pruebas/resultados.json (+ el audio de la demo).

    python pruebas/demo_pruebas.py && python pruebas/generar_informe.py
"""
import base64
import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
datos = json.loads((AQUI / "resultados.json").read_text(encoding="utf-8"))
wav = AQUI / "demo_voz.wav"
datos["audio"] = "data:audio/wav;base64," + base64.b64encode(wav.read_bytes()).decode() if wav.exists() else None

plantilla = (AQUI / "plantilla_informe.html").read_text(encoding="utf-8")
html = "<!doctype html>\n" + plantilla.replace("/*__DATOS__*/null", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
salida = AQUI.parent / "docs" / "estado.html"
salida.write_text(html, encoding="utf-8")
print(f"→ {salida} ({len(html) // 1024} KB)")
