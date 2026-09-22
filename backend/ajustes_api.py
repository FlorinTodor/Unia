"""API del panel ⚙️ Ajustes: alta/baja de claves, modelos, proveedor activo e IA local.

Las claves API nunca salen del servidor: el frontend solo recibe la máscara.
"""
import httpx
from fastapi import APIRouter, HTTPException
from openai import APIConnectionError, APIError, APIStatusError, AuthenticationError, PermissionDeniedError
from pydantic import BaseModel

from . import agente, ajustes
from .config import CATALOGO, cliente_para, get_cliente_stt

router = APIRouter(prefix="/ajustes")

# fragmentos de id de modelos que no sirven para chatear (voz, imagen, embeddings...)
_NO_CHAT = (
    "whisper", "tts", "transcribe", "audio", "realtime", "embed", "moderation", "guard",
    "dall-e", "image", "imagen", "veo", "aqa", "davinci", "babbage", "search", "playai",
    "orpheus", "distil", "ocr",
)


def _listar_modelos(proveedor: str, api_key: str | None = None) -> list[str]:
    """Modelos de chat de la cuenta. Sirve también para validar la clave (no gasta cuota)."""
    modelos = cliente_para(proveedor, api_key, timeout=10).models.list()
    ids = {m.id.removeprefix("models/") for m in modelos.data}  # Gemini antepone "models/"
    return sorted(i for i in ids if not any(x in i.lower() for x in _NO_CHAT))


def _probar(proveedor: str, api_key: str | None = None) -> dict:
    nombre = CATALOGO[proveedor]["nombre"]
    try:
        modelos = _listar_modelos(proveedor, api_key)
    except (AuthenticationError, PermissionDeniedError):
        return {"ok": False, "mensaje": f"{nombre} rechaza la clave: revisa que esté bien copiada."}
    except APIConnectionError:
        return {"ok": False, "mensaje": f"No se pudo conectar con {nombre}. ¿Hay conexión a internet?"}
    except APIStatusError as e:
        if e.status_code == 400:  # Gemini responde 400 «API key not valid»
            return {"ok": False, "mensaje": f"{nombre} rechaza la clave: revisa que esté bien copiada."}
        # el proveedor no permite listar modelos: la clave se comprobará al chatear
        return {"ok": True, "mensaje": "Clave guardada (no se pudo obtener la lista de modelos).", "modelos": []}
    return {"ok": True, "mensaje": f"Clave válida · {len(modelos)} modelos disponibles.", "modelos": modelos}


def _vista() -> dict:
    """Ajustes para el frontend, sin claves en claro."""
    a = ajustes.cargar()
    stt = get_cliente_stt()
    return {
        "activo": a["activo"],
        "configurado": a["activo"] is not None,
        "claves": [
            {
                "proveedor": p,
                "nombre": CATALOGO[p]["nombre"],
                "mascara": ajustes.enmascarar(cfg["api_key"]),
                "modelo": cfg.get("modelo"),
                "modelo_respaldo": cfg.get("modelo_respaldo"),
                "modelos": cfg.get("modelos") or [],
            }
            for p, cfg in a["claves"].items()
            if p in CATALOGO
        ],
        "catalogo": [{"id": p, **{k: v for k, v in c.items() if k != "base_url"}} for p, c in CATALOGO.items()],
        "ollama": {"url": a["ollama_url"], "modelo": a["ollama_modelo"], "fallback_local": a["fallback_local"]},
        "voz_entrada": CATALOGO[_proveedor_stt(a)]["nombre"] if stt else None,
        **agente.info_proveedor(),
    }


def _proveedor_stt(a: dict) -> str:
    return "groq" if "groq" in a["claves"] else "openai"


def _proveedor_valido(proveedor: str) -> None:
    if proveedor not in CATALOGO:
        raise HTTPException(404, f"Proveedor desconocido: {proveedor}")


@router.get("")
def leer():
    a = ajustes.cargar()
    # claves heredadas del .env: se rellena su lista de modelos la primera vez
    pendientes = [p for p, cfg in a["claves"].items() if p in CATALOGO and not cfg.get("modelos")]
    for p in pendientes:
        try:
            a["claves"][p]["modelos"] = _listar_modelos(p)
        except APIError:
            pass
    if pendientes:
        ajustes.guardar(a)
    return _vista()


