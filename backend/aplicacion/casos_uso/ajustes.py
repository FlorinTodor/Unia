"""Casos de uso del panel ⚙️ Ajustes: claves, modelos, proveedor activo e IA local."""
from dataclasses import dataclass

from ...dominio.ajustes import Ajustes, ConfigClave
from ...dominio.errores import ErrorDeValidacion, ErrorNoEncontrado
from ...dominio.proveedores import CATALOGO, OLLAMA
from ..puertos.infraestructura import (
    ClaveRechazada,
    EstadoOllama,
    ListadoNoSoportado,
    RepositorioAjustes,
    SinConexion,
    SondaProveedores,
)


@dataclass(frozen=True)
class ResultadoPrueba:
    ok: bool
    mensaje: str
    modelos: list[str]


class GestionAjustes:
    def __init__(self, repositorio: RepositorioAjustes, sonda: SondaProveedores):
        self._repo = repositorio
        self._sonda = sonda

    # ------------------------------------------------------------------ lectura

    def leer(self) -> Ajustes:
        ajustes = self._repo.cargar()
        # claves heredadas del .env: se rellena su lista de modelos la primera vez
        pendientes = [p for p, cfg in ajustes.claves.items() if p in CATALOGO and not cfg.modelos]
        for proveedor in pendientes:
            try:
                ajustes.claves[proveedor].modelos = self._sonda.listar_modelos(proveedor)
            except (ClaveRechazada, SinConexion, ListadoNoSoportado):
                pass
        if pendientes:
            self._repo.guardar(ajustes)
        return ajustes

    def probar_clave(self, proveedor: str, api_key: str) -> ResultadoPrueba:
        """Valida una clave antes de guardarla y devuelve sus modelos."""
        nombre = self._proveedor(proveedor).nombre
        try:
            modelos = self._sonda.listar_modelos(proveedor, api_key.strip())
        except ClaveRechazada:
            return ResultadoPrueba(False, f"{nombre} rechaza la clave: revisa que esté bien copiada.", [])
        except SinConexion:
            return ResultadoPrueba(False, f"No se pudo conectar con {nombre}. ¿Hay conexión a internet?", [])
        except ListadoNoSoportado:
            return ResultadoPrueba(True, "Clave guardada (no se pudo obtener la lista de modelos).", [])
        return ResultadoPrueba(True, f"Clave válida · {len(modelos)} modelos disponibles.", modelos)

    def estado_ollama(self, url: str | None = None) -> EstadoOllama:
        return self._sonda.estado_ollama(url or self._repo.cargar().ollama_url)

    # ------------------------------------------------------------------ cambios

    def anadir_clave(
        self, proveedor: str, api_key: str, modelo: str | None = None, modelo_respaldo: str | None = None
    ) -> tuple[Ajustes, str]:
        """Añade o reemplaza la clave de un proveedor (solo si el proveedor la acepta)."""
        catalogo = self._proveedor(proveedor)
        clave = api_key.strip()
        if not clave:
            raise ErrorDeValidacion("Escribe una clave API.")
        prueba = self.probar_clave(proveedor, clave)
        if not prueba.ok:
            raise ErrorDeValidacion(prueba.mensaje)
        ajustes = self._repo.cargar()
        ajustes.claves[proveedor] = ConfigClave(
            api_key=clave,
            modelo=modelo or catalogo.modelo,
            modelo_respaldo=modelo_respaldo if modelo_respaldo is not None else catalogo.modelo_respaldo,
            modelos=prueba.modelos,
        )
        if ajustes.activo is None:
            ajustes.activo = proveedor  # la primera clave se activa sola
        self._repo.guardar(ajustes)
        return ajustes, prueba.mensaje

    def cambiar_modelos(self, proveedor: str, modelo: str | None, modelo_respaldo: str | None) -> Ajustes:
        ajustes = self._repo.cargar()
        if proveedor not in ajustes.claves:
            raise ErrorNoEncontrado("No hay clave para ese proveedor.")
        if modelo is not None:
            ajustes.claves[proveedor].modelo = modelo
        if modelo_respaldo is not None:
            ajustes.claves[proveedor].modelo_respaldo = modelo_respaldo
        self._repo.guardar(ajustes)
        return ajustes

    def borrar_clave(self, proveedor: str) -> Ajustes:
        ajustes = self._repo.cargar()
        ajustes.claves.pop(proveedor, None)
        if ajustes.activo == proveedor:
            ajustes.activo = next(iter(ajustes.claves), None)
        self._repo.guardar(ajustes)
        return ajustes

    def activar(self, proveedor: str) -> Ajustes:
        ajustes = self._repo.cargar()
        if proveedor != OLLAMA and proveedor not in ajustes.claves:
            raise ErrorNoEncontrado("Primero añade una clave para ese proveedor.")
        ajustes.activo = proveedor
        self._repo.guardar(ajustes)
        return ajustes

    def configurar_ollama(
        self, url: str | None = None, modelo: str | None = None, fallback_local: bool | None = None
    ) -> Ajustes:
        ajustes = self._repo.cargar()
        if url is not None:
            ajustes.ollama_url = url.strip().rstrip("/") or "http://localhost:11434/v1"
        if modelo:
            ajustes.ollama_modelo = modelo
        if fallback_local is not None:
            ajustes.fallback_local = fallback_local
        self._repo.guardar(ajustes)
        return ajustes

    @staticmethod
    def _proveedor(proveedor: str):
        if proveedor not in CATALOGO:
            raise ErrorNoEncontrado(f"Proveedor desconocido: {proveedor}")
        return CATALOGO[proveedor]
