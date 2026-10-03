"""Demo + batería de pruebas contra la app en marcha (http://localhost:8000).

Uso:
    source .venv/bin/activate
    uvicorn backend.main:app          # en otra terminal
    python pruebas/demo_pruebas.py    # escribe pruebas/resultados.json

No modifica la BD: el Bizum de la demo se cancela antes de ejecutarse.
"""
from backend.adaptadores.salida.sqlite.perfiles import contrasena_demo
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
from backend.adaptadores.salida.sqlite.consultor import ConsultorMovimientosSqlite  # noqa: E402
from backend.aplicacion.casos_uso.banco import ConsultarMovimientos  # noqa: E402
from backend.dominio.errores import ErrorDeDominio  # noqa: E402
from backend.dominio.modelos import Cliente  # noqa: E402

CLAVES = AjustesJson().cargar().claves

class _AuditoriaNula:
    def registrar(self, *_):
        pass


_consultar = ConsultarMovimientos(ConsultorMovimientosSqlite(BaseDeDatos()), _AuditoriaNula())
CLIENTES = {
    "alex": Cliente(1, "alex", "Alex García", "611000111"),
    "ana": Cliente(2, "ana", "Ana Ruiz", "622000222"),
}


def ejecutar_select(sql, cliente="alex"):
    """Misma ruta que usa el LLM (validación del dominio + copia aislada del cliente)."""
    try:
        r = _consultar(CLIENTES[cliente], sql)
    except ErrorDeDominio as e:
        return {"ok": False, "error": e.mensaje}
    return {"ok": True, "filas": r.filas}

BASE = "http://localhost:8000"
# Groq gratis: ~8.000 tokens/min por modelo; sin pausa, 4 mensajes seguidos agotan la cadena
PAUSA_CHAT = 40  # un turno con gráfico gasta ~10.000 tokens y el plan gratuito de Groq permite 8.000 por minuto
RESULTADOS = []


def registrar(grupo, nombre, ok, detalle="", ms=None, extra=None):
    RESULTADOS.append({"grupo": grupo, "nombre": nombre, "ok": bool(ok), "detalle": detalle, "ms": ms, **(extra or {})})
    marca = "✅" if ok else "❌"
    print(f"{marca} [{grupo}] {nombre} {f'({ms} ms)' if ms else ''} {detalle[:120]}")


COOKIES = None  # sesión iniciada por main()


