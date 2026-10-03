"""Demo + batería de pruebas contra la app en marcha (http://localhost:8000).

Uso:
    source .venv/bin/activate
    uvicorn backend.main:app          # en otra terminal
    python pruebas/demo_pruebas.py    # escribe pruebas/resultados.json

No modifica la BD: el Bizum de la demo se cancela antes de ejecutarse.
"""
import io
import json
import sqlite3
import sys
import time
import uuid
import wave
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.adaptadores.salida.persistencia.ajustes_json import AjustesJson  # noqa: E402
from backend.adaptadores.salida.sqlite.conexion import RUTA_DB, BaseDeDatos  # noqa: E402
from backend.adaptadores.salida.sqlite.repositorios import ConsultorMovimientosSqlite  # noqa: E402
from backend.aplicacion.casos_uso.banco import ConsultarMovimientos  # noqa: E402
from backend.dominio.errores import ErrorDeDominio  # noqa: E402

CLAVES = AjustesJson().cargar().claves
_consultar = ConsultarMovimientos(ConsultorMovimientosSqlite(BaseDeDatos()))


def ejecutar_select(sql):
    """Misma ruta que usa el LLM (validación del dominio + conexión de solo lectura)."""
    try:
        r = _consultar(sql)
    except ErrorDeDominio as e:
        return {"ok": False, "error": e.mensaje}
    return {"ok": True, "filas": r.filas}

BASE = "http://localhost:8000"
# Groq gratis: ~8.000 tokens/min por modelo; sin pausa, 4 mensajes seguidos agotan la cadena
PAUSA_CHAT = 20
RESULTADOS = []


def registrar(grupo, nombre, ok, detalle="", ms=None, extra=None):
    RESULTADOS.append({"grupo": grupo, "nombre": nombre, "ok": bool(ok), "detalle": detalle, "ms": ms, **(extra or {})})
    marca = "✅" if ok else "❌"
    print(f"{marca} [{grupo}] {nombre} {f'({ms} ms)' if ms else ''} {detalle[:120]}")


def chat(sesion, mensaje):
    """Envía un mensaje y recoge los eventos SSE. Devuelve dict con texto, herramientas, gráficos…"""
    r = {"texto": "", "herramientas": [], "graficos": [], "avisos": [], "errores": [], "primer_token_ms": None}
    t0 = time.perf_counter()
    with httpx.stream("POST", f"{BASE}/chat", json={"session_id": sesion, "mensaje": mensaje}, timeout=120) as resp:
        for linea in resp.iter_lines():
            if not linea.startswith("data: "):
                continue
            ev = json.loads(linea[6:])
            tipo, dato = ev["tipo"], ev["dato"]
            if tipo == "delta" and r["primer_token_ms"] is None:
                r["primer_token_ms"] = round((time.perf_counter() - t0) * 1000)
            if tipo == "herramienta":
                r["herramientas"].append(dato)
            elif tipo == "grafico":
                r["graficos"].append(dato)
            elif tipo == "aviso":
                r["avisos"].append(dato)
            elif tipo == "error":
                r["errores"].append(dato)
            elif tipo == "fin":
                r["texto"] = dato
    r["total_ms"] = round((time.perf_counter() - t0) * 1000)
    return r


def prueba_chat(nombre, mensaje, comprobar, sesion=None):
    sesion = sesion or f"demo-{uuid.uuid4().hex[:6]}"
    time.sleep(PAUSA_CHAT)
    try:
        r = chat(sesion, mensaje)
        ok, motivo = comprobar(r)
        registrar(
            "Chat", nombre, ok and not r["errores"], motivo or "; ".join(r["errores"]), r["total_ms"],
            {"pregunta": mensaje, "respuesta": r["texto"], "herramientas": r["herramientas"],
             "graficos": [{"titulo": g.get("titulo"), "tipo": g.get("config", {}).get("type"),
                           "config": g.get("config")} for g in r["graficos"]],
             "avisos": r["avisos"], "primer_token_ms": r["primer_token_ms"]},
        )
    except Exception as e:  # noqa: BLE001
        registrar("Chat", nombre, False, f"excepción: {e}")
    return sesion