class PeticionProbar(BaseModel):
    proveedor: str
    api_key: str


@router.post("/probar")
def probar(peticion: PeticionProbar):
    """Valida una clave antes de guardarla y devuelve sus modelos."""
    _proveedor_valido(peticion.proveedor)
    return _probar(peticion.proveedor, peticion.api_key.strip())


class PeticionClave(BaseModel):
    proveedor: str
    api_key: str
    modelo: str | None = None
    modelo_respaldo: str | None = None


@router.post("/claves")
def anadir_clave(peticion: PeticionClave):
    """Añade o reemplaza la clave de un proveedor (solo si el proveedor la acepta)."""
    _proveedor_valido(peticion.proveedor)
    clave = peticion.api_key.strip()
    if not clave:
        raise HTTPException(422, "Escribe una clave API.")
    prueba = _probar(peticion.proveedor, clave)
    if not prueba["ok"]:
        raise HTTPException(422, prueba["mensaje"])
    cat = CATALOGO[peticion.proveedor]
    a = ajustes.cargar()
    a["claves"][peticion.proveedor] = {
        "api_key": clave,
        "modelo": peticion.modelo or cat["modelo"],
        "modelo_respaldo": peticion.modelo_respaldo if peticion.modelo_respaldo is not None else cat["modelo_respaldo"],
        "modelos": prueba["modelos"],
    }
    if a["activo"] is None:
        a["activo"] = peticion.proveedor  # la primera clave se activa sola
    ajustes.guardar(a)
    return {**_vista(), "mensaje": prueba["mensaje"]}


class PeticionModelos(BaseModel):
    modelo: str | None = None
    modelo_respaldo: str | None = None  # "" = sin respaldo


@router.patch("/claves/{proveedor}")
def cambiar_modelos(proveedor: str, peticion: PeticionModelos):
    a = ajustes.cargar()
    if proveedor not in a["claves"]:
        raise HTTPException(404, "No hay clave para ese proveedor.")
    a["claves"][proveedor].update(peticion.model_dump(exclude_none=True))
    ajustes.guardar(a)
    return _vista()


@router.delete("/claves/{proveedor}")
def borrar_clave(proveedor: str):
    a = ajustes.cargar()
    a["claves"].pop(proveedor, None)
    if a["activo"] == proveedor:
        a["activo"] = next(iter(a["claves"]), None)
    ajustes.guardar(a)
    return _vista()


class PeticionActivar(BaseModel):
    proveedor: str


@router.post("/activar")
def activar(peticion: PeticionActivar):
    a = ajustes.cargar()
    if peticion.proveedor != "ollama" and peticion.proveedor not in a["claves"]:
        raise HTTPException(404, "Primero añade una clave para ese proveedor.")
    a["activo"] = peticion.proveedor
    ajustes.guardar(a)
    return _vista()


class PeticionOllama(BaseModel):
    url: str | None = None
    modelo: str | None = None
    fallback_local: bool | None = None


@router.put("/ollama")
def guardar_ollama(peticion: PeticionOllama):
    a = ajustes.cargar()
    if peticion.url is not None:
        a["ollama_url"] = peticion.url.strip().rstrip("/") or "http://localhost:11434/v1"
    if peticion.modelo:
        a["ollama_modelo"] = peticion.modelo
    if peticion.fallback_local is not None:
        a["fallback_local"] = peticion.fallback_local
    ajustes.guardar(a)
    return _vista()


@router.get("/ollama/estado")
def estado_ollama(url: str | None = None):
    """Comprueba si Ollama responde y qué modelos tiene descargados."""
    base = (url or ajustes.cargar()["ollama_url"]).rstrip("/").removesuffix("/v1")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=3)
        r.raise_for_status()
    except httpx.HTTPError:
        return {"ok": False, "mensaje": "Ollama no responde. Arráncalo con «ollama serve».", "modelos": []}
    modelos = sorted(m["name"] for m in r.json().get("models", []))
    if not modelos:
        return {"ok": True, "mensaje": "Ollama funciona, pero no tiene modelos: «ollama pull qwen3:8b».", "modelos": []}
    return {"ok": True, "mensaje": f"Ollama en marcha · {len(modelos)} modelos instalados.", "modelos": modelos}