def chat(sesion, mensaje):
    """Envía un mensaje y recoge los eventos SSE. Devuelve dict con texto, herramientas, gráficos…"""
    r = {"texto": "", "herramientas": [], "graficos": [], "avisos": [], "errores": [], "primer_token_ms": None}
    t0 = time.perf_counter()
    with httpx.stream("POST", f"{BASE}/chat", json={"session_id": sesion, "mensaje": mensaje}, cookies=COOKIES, timeout=120) as resp:
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
    global COOKIES
    cli = httpx.Client(base_url=BASE, timeout=60)

    # ── Acceso: sin sesión no se entra; con sesión, cada cliente ve lo suyo ──
    for metodo, ruta in [("GET", "/api/banco/saldo"), ("GET", "/estado"), ("GET", "/ajustes"), ("POST", "/chat")]:
        r = cli.request(metodo, ruta, json={})
        registrar("Seguridad", f"Sin sesión: {metodo} {ruta} → 401", r.status_code == 401, f"HTTP {r.status_code}")
    r = cli.post("/auth/login", json={"usuario": "alex", "contrasena": "incorrecta"})
    registrar("Seguridad", "Contraseña incorrecta rechazada (mensaje genérico)", r.status_code == 401 and "incorrectos" in r.json()["detail"], r.json()["detail"])
    r = cli.post("/auth/login", json={"usuario": "alex", "contrasena": contrasena_demo("alex")})
    cookie = r.headers.get("set-cookie", "").lower()
    registrar("Seguridad", "Login correcto con cookie HttpOnly + SameSite=Strict", r.status_code == 200 and "httponly" in cookie and "samesite=strict" in cookie, cookie[:60] + "…")
    COOKIES = cli.cookies
    otro = httpx.Client(base_url=BASE, timeout=60)
    for _ in range(5):
        r5 = otro.post("/auth/login", json={"usuario": "usuario-inexistente", "contrasena": "x"})
    registrar("Seguridad", "Bloqueo temporal tras 5 intentos fallidos (429)", r5.status_code == 429, r5.json()["detail"])
    r = otro.post("/auth/login", json={"usuario": "ana", "contrasena": contrasena_demo("ana")})
    ana = httpx.Client(base_url=BASE, timeout=60, cookies=otro.cookies)
    saldo_alex, saldo_ana = cli.get("/api/banco/saldo").json(), ana.get("/api/banco/saldo").json()
    registrar("Seguridad", "Cada cliente ve su propia cuenta", saldo_alex["titular"] == "Alex García" and saldo_ana["titular"] == "Ana Ruiz",
              f"{saldo_alex['titular']} {saldo_alex['saldo']} € · {saldo_ana['titular']} {saldo_ana['saldo']} €")
    for sql in ["SELECT * FROM main.movimientos", "WITH movimientos AS (SELECT * FROM main.movimientos) SELECT * FROM movimientos"]:
        propios = ejecutar_select("SELECT COUNT(*) FROM movimientos", "ana")["filas"][0][0]
        res = ejecutar_select(sql, "ana")
        ok = res["ok"] and all("María López" not in str(f) and "Alex" not in str(f) for f in res["filas"])
        registrar("Seguridad", f"Aislamiento SQL: «{sql[:48]}…» no ve datos de otros", ok, f"Ana tiene {propios} movimientos")
    for sql in ["SELECT hash_contrasena FROM clientes", "SELECT name FROM sqlite_master"]:
        res = ejecutar_select(sql, "ana")
        registrar("Seguridad", f"Aislamiento SQL: {sql} bloqueado", not res["ok"], str(res.get("error", ""))[:80])
    saldo_antes_otp = cli.get("/api/banco/saldo").json()["saldo"]
    op = cli.post("/api/banco/bizum", json={"destinatario": "María", "importe": 7}).json()
    registrar("Seguridad", "Bizum solo queda pendiente (no mueve dinero sin OTP)", op.get("estado") == "pendiente_de_confirmacion" and cli.get("/api/banco/saldo").json()["saldo"] == saldo_antes_otp, f"operación {op.get('operacion', {}).get('id')}")
    sms = cli.get("/movil/mensajes").json()
    registrar("Seguridad", "El código llega solo al móvil simulado, no en la respuesta", bool(sms) and "Código de confirmación" in sms[0]["texto"] and "Código de confirmación" not in json.dumps(op), sms[0]["texto"][:70] if sms else "")
    id_op = op["operacion"]["id"]
    mala = cli.post(f"/operaciones/{id_op}/confirmar", json={"codigo": "000000"})
    registrar("Seguridad", "Código incorrecto rechazado", mala.status_code == 422 and "Te quedan" in mala.json()["detail"], mala.json()["detail"])
    ajena = ana.post(f"/operaciones/{id_op}/confirmar", json={"codigo": "000000"})
    registrar("Seguridad", "Otro cliente no puede tocar mi operación (404)", ajena.status_code == 404, f"HTTP {ajena.status_code}")
    cli.post(f"/operaciones/{id_op}/cancelar")
    registrar("Seguridad", "Saldo intacto tras cancelar el Bizum", cli.get("/api/banco/saldo").json()["saldo"] == saldo_antes_otp)
    r = cli.post(f"/operaciones/{id_op}/confirmar", json={"codigo": "000000"})
    registrar("Códigos HTTP", "Confirmar una operación ya cancelada → 409", r.status_code == 409, r.json()["detail"])

    # ── Códigos de error: cada caso, su código ───────────────────────────
    casos = [
        ("JSON roto → 400", lambda: cli.post("/api/banco/bizum", content=b"{roto", headers={"Content-Type": "application/json"}), 400),
        ("Importe no numérico → 422", lambda: cli.post("/api/banco/bizum", json={"destinatario": "María", "importe": "mucho"}), 422),
        ("Importe por encima del tope → 422", lambda: cli.post("/api/banco/bizum", json={"destinatario": "María", "importe": 5000}), 422),
        ("Contacto inexistente → 404", lambda: cli.post("/api/banco/bizum", json={"destinatario": "Nadie", "importe": 5}), 404),
        ("Saldo insuficiente → 409", lambda: ana.post("/api/banco/bizum", json={"destinatario": "Mamá", "importe": 900}), 409),
        ("Operación inventada → 404", lambda: cli.post("/operaciones/inventada/confirmar", json={"codigo": "123456"}), 404),
        ("Ruta inexistente → 404", lambda: cli.get("/api/no-existe"), 404),
        ("Método incorrecto → 405", lambda: cli.delete("/api/banco/saldo"), 405),
        ("Escritura desde otro origen → 403", lambda: cli.post("/api/banco/bizum", json={"destinatario": "María", "importe": 1}, headers={"Origin": "https://sitio-malicioso.example"}), 403),
        ("Mensaje de chat demasiado largo → 413", lambda: cli.post("/chat", json={"session_id": "x", "mensaje": "x" * 2000}), 413),
        ("Mensaje de chat vacío → 422", lambda: cli.post("/chat", json={"session_id": "x", "mensaje": "  "}), 422),
        ("Fichero que no es audio → 415", lambda: cli.post("/stt", files={"audio": ("nota.txt", b"hola" * 2000, "text/plain")}), 415),
    ]
    for nombre, peticion, esperado in casos:
        r = peticion()
        registrar("Códigos HTTP", nombre, r.status_code == esperado, f"HTTP {r.status_code} · {str(r.json().get('detail', ''))[:70]}")
    uso0 = cli.get("/api/uso").json()
    registrar("Uso de la IA", "GET /api/uso informa del gasto y los límites", uso0["limite_dia"] > 0 and "ultimos" in uso0,
              f"{uso0['tokens_hoy']} / {uso0['limite_dia']} tokens hoy · tope por pregunta {uso0['por_turno']}")

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
    malo = cli.post("/ajustes/probar", json={"proveedor": "groq", "api_key": "clave-falsa-para-probar"}).json()
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
    uso1 = cli.get("/api/uso").json()
    reales = [u for u in uso1["ultimos"] if not u["estimado"]]
    registrar("Uso de la IA", "El gasto de tokens se mide con el dato REAL del proveedor", uso1["tokens_hoy"] > uso0["tokens_hoy"] and bool(reales),
              f"{uso1['tokens_hoy'] - uso0['tokens_hoy']} tokens en las pruebas de chat · {len(reales)}/{len(uso1['ultimos'])} llamadas con uso real")

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
