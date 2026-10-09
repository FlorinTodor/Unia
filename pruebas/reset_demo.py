"""Deja la app «como nueva» antes de una defensa o una demo en directo.

Cuándo usarlo: justo antes de enseñar la app delante de alguien, cuando la base de datos arrastra Bizum de prueba,
tarjetas bloqueadas, operaciones pendientes, SMS del móvil simulado o conversaciones de ensayos anteriores.

Qué hace (solo con `--si`; sin él dice qué haría y sale sin tocar nada):
  1. Comprueba que no hay ningún servidor usando la base: si responde algo en los puertos 8000–8004 (el del usuario y
     los de prueba, que comparten `data/banco.db`), en 127.0.0.1 o en ::1, o si `fuser` dice que algún proceso tiene
     abierto el fichero, aborta. No mata nada: páralo tú. `--puerto N` (repetible) cambia los puertos vigilados.
  2. Copia `data/banco.db` a `data/banco.db.copia-AAAAMMDD-HHMMSS` (con sufijo -2, -3… si ya existe: nunca sobrescribe
     una copia anterior; las copias no se borran nunca: bórralas tú si sobran).
  3. Regenera la base con el mismo esquema y los mismos adaptadores que usa el servidor (`esquema.inicializar(...,
     forzar=True)`): clientes `alex`, `ana`, `marta`, `jose` (y `admin` si hay `CONTRASENA_ADMIN` en `.env`) con sus
     contraseñas, movimientos, contactos y tarjetas activas; sin sesiones de login, operaciones pendientes, SMS,
     conversaciones ni consumo de tokens. OJO: se pierden los Bizum hechos desde el chat (por eso la copia).
  4. Con `--ajustes`, restablece los ajustes de la IA: aparta `data/ajustes.json` a `ajustes.json.copia-…` y la app
     vuelve a los valores por defecto del `.env` (proveedor, modelos, Ollama).

Uso:
    source .venv/bin/activate
    python pruebas/reset_demo.py                 # simulacro: qué haría
    python pruebas/reset_demo.py --si            # lo hace
    python pruebas/reset_demo.py --si --ajustes  # también los ajustes de la IA
Después, arranca uvicorn como siempre e inicia sesión de nuevo (las sesiones anteriores ya no valen).
"""
import argparse
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from dotenv import load_dotenv  # noqa: E402

from backend.adaptadores.salida.persistencia.ajustes_json import RUTA_AJUSTES  # noqa: E402
from backend.adaptadores.salida.reloj import RelojSistema  # noqa: E402
from backend.adaptadores.salida.seguridad.hasheador import HasheadorScrypt  # noqa: E402
from backend.adaptadores.salida.sqlite import esquema  # noqa: E402
from backend.adaptadores.salida.sqlite.conexion import RUTA_DB, BaseDeDatos  # noqa: E402

PUERTOS_SERVIDOR = (8000, 8001, 8002, 8003, 8004)  # el del usuario y los de prueba: todos abren data/banco.db


def cargar_entorno() -> None:
    """Mismo `.env` que el servidor: así las contraseñas (`CONTRASENA_<USUARIO>`, `CONTRASENA_ADMIN`) coinciden."""
    load_dotenv(RAIZ / ".env")


def servidor_en_marcha(puerto: int) -> bool:
    """¿Hay algo escuchando en el puerto (IPv4 o IPv6)? Con uvicorn en marcha seguiría escribiendo en la base regenerada."""
    for familia, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(familia, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, puerto)) == 0:
                    return True
        except OSError:  # sin IPv6 en esta máquina: no hay nada que comprobar ahí
            continue
    return False


def procesos_con_la_bd(ruta: Path) -> str:
    """PIDs que tienen abierto el fichero según `fuser` (solo lo consulta); "" si nadie o si no hay `fuser`."""
    if not ruta.exists() or shutil.which("fuser") is None:
        return ""
    try:
        r = subprocess.run(["fuser", str(ruta)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def ruta_copia(ruta: Path, sello: str) -> Path:
    """Destino libre para la copia: nunca pisa una anterior (dos ejecuciones en el mismo segundo → -2, -3…)."""
    destino, n = ruta.with_name(f"{ruta.name}.copia-{sello}"), 1
    while destino.exists():
        n += 1
        destino = ruta.with_name(f"{ruta.name}.copia-{sello}-{n}")
    return destino


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Deja la base de datos de la demo como nueva (ver docstring).")
    p.add_argument("--si", action="store_true", help="hacerlo de verdad (sin esto solo se describe)")
    p.add_argument("--ajustes", action="store_true", help="restablecer también los ajustes de la IA (data/ajustes.json)")
    p.add_argument("--bd", type=Path, default=RUTA_DB, help=f"base de datos (por defecto {RUTA_DB})")
    p.add_argument("--ruta-ajustes", type=Path, default=RUTA_AJUSTES, help=argparse.SUPPRESS)
    p.add_argument("--puerto", type=int, action="append",
                   help=f"puerto de un servidor que debe estar parado (repetible; por defecto {', '.join(map(str, PUERTOS_SERVIDOR))})")
    args = p.parse_args(argv)
    puertos = args.puerto or PUERTOS_SERVIDOR

    sello = datetime.now().strftime("%Y%m%d-%H%M%S")
    copia_bd = ruta_copia(args.bd, sello)
    copia_ajustes = ruta_copia(args.ruta_ajustes, sello)
    tocar_ajustes = args.ajustes and args.ruta_ajustes.exists()

    ocupados = [puerto for puerto in puertos if servidor_en_marcha(puerto)]
    if ocupados:
        print(f"ABORTADO: algo responde en el puerto {', '.join(map(str, ocupados))}. Para uvicorn antes de reiniciar la demo "
              "(este script no mata ningún proceso).", file=sys.stderr)
        return 2
    pids = procesos_con_la_bd(args.bd)
    if pids:
        print(f"ABORTADO: {args.bd} está abierta por el proceso {pids}. Ciérralo antes de reiniciar la demo.", file=sys.stderr)
        return 2

    print("Reinicio de la demo:")
    print(f"  · copiar {args.bd} → {copia_bd}" if args.bd.exists() else f"  · {args.bd} no existe: no hay nada que copiar")
    print(f"  · regenerar {args.bd} (clientes de demo con sus movimientos; sin sesiones, operaciones, SMS ni conversaciones)")
    if args.ajustes:
        print(f"  · apartar {args.ruta_ajustes} → {copia_ajustes} (vuelven los ajustes del .env)" if tocar_ajustes
              else f"  · {args.ruta_ajustes} no existe: los ajustes ya son los de por defecto")
    if not args.si:
        print("Simulacro: no se ha tocado nada. Repite con --si para hacerlo.")
        return 0

    cargar_entorno()
    if args.bd.exists():
        shutil.copy2(args.bd, copia_bd)
    esquema.inicializar(BaseDeDatos(args.bd), RelojSistema(), HasheadorScrypt(), forzar=True)
    if tocar_ajustes:
        args.ruta_ajustes.rename(copia_ajustes)  # se aparta, no se borra: las claves API siguen en la copia
    print("Hecho. Arranca uvicorn e inicia sesión de nuevo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