def main():
    cli = httpx.Client(base_url=BASE, timeout=60)

    # ── Servidor y configuración ─────────────────────────────────────────
    t = time.perf_counter()
    est = cli.get("/estado").json()
    registrar("Servidor", "GET /estado responde", est.get("ok"), f"modelo {est.get('modelo')} · cadena {est.get('cadena_fallback')}",
              round((time.perf_counter() - t) * 1000), {"estado": est})
    registrar("Servidor", "Página principal servida", cli.get("/").status_code == 200)
    aj = cli.get("/ajustes").json()
    claves_reales = [c.api_key for c in CLAVES.values()]
    sin_claves = all("••••" in c["mascara"] for c in aj["claves"]) and not any(k in json.dumps(aj) for k in claves_reales)
    registrar("Ajustes", "Las claves API nunca salen en claro", sin_claves, f"{len(aj['claves'])} clave(s) enmascarada(s)")
    registrar("Ajustes", "Catálogo de proveedores", len(aj["catalogo"]) >= 5, ", ".join(c["nombre"] for c in aj["catalogo"]))
    t = time.perf_counter()
    pr = cli.post("/ajustes/probar", json={"proveedor": "groq", "api_key": CLAVES["groq"].api_key}).json()
    registrar("Ajustes", "Validar clave Groq (sin gastar cuota)", pr.get("ok"), pr.get("mensaje", ""), round((time.perf_counter() - t) * 1000))
    malo = cli.post("/ajustes/probar", json={"proveedor": "groq", "api_key": "gsk_clave_falsa_123456"}).json()
    registrar("Ajustes", "Clave falsa rechazada con mensaje claro", not malo.get("ok"), malo.get("mensaje", ""))

    # ── API bancaria ficticia ────────────────────────────────────────────
    saldo = cli.get("/api/banco/saldo").json()
    registrar("API banco", "GET /api/banco/saldo", "saldo" in saldo, f"{saldo.get('saldo')} € · {saldo.get('titular')}", extra={"saldo": saldo})
    contactos = cli.get("/api/banco/contactos").json()
    registrar("API banco", "GET /api/banco/contactos", len(contactos) > 0, ", ".join(c["nombre"] for c in contactos))
    movs = cli.get("/api/banco/movimientos", params={"limite": 5}).json()
    registrar("API banco", "GET /api/banco/movimientos", movs.get("ok") and movs["num_filas"] > 0,
              f"{movs.get('num_filas')} filas · columnas {movs.get('columnas')}", extra={"movimientos": movs})

    # ── Base de datos y seguridad NL→SQL ─────────────────────────────────
    con = sqlite3.connect(f"file:{RUTA_DB}?mode=ro", uri=True)
    n, desde, hasta = con.execute("SELECT COUNT(*), MIN(fecha), MAX(fecha) FROM movimientos").fetchone()
    cats = con.execute("SELECT categoria, ROUND(SUM(importe),2) FROM movimientos GROUP BY categoria ORDER BY 2").fetchall()
    con.close()
    registrar("Base de datos", "Movimientos ficticios generados", n > 100, f"{n} movimientos del {desde} al {hasta}",
              extra={"categorias": cats})
    for sql in ["DELETE FROM movimientos", "SELECT 1; DROP TABLE cuenta", "UPDATE cuenta SET saldo = 1e9",
                "WITH x AS (SELECT 1) INSERT INTO movimientos VALUES (1)", "PRAGMA writable_schema=1"]:
        res = ejecutar_select(sql)
        registrar("Seguridad SQL", f"Bloquea: {sql}", not res["ok"], str(res.get("error", res))[:100])
    res = ejecutar_select("SELECT categoria, SUM(importe) FROM movimientos GROUP BY categoria")
    registrar("Seguridad SQL", "Permite SELECT de agregación", res["ok"], f"{len(res.get('filas', []))} filas")
    res = ejecutar_select("SELECT * FROM movimientos")
    registrar("Seguridad SQL", "Tope de 60 filas", len(res.get("filas", [])) <= 60, f"{len(res.get('filas', []))} filas devueltas")

    # ── Chat con el agente (LLM real) ────────────────────────────────────
    prueba_chat("Consulta de saldo", "¿Cuánto dinero tengo?",
                lambda r: ("consultar_saldo" in r["herramientas"] and "€" in r["texto"], ""))
    prueba_chat("Pregunta en lenguaje natural → SQL", "¿Cuánto gasté en supermercados el mes pasado?",
                lambda r: ("consultar_movimientos" in r["herramientas"] and any(c.isdigit() for c in r["texto"]), ""))
    prueba_chat("Último movimiento", "¿Cuál fue mi último movimiento?",
                lambda r: ("consultar_movimientos" in r["herramientas"], ""))
    prueba_chat("Gráfico autónomo (categorías)", "Hazme un gráfico de mis gastos por categoría de los últimos 3 meses",
                lambda r: (len(r["graficos"]) > 0, f"tipo elegido por el LLM: {[g['config'].get('type') for g in r['graficos']]}"))
    prueba_chat("Gráfico autónomo (evolución)", "¿Cómo ha evolucionado mi gasto mensual este año?",
                lambda r: (len(r["graficos"]) > 0, f"tipo elegido por el LLM: {[g['config'].get('type') for g in r['graficos']]}"))
    saldo_antes = cli.get("/api/banco/saldo").json()["saldo"]
    s = prueba_chat("Bizum: pide confirmación antes de enviar", "Envíale 15 € a María por la cena",
                    lambda r: ("transferencia_bizum" not in r["herramientas"] and "?" in r["texto"], "no envía sin confirmar"))
    prueba_chat("Bizum: cancelar con «no»", "No, déjalo, no lo envíes",
                lambda r: ("transferencia_bizum" not in r["herramientas"], ""), sesion=s)
    saldo_despues = cli.get("/api/banco/saldo").json()["saldo"]
    registrar("Chat", "Saldo intacto tras cancelar", saldo_antes == saldo_despues, f"{saldo_antes} € → {saldo_despues} €")
    prueba_chat("Fuera de ámbito (se reconduce)", "Recomiéndame un libro de misa",
                lambda r: (not r["herramientas"], ""))

    # ── Voz: Piper (TTS) → Whisper (STT), ida y vuelta ───────────────────
    frase = "¿Cuánto gasté en restaurantes en agosto?"
    t = time.perf_counter()
    wav_resp = cli.post("/tts", json={"texto": frase})
    ms_tts = round((time.perf_counter() - t) * 1000)
    ok_wav = wav_resp.status_code == 200 and wav_resp.content[:4] == b"RIFF"
    dur = 0
    if ok_wav:
        with wave.open(io.BytesIO(wav_resp.content)) as w:
            dur = round(w.getnframes() / w.getframerate(), 2)
        Path(__file__).with_name("demo_voz.wav").write_bytes(wav_resp.content)
    registrar("Voz", "TTS Piper (texto → audio)", ok_wav, f"{dur} s de audio, {len(wav_resp.content)//1024} KB", ms_tts)
    if ok_wav:
        t = time.perf_counter()
        st = cli.post("/stt", files={"audio": ("demo.wav", wav_resp.content, "audio/wav")})
        texto = st.json().get("texto", st.text) if st.status_code == 200 else st.text
        parecido = "restaurantes" in texto.lower() and "agosto" in texto.lower()
        registrar("Voz", "STT Whisper (audio → texto), ida y vuelta", parecido, f"«{frase}» → «{texto}»",
                  round((time.perf_counter() - t) * 1000))
    corto = cli.post("/stt", files={"audio": ("x.webm", b"\x00" * 500, "audio/webm")})
    registrar("Voz", "Audio vacío rechazado (anti-alucinación)", corto.status_code == 422, corto.json().get("detail", ""))

    salida = Path(__file__).with_name("resultados.json")
    salida.write_text(json.dumps({"fecha": time.strftime("%Y-%m-%d %H:%M"), "resultados": RESULTADOS}, ensure_ascii=False, indent=1))
    ok = sum(r["ok"] for r in RESULTADOS)
    print(f"\n{ok}/{len(RESULTADOS)} pruebas OK → {salida}")


if __name__ == "__main__":
    main()
