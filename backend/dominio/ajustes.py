"""Ajustes del usuario (claves API, modelos, IA local) y las reglas que de ellos se derivan."""
from dataclasses import dataclass, field

from .proveedores import OLLAMA, PROVEEDORES_STT, ModeloRef


@dataclass
class ConfigClave:
    api_key: str
    modelo: str | None = None
    modelo_respaldo: str | None = None
    modelos: list[str] = field(default_factory=list)  # modelos de chat que ofrece la cuenta


@dataclass
class Ajustes:
    activo: str | None = None  # id del proveedor en uso, "ollama", o None si no hay configuración
    claves: dict[str, ConfigClave] = field(default_factory=dict)
    ollama_url: str = "http://localhost:11434/v1"
    ollama_modelo: str = "qwen3:8b"
    fallback_local: bool = True  # usar Ollama como último eslabón si fallan las claves

    @property
    def configurado(self) -> bool:
        return self.activo is not None

    def cadena_llm(self) -> list[ModeloRef]:
        """Cadena de fallback en orden de preferencia.

        Clave activa (principal → respaldo) → resto de claves → Ollama local.
        En los proveedores gratuitos los límites de tokens/día son POR MODELO, así que
        el modelo de respaldo de la misma clave es un fallback real. Con la IA local
        activa no se usa la nube: el usuario la eligió por privacidad.
        """
        if self.activo == OLLAMA:
            return [ModeloRef(OLLAMA, self.ollama_modelo)]
        orden = sorted(self.claves, key=lambda p: p != self.activo)  # la activa primero
        cadena: list[ModeloRef] = []
        for proveedor in orden:
            cfg = self.claves[proveedor]
            for modelo in (cfg.modelo, cfg.modelo_respaldo):
                eslabon = ModeloRef(proveedor, modelo) if modelo else None
                if eslabon and eslabon not in cadena:
                    cadena.append(eslabon)
        if self.fallback_local:
            cadena.append(ModeloRef(OLLAMA, self.ollama_modelo))
        return cadena

    def transcripcion(self) -> ModeloRef | None:
        """Proveedor y modelo Whisper con la primera clave que lo ofrezca."""
        for proveedor, modelo in PROVEEDORES_STT:
            if proveedor in self.claves:
                return ModeloRef(proveedor, modelo)
        return None


def enmascarar(clave: str) -> str:
    return "••••" + clave[-4:] if len(clave) > 8 else "••••"
