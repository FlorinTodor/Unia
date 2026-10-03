"""Panel ⚙️ Ajustes: alta/baja de claves, modelos, proveedor activo e IA local."""
from fastapi import APIRouter
from pydantic import BaseModel

from ....aplicacion.casos_uso.ajustes import GestionAjustes
from . import presentadores


class PeticionProbar(BaseModel):
    proveedor: str
    api_key: str


class PeticionClave(BaseModel):
    proveedor: str
    api_key: str
    modelo: str | None = None
    modelo_respaldo: str | None = None


class PeticionModelos(BaseModel):
    modelo: str | None = None
    modelo_respaldo: str | None = None  # "" = sin respaldo


class PeticionActivar(BaseModel):
    proveedor: str


class PeticionOllama(BaseModel):
    url: str | None = None
    modelo: str | None = None
    fallback_local: bool | None = None


def crear_router(ajustes: GestionAjustes) -> APIRouter:
    router = APIRouter(prefix="/ajustes", tags=["ajustes"])
    vista = presentadores.vista_ajustes

    @router.get("")
    def leer():
        return vista(ajustes.leer())

    @router.post("/probar")
    def probar(peticion: PeticionProbar):
        """Valida una clave antes de guardarla y devuelve sus modelos."""
        r = ajustes.probar_clave(peticion.proveedor, peticion.api_key)
        return {"ok": r.ok, "mensaje": r.mensaje, "modelos": r.modelos}

    @router.post("/claves")
    def anadir_clave(peticion: PeticionClave):
        resultado, mensaje = ajustes.anadir_clave(
            peticion.proveedor, peticion.api_key, peticion.modelo, peticion.modelo_respaldo
        )
        return {**vista(resultado), "mensaje": mensaje}

    @router.patch("/claves/{proveedor}")
    def cambiar_modelos(proveedor: str, peticion: PeticionModelos):
        return vista(ajustes.cambiar_modelos(proveedor, peticion.modelo, peticion.modelo_respaldo))

    @router.delete("/claves/{proveedor}")
    def borrar_clave(proveedor: str):
        return vista(ajustes.borrar_clave(proveedor))

    @router.post("/activar")
    def activar(peticion: PeticionActivar):
        return vista(ajustes.activar(peticion.proveedor))

    @router.put("/ollama")
    def guardar_ollama(peticion: PeticionOllama):
        return vista(ajustes.configurar_ollama(peticion.url, peticion.modelo, peticion.fallback_local))

    @router.get("/ollama/estado")
    def estado_ollama(url: str | None = None):
        """Comprueba si Ollama responde y qué modelos tiene descargados."""
        e = ajustes.estado_ollama(url)
        return {"ok": e.ok, "mensaje": e.mensaje, "modelos": e.modelos}

    return router
