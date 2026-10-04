"""Genera docs/REFERENCIA.md y docs/referencia.json leyendo el código: puertos, adaptadores, casos de uso,
herramientas, endpoints, tests y ficheros. Así la referencia nunca se queda desfasada.

    source .venv/bin/activate && python pruebas/generar_referencia.py
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
os.environ["DOCS_API"] = "1"
sys.path.insert(0, str(RAIZ))

# qué adaptador de producción y qué doble de pruebas implementa cada puerto (se comprueba que no falte ninguno)
IMPLEMENTACIONES = {
    "RepositorioCuenta": ("RepositorioCuentaSqlite", "salida/sqlite/repositorios.py", "CuentaEnMemoria"),
    "RepositorioContactos": ("RepositorioContactosSqlite", "salida/sqlite/repositorios.py", "ContactosEnMemoria"),
    "RepositorioTarjetas": ("RepositorioTarjetasSqlite", "salida/sqlite/repositorios.py", "TarjetasEnMemoria"),
    "ConsultorMovimientos": ("ConsultorMovimientosSqlite", "salida/sqlite/consultor.py", "ConsultorFalso"),
    "ProveedorLLM": ("ProveedorLLMOpenAI", "salida/llm/openai_compat.py", "LLMGuionizado"),
    "Transcriptor": ("TranscriptorWhisper", "salida/voz/whisper.py", "TranscriptorFalso (test_http)"),
    "Sintetizador": ("SintetizadorPiper", "salida/voz/piper.py", "SintetizadorFalso (test_http)"),
    "RepositorioSesiones": ("SesionesChatSqlite", "salida/persistencia/sqlite_estado.py", "SesionesEnMemoria"),
    "RepositorioAjustes": ("AjustesJson", "salida/persistencia/ajustes_json.py", "AjustesEnMemoria"),
    "Reloj": ("RelojSistema", "salida/reloj.py", "RelojFijo"),
    "SondaProveedores": ("SondaOpenAI", "salida/llm/sonda.py", "SondaFalsa"),
    "RepositorioClientes": ("RepositorioClientesSqlite", "salida/sqlite/repositorios.py", "ClientesFalsos (test_acceso)"),
    "Hasheador": ("HasheadorScrypt", "salida/seguridad/hasheador.py", "(el real, es rápido de crear)"),
    "SesionesAutenticadas": ("SesionesAutenticadasSqlite", "salida/persistencia/sqlite_estado.py", "SesionesAutenticadasEnMemoria"),
    "RegistroIntentos": ("IntentosEnMemoria", "salida/persistencia/memoria_seguridad.py", "IntentosEnMemoria"),
    "RepositorioOperaciones": ("OperacionesSqlite", "salida/persistencia/sqlite_estado.py", "OperacionesEnMemoria"),
    "GeneradorCodigos": ("GeneradorCodigosSeguro", "salida/seguridad/codigos.py", "CodigosFijos"),
    "CanalOTP": ("MovilSqlite", "salida/persistencia/sqlite_estado.py", "MovilFalso"),
    "BandejaMovil": ("MovilSqlite", "salida/persistencia/sqlite_estado.py", "MovilFalso"),
    "Auditoria": ("AuditoriaSqlite", "salida/sqlite/auditoria.py", "AuditoriaEnMemoria"),
    "RegistroUso": ("UsoSqlite", "salida/sqlite/uso.py", "UsoEnMemoria"),
    "LimitadorPeticiones": ("LimitadorEnMemoria", "salida/persistencia/limitador.py", "LimitadorEnMemoria"),
}

# quién llama a cada caso de uso (herramienta del agente y/o endpoint)
USADO_POR = {
    "ConsultarSaldo": "herramienta consultar_saldo · GET /api/banco/saldo",
    "ListarContactos": "herramienta listar_contactos_bizum · GET /api/banco/contactos",
    "ConsultarMovimientos": "herramienta consultar_movimientos · GET /api/banco/movimientos",
    "SolicitarBizum": "herramienta transferencia_bizum · POST /api/banco/bizum",
    "ConsultarTarjetas": "herramienta consultar_tarjetas · GET /api/banco/tarjetas",
    "BloquearTarjeta": "herramienta bloquear_tarjeta (sin OTP, auditado)",
    "SolicitarDesbloqueoTarjeta": "herramienta desbloquear_tarjeta (operación pendiente de OTP)",
    "DesbloquearTarjeta": "la ejecuta ConfirmarOperacion al confirmar el desbloqueo",
    "ConfirmarOperacion": "POST /operaciones/{id}/confirmar y /aprobar",
    "CancelarOperacion": "POST /operaciones/{id}/cancelar",
    "IniciarSesion": "POST /auth/login",
    "IdentificarCliente": "dependencia de todos los endpoints protegidos",
    "CerrarSesion": "POST /auth/logout",
    "LeerMensajesMovil": "GET /movil/mensajes",
    "TranscribirAudio": "POST /stt",
    "SintetizarVoz": "POST /tts",
    "GestionAjustes": "/ajustes/*",
    "ConsultarEstado": "GET /estado",
    "ConsultarUso": "GET /api/uso",
}


def clases(ruta: Path):
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    return [n for n in arbol.body if isinstance(n, ast.ClassDef)]


def primera_linea(nodo) -> str:
    doc = ast.get_docstring(nodo) or ""
    return doc.strip().splitlines()[0] if doc else ""


def metodos_publicos(clase: ast.ClassDef):
    return [
        (f.name, ast.unparse(f.args).replace("self, ", "").replace("self", ""), ast.unparse(f.returns) if f.returns else "")
        for f in clase.body if isinstance(f, ast.FunctionDef) and not f.name.startswith("_")
    ]


def puertos():
    salida = []
    for fichero in sorted((RAIZ / "backend/aplicacion/puertos").glob("*.py")):
        if fichero.name == "__init__.py":
            continue
        for c in clases(fichero):
            if any(ast.unparse(b) == "Protocol" for b in c.bases):
                impl = IMPLEMENTACIONES.get(c.name)
                if impl is None:
                    raise SystemExit(f"Falta registrar el puerto {c.name} en IMPLEMENTACIONES")
                salida.append({
                    "puerto": c.name, "fichero": f"aplicacion/puertos/{fichero.name}",
                    "metodos": [f"{n}({a})" + (f" → {r}" if r else "") for n, a, r in metodos_publicos(c)],
                    "adaptador": impl[0], "fichero_adaptador": impl[1], "doble": impl[2],
                })
    sobran = set(IMPLEMENTACIONES) - {p["puerto"] for p in salida}
    if sobran:
        raise SystemExit(f"IMPLEMENTACIONES menciona puertos que ya no existen: {sobran}")
    return salida


def casos_de_uso():
    salida = []
    for fichero in sorted((RAIZ / "backend/aplicacion/casos_uso").glob("*.py")):
        if fichero.name == "__init__.py":
            continue
        for c in clases(fichero):
            if c.name.startswith("_") or c.name in {"ResumenUso", "ResultadoPrueba", "EstadoSistema"}:
                continue
            init = next((f for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "__init__"), None)
            dep = [a.annotation.id if isinstance(a.annotation, ast.Name) else ast.unparse(a.annotation)
                   for a in (init.args.args[1:] if init else []) if a.annotation]
            salida.append({"caso": c.name, "fichero": f"aplicacion/casos_uso/{fichero.name}", "puertos": dep,
                           "doc": primera_linea(c), "usado_por": USADO_POR.get(c.name, "—")})
    return salida


def herramientas():
    from backend.aplicacion.herramientas import bizum, contactos, grafico, movimientos, saldo, tarjetas

    salida = []
    for modulo, args in ((saldo, (None,)), (contactos, (None,)), (bizum, (None,)), (movimientos, (None,)), (grafico, ()), (tarjetas, (None, None, None))):
        creadas = modulo.crear(*args)
        for h in creadas if isinstance(creadas, list) else [creadas]:
            salida.append({
                "nombre": h.nombre, "riesgo": h.riesgo.value, "etiqueta": h.etiqueta,
                "fichero": f"aplicacion/herramientas/{modulo.__name__.rsplit('.', 1)[1]}.py", "descripcion": h.esquema.descripcion,
            })
    return salida


def endpoints():
    from backend.main import app

    spec = app.openapi()
    filas = []
    for ruta, ops in spec["paths"].items():
        for metodo, o in ops.items():
            cuerpo = (o.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", "") or "").split("/")[-1]
            ok = o["responses"].get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
            refs = [x["$ref"].split("/")[-1] for x in ok.get("anyOf", []) if "$ref" in x]  # respuesta con varias formas posibles
            respuesta = (ok.get("$ref", "") or "").split("/")[-1] or " o ".join(refs) or ("lista de " + ok["items"]["$ref"].split("/")[-1] if ok.get("items", {}).get("$ref") else "")
            filas.append({
                "metodo": metodo.upper(), "ruta": ruta, "etiqueta": o["tags"][0], "resumen": o["summary"],
                "auth": bool(o.get("security")), "peticion": cuerpo, "respuesta": respuesta or "—",
                "errores": sorted(c for c in o["responses"] if c != "200" and c != "422"),
            })
    return filas, spec


def tests():
    salida = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"], cwd=RAIZ, capture_output=True, text=True).stdout
    por_fichero = {}
    for linea in salida.splitlines():
        m = re.match(r"tests/(test_\w+\.py)::", linea)
        if m:
            por_fichero[m.group(1)] = por_fichero.get(m.group(1), 0) + 1
    return por_fichero


def ficheros():
    """Todos los módulos de código con su número de líneas, agrupados por capa."""
    grupos = {}
    for ruta in sorted(list((RAIZ / "backend").rglob("*.py")) + list((RAIZ / "frontend/js").rglob("*.js"))):
        if ruta.name == "__init__.py":
            continue
        rel = ruta.relative_to(RAIZ).as_posix()
        capa = (rel.split("/")[1] if rel.startswith("backend/") else "frontend/" + rel.split("/")[2] if "/" in rel[len("frontend/js/"):] else "frontend")
        if rel.startswith("backend/adaptadores/"):
            capa = "adaptadores/" + rel.split("/")[2]
        grupos.setdefault(capa, []).append({"fichero": rel, "lineas": len(ruta.read_text(encoding="utf-8").splitlines()), "doc": _doc_modulo(ruta)})
    return grupos


def _doc_modulo(ruta: Path) -> str:
    texto = ruta.read_text(encoding="utf-8")
    if ruta.suffix == ".py":
        d = ast.get_docstring(ast.parse(texto)) or ""
        return d.strip().splitlines()[0] if d else ""
    m = re.match(r"\s*/\*\s*(.+?)(?:\n|\*/)", texto)
    return m.group(1).strip(" *") if m else ""


def variables_entorno():
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
    return re.findall(r"^#?\s*([A-Z_]{4,})=([^\s#]*)\s*(?:#\s*(.*))?$", texto, re.M)


def main():
    filas, spec = endpoints()
    datos = {
        "puertos": puertos(), "casos_uso": casos_de_uso(), "herramientas": herramientas(), "endpoints": filas,
        "tests": tests(), "ficheros": ficheros(), "entorno": variables_entorno(),
    }
    (RAIZ / "docs/referencia.json").write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = ["# Referencia del código (generada)", "",
          "Generada por `pruebas/generar_referencia.py` leyendo el código. No se edita a mano.", ""]
    md += [f"## Puertos ({len(datos['puertos'])})", "", "| Puerto | Fichero | Métodos | Adaptador | Doble de pruebas |", "|---|---|---|---|---|"]
    for p in datos["puertos"]:
        md.append(f"| `{p['puerto']}` | `{p['fichero']}` | {'<br>'.join('`' + m.replace('|', '∣') + '`' for m in p['metodos'])} | `{p['adaptador']}` (`{p['fichero_adaptador']}`) | `{p['doble']}` |")
    md += ["", f"## Casos de uso ({len(datos['casos_uso'])})", "", "| Caso de uso | Fichero | Puertos que usa | Lo llama |", "|---|---|---|---|"]
    for c in datos["casos_uso"]:
        md.append(f"| `{c['caso']}` | `{c['fichero']}` | {', '.join('`' + p + '`' for p in c['puertos']) or '—'} | {c['usado_por']} |")
    md += ["", f"## Herramientas del agente ({len(datos['herramientas'])})", "", "| Herramienta | Riesgo | Fichero | Estado en pantalla |", "|---|---|---|---|"]
    for h in datos["herramientas"]:
        md.append(f"| `{h['nombre']}` | {h['riesgo']} | `{h['fichero']}` | {h['etiqueta']} |")
    md += ["", f"## Endpoints ({len(datos['endpoints'])})", "", "| Método | Ruta | Auth | Petición | Respuesta | Errores |", "|---|---|---|---|---|---|"]
    for e in datos["endpoints"]:
        md.append(f"| {e['metodo']} | `{e['ruta']}` | {'sí' if e['auth'] else 'no'} | {e['peticion'] or '—'} | {e['respuesta']} | {', '.join(e['errores']) or '—'} |")
    md += ["", f"## Tests ({sum(datos['tests'].values())})", "", "| Fichero | Pruebas |", "|---|---|"]
    md += [f"| `tests/{f}` | {n} |" for f, n in sorted(datos["tests"].items())]
    (RAIZ / "docs/REFERENCIA.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"{len(datos['puertos'])} puertos · {len(datos['casos_uso'])} casos de uso · {len(datos['herramientas'])} herramientas · "
          f"{len(datos['endpoints'])} endpoints · {sum(datos['tests'].values())} tests · {sum(len(v) for v in datos['ficheros'].values())} módulos")


if __name__ == "__main__":
    main()
