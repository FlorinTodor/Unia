"""Casos de uso del panel ⚙️ Ajustes: claves, modelos, proveedor activo e IA local."""
from dataclasses import dataclass
from urllib.parse import urlsplit

from ...dominio.ajustes import Ajustes, ConfigClave
from ...dominio.errores import ErrorDeValidacion, ErrorNoEncontrado
from ...dominio.modelos import Cliente
from ...dominio.proveedores import CATALOGO, OLLAMA
from ...dominio.reglas import validar_url_ollama
from ..puertos.infraestructura import (
    ClaveRechazada,
    EstadoOllama,
    ListadoNoSoportado,
    RepositorioAjustes,
    SinConexion,
    SondaProveedores,
)
from ..puertos.seguridad import Auditoria


def _sin_credenciales(url: str) -> str:
    """Quita `usuario:clave@` de una URL antes de dejarla en la auditoría (puede ser una contraseña tecleada)."""
    try:
        partes = urlsplit(url)
        if partes.username is None and partes.password is None:
            return url[:200]
        host = f"[{partes.hostname}]" if ":" in (partes.hostname or "") else (partes.hostname or "")
        return partes._replace(netloc=f"{host}:{partes.port}" if partes.port else host).geturl()[:200]
    except ValueError:
        return "(URL no válida)"


@dataclass(frozen=True)
class ResultadoPrueba:
    ok: bool
    mensaje: str
    modelos: list[str]


class GestionAjustes:
    def __init__(
        self, repositorio: RepositorioAjustes, sonda: SondaProveedores, hosts_ollama_permitidos: frozenset[str] = frozenset(),
        auditoria: Auditoria | None = None,
    ):
        self._auditoria = auditoria
        self._repo = repositorio
        self._sonda = sonda
        self._hosts_ollama = hosts_ollama_permitidos  # lista blanca opcional (.env); por defecto solo loopback

    def _auditar(self, admin: Cliente, accion: str, detalle: str, resultado: str = "ok") -> None:
        """Deja constancia de quién cambió qué. NUNCA se anota una clave API, solo el proveedor."""
        if self._auditoria is not None:
            self._auditoria.registrar(admin.id, accion, detalle, resultado)

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

    def estado_ollama(self) -> EstadoOllama:
        """Sondea SIEMPRE la URL guardada (y validada): el cliente no puede dirigir al servidor a una URL arbitraria."""
        return self._sonda.estado_ollama(validar_url_ollama(self._repo.cargar().ollama_url, self._hosts_ollama))

    # ------------------------------------------------------------------ cambios

    def anadir_clave(
        self, admin: Cliente, proveedor: str, api_key: str, modelo: str | None = None, modelo_respaldo: str | None = None
    ) -> tuple[Ajustes, str]:
        """Añade o reemplaza la clave de un proveedor (solo si el proveedor la acepta)."""
        catalogo = self._proveedor(proveedor)
        clave = api_key.strip()
        if not clave:
            raise ErrorDeValidacion("Escribe una clave API.")
        prueba = self.probar_clave(proveedor, clave)
        if not prueba.ok:
            self._auditar(admin, "ajustes_clave_rechazada", proveedor, prueba.mensaje)
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
        self._auditar(admin, "ajustes_clave_guardada", proveedor)
        return ajustes, prueba.mensaje

    def cambiar_modelos(self, admin: Cliente, proveedor: str, modelo: str | None, modelo_respaldo: str | None) -> Ajustes:
        ajustes = self._repo.cargar()
        if proveedor not in ajustes.claves:
            raise ErrorNoEncontrado("No hay clave para ese proveedor.")
        if modelo is not None:
            ajustes.claves[proveedor].modelo = modelo
        if modelo_respaldo is not None:
            ajustes.claves[proveedor].modelo_respaldo = modelo_respaldo
        self._repo.guardar(ajustes)
        self._auditar(admin, "ajustes_modelos", f"{proveedor}: {modelo or '-'} / {modelo_respaldo or '-'}")
        return ajustes

    def borrar_clave(self, admin: Cliente, proveedor: str) -> Ajustes:
        ajustes = self._repo.cargar()
        ajustes.claves.pop(proveedor, None)
        if ajustes.activo == proveedor:
            ajustes.activo = next(iter(ajustes.claves), None)
        self._repo.guardar(ajustes)
        self._auditar(admin, "ajustes_clave_borrada", proveedor)
        return ajustes

    def activar(self, admin: Cliente, proveedor: str) -> Ajustes:
        ajustes = self._repo.cargar()
        if proveedor != OLLAMA and proveedor not in ajustes.claves:
            raise ErrorNoEncontrado("Primero añade una clave para ese proveedor.")
        ajustes.activo = proveedor
        self._repo.guardar(ajustes)
        self._auditar(admin, "ajustes_activar", proveedor)
        return ajustes

    def configurar_ollama(
        self, admin: Cliente, url: str | None = None, modelo: str | None = None, fallback_local: bool | None = None
    ) -> Ajustes:
        ajustes = self._repo.cargar()
        if url is not None:
            nueva = url.strip().rstrip("/") or "http://localhost:11434/v1"
            try:
                ajustes.ollama_url = validar_url_ollama(nueva, self._hosts_ollama)
            except ErrorDeValidacion as e:
                self._auditar(admin, "ajustes_ollama_rechazado", _sin_credenciales(nueva), e.mensaje)
                raise
        if modelo:
            ajustes.ollama_modelo = modelo
        if fallback_local is not None:
            ajustes.fallback_local = fallback_local
        self._repo.guardar(ajustes)
        self._auditar(admin, "ajustes_ollama", f"{ajustes.ollama_url} · {ajustes.ollama_modelo} · local={ajustes.fallback_local}")
        return ajustes

    @staticmethod
    def _proveedor(proveedor: str):
        if proveedor not in CATALOGO:
            raise ErrorNoEncontrado(f"Proveedor desconocido: {proveedor}")
        return CATALOGO[proveedor]
