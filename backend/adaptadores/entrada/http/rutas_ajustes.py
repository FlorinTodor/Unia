"""Panel ⚙️ Ajustes: alta/baja de claves, modelos, proveedor activo e IA local. Solo para el administrador."""
from collections.abc import Callable

from fastapi import APIRouter, Depends

from ....aplicacion.casos_uso.ajustes import GestionAjustes
from ....dominio.modelos import Cliente
from . import esquemas, presentadores, seguridad


def crear_router(ajustes: GestionAjustes, cliente_actual: Callable[..., Cliente]) -> APIRouter:
    admin_actual = seguridad.exigir_admin(cliente_actual)
    router = APIRouter(
        prefix="/ajustes", tags=["ajustes"], dependencies=[Depends(admin_actual)],
        responses={**esquemas.NO_AUTENTICADO, 403: {"model": esquemas.ErrorOut, "description": "Solo el administrador."}},
    )
    vista = presentadores.vista_ajustes

    @router.get("", response_model=esquemas.AjustesOut, summary="Ajustes actuales",
                description="Las claves API nunca salen del servidor: solo su máscara.")
    def leer():
        return vista(ajustes.leer())

    @router.post("/probar", response_model=esquemas.PruebaClaveOut, summary="Validar una clave API",
                 description="Lista los modelos de la cuenta sin gastar cuota. No guarda nada.",
                 responses=esquemas.NO_ENCONTRADO)
    def probar(peticion: esquemas.PeticionProbar):
        """Valida una clave antes de guardarla y devuelve sus modelos."""
        r = ajustes.probar_clave(peticion.proveedor, peticion.api_key)
        return {"ok": r.ok, "mensaje": r.mensaje, "modelos": r.modelos}

    @router.post("/claves", response_model=esquemas.AjustesConMensajeOut, summary="Añadir o reemplazar una clave",
                 description="Solo se guarda si el proveedor la acepta. La primera clave se activa sola.",
                 responses={**esquemas.VALIDACION, **esquemas.NO_ENCONTRADO})
    def anadir_clave(peticion: esquemas.PeticionClave, admin: Cliente = Depends(admin_actual)):
        resultado, mensaje = ajustes.anadir_clave(
            admin, peticion.proveedor, peticion.api_key, peticion.modelo, peticion.modelo_respaldo
        )
        return {**vista(resultado), "mensaje": mensaje}

    @router.patch("/claves/{proveedor}", response_model=esquemas.AjustesOut, summary="Cambiar los modelos de una clave",
                  responses=esquemas.NO_ENCONTRADO)
    def cambiar_modelos(proveedor: str, peticion: esquemas.PeticionModelos, admin: Cliente = Depends(admin_actual)):
        return vista(ajustes.cambiar_modelos(admin, proveedor, peticion.modelo, peticion.modelo_respaldo))

    @router.delete("/claves/{proveedor}", response_model=esquemas.AjustesOut, summary="Borrar una clave")
    def borrar_clave(proveedor: str, admin: Cliente = Depends(admin_actual)):
        return vista(ajustes.borrar_clave(admin, proveedor))

    @router.post("/activar", response_model=esquemas.AjustesOut, summary="Elegir el proveedor principal",
                 responses=esquemas.NO_ENCONTRADO)
    def activar(peticion: esquemas.PeticionActivar, admin: Cliente = Depends(admin_actual)):
        return vista(ajustes.activar(admin, peticion.proveedor))

    @router.put("/ollama", response_model=esquemas.AjustesOut, summary="Configurar la IA local (Ollama)")
    def guardar_ollama(peticion: esquemas.PeticionOllama, admin: Cliente = Depends(admin_actual)):
        return vista(ajustes.configurar_ollama(admin, peticion.url, peticion.modelo, peticion.fallback_local))

    @router.get("/ollama/estado", response_model=esquemas.EstadoOllamaOut, summary="Comprobar si Ollama responde")
    def estado_ollama():
        """Comprueba si Ollama responde (en la URL guardada) y qué modelos tiene descargados."""
        e = ajustes.estado_ollama()
        return {"ok": e.ok, "mensaje": e.mensaje, "modelos": e.modelos}

    return router
