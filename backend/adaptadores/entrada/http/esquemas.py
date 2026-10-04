"""Modelos de petición y respuesta de la API (lo que aparece en OpenAPI / Swagger)."""
from pydantic import BaseModel, Field


class ErrorOut(BaseModel):
    detail: str = Field(description="Motivo del error, ya redactado para mostrarlo al usuario.")
    errores: list[dict] | None = Field(default=None, description="Solo en 400/422: `[{campo, motivo}]`.")
    contactos_disponibles: list[str] | None = Field(default=None, description="Solo si un contacto Bizum no existe (404).")


# ------------------------------------------------------------------ acceso

class PeticionLogin(BaseModel):
    usuario: str = Field(max_length=64, description="Usuario (no distingue mayúsculas).")
    contrasena: str = Field(max_length=256)
    model_config = {"json_schema_extra": {"examples": [{"usuario": "alex", "contrasena": "<su contraseña>"}]}}


class ClienteOut(BaseModel):
    usuario: str
    nombre: str
    es_admin: bool = Field(False, description="Solo el administrador puede ver y cambiar los ajustes de la IA.")


class OkOut(BaseModel):
    ok: bool = True


# ------------------------------------------------------------------ banco

class CuentaOut(BaseModel):
    iban: str
    titular: str
    saldo: float = Field(description="Saldo en euros.")


class ContactoOut(BaseModel):
    nombre: str
    telefono: str


class TarjetaOut(BaseModel):
    marca: str
    tipo: str = Field(description="`débito` o `crédito`.")
    ultimos4: str = Field(description="Solo los 4 últimos dígitos: el número completo no existe en el sistema.")
    estado: str = Field(description="`activa` o `bloqueada`.")
    bloqueada_el: str | None = Field(description="Instante (ISO 8601) del bloqueo, o null si está activa.")


class ConsultaOut(BaseModel):
    ok: bool = True
    columnas: list[str]
    filas: list[list] = Field(description="Cada fila es una lista de valores en el orden de `columnas`.")
    num_filas: int
    truncado: bool = Field(description="True si hay más filas que el tope de 60.")


class PeticionBizum(BaseModel):
    destinatario: str = Field(max_length=100, description="Nombre (o parte) o teléfono de un contacto del cliente.")
    importe: float = Field(allow_inf_nan=False, description="Euros. Máximo 1.000 por operación y 1.500 al día.")
    concepto: str = Field("", max_length=140)
    model_config = {"json_schema_extra": {"examples": [{"destinatario": "María", "importe": 25, "concepto": "cena"}]}}


class OperacionOut(BaseModel):
    id: str
    destinatario: str
    importe: float
    concepto: str
    alertas: list[str] = Field(description="Avisos para el cliente (destinatario nuevo, importe alto...).")
    caduca: str = Field(description="Instante (ISO 8601) hasta el que vale el código.")
    tipo: str = Field("bizum", description="`bizum` o `desbloqueo_tarjeta` (en este, `destinatario` es la tarjeta e `importe` 0).")


class BizumPendienteOut(BaseModel):
    ok: bool = True
    estado: str = Field(description="Siempre `pendiente_de_confirmacion`: el dinero NO se ha movido.")
    operacion: OperacionOut


class PeticionCodigo(BaseModel):
    codigo: str = Field(pattern=r"^\d{6}$", description="Código de 6 dígitos recibido en el móvil simulado.")
    model_config = {"json_schema_extra": {"examples": [{"codigo": "123456"}]}}


class ComprobanteOut(BaseModel):
    ok: bool = True
    tipo: str = "bizum"
    destinatario: str
    telefono: str
    importe: float
    concepto: str
    nuevo_saldo: float


class ComprobanteTarjetaOut(BaseModel):
    ok: bool = True
    tipo: str = "desbloqueo_tarjeta"
    tarjeta: TarjetaOut = Field(description="La tarjeta ya desbloqueada.")


class SmsOut(BaseModel):
    remitente: str
    texto: str = Field(description="Incluye el código de confirmación. Solo se entrega por este canal.")
    hora: str


# ------------------------------------------------------------------ chat, voz y estado

class PeticionChat(BaseModel):
    session_id: str = Field(
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
        description="Identificador de la conversación (lo elige el cliente; letras, cifras, `_` y `-`, máx. 64). Es privado de cada usuario.",
    )
    mensaje: str = Field(max_length=20_000, description="El tope real (`MAX_CARACTERES_MENSAJE`) responde 413; esto solo acota el cuerpo.")
    model_config = {"json_schema_extra": {"examples": [{"session_id": "demo-1", "mensaje": "¿Cuánto gasté en restaurantes en junio?"}]}}


class PeticionTTS(BaseModel):
    texto: str = Field(max_length=5_000, description="Hasta 1.200 caracteres; los números se leen como palabras.")


class TranscripcionOut(BaseModel):
    texto: str


class EstadoOut(BaseModel):
    ok: bool = True
    proveedor: str | None
    modelo: str | None
    cadena_fallback: list[str] = Field(description="Modelos en orden de uso si el principal falla.")
    voz_disponible: bool = Field(description="¿Hay una clave con Whisper para transcribir voz?")
    tts_servidor: bool = Field(description="¿Está instalada la voz neuronal Piper?")
    configurado: bool


# ------------------------------------------------------------------ uso de la IA

class UsoReciente(BaseModel):
    momento: str
    modelo: str
    entrada: int = Field(description="Tokens enviados al modelo.")
    salida: int = Field(description="Tokens generados por el modelo (incluye su razonamiento).")
    estimado: bool = Field(description="True si el proveedor no informó y el dato es una aproximación.")


class UsoClienteOut(BaseModel):
    usuario: str
    nombre: str
    tokens_hoy: int
    limite_dia: int


class UsoOut(BaseModel):
    tokens_hoy: int
    limite_dia: int = Field(description="Tokens que puede gastar el cliente al día. Se renueva a medianoche.")
    restante: int
    porcentaje: float
    por_turno: int = Field(description="Tope de tokens de una sola pregunta (con todas sus rondas).")
    peticiones_por_minuto: int
    max_caracteres_mensaje: int
    ultimos: list[UsoReciente]


# ------------------------------------------------------------------ ajustes

class ClaveOut(BaseModel):
    proveedor: str
    nombre: str
    mascara: str = Field(description="La clave API nunca sale del servidor; solo sus últimos 4 caracteres.")
    modelo: str | None
    modelo_respaldo: str | None
    modelos: list[str]


class ProveedorOut(BaseModel):
    id: str
    nombre: str
    url_claves: str
    prefijo: str
    nota: str
    modelo: str
    modelo_respaldo: str


class OllamaOut(BaseModel):
    url: str
    modelo: str
    fallback_local: bool


class AjustesOut(BaseModel):
    activo: str | None
    configurado: bool
    claves: list[ClaveOut]
    catalogo: list[ProveedorOut]
    ollama: OllamaOut
    voz_entrada: str | None
    proveedor: str | None
    modelo: str | None
    cadena_fallback: list[str]


class AjustesConMensajeOut(AjustesOut):
    mensaje: str


class PeticionProbar(BaseModel):
    proveedor: str = Field(max_length=32)
    api_key: str = Field(max_length=512)


class PruebaClaveOut(BaseModel):
    ok: bool
    mensaje: str
    modelos: list[str]


class PeticionClave(BaseModel):
    proveedor: str = Field(max_length=32)
    api_key: str = Field(max_length=512)
    modelo: str | None = Field(default=None, max_length=128)
    modelo_respaldo: str | None = Field(default=None, max_length=128)


class PeticionModelos(BaseModel):
    modelo: str | None = Field(default=None, max_length=128)
    modelo_respaldo: str | None = Field(default=None, max_length=128, description='Cadena vacía = sin modelo de respaldo.')


class PeticionActivar(BaseModel):
    proveedor: str = Field(max_length=32, description="Id de un proveedor con clave, o `ollama`.")


class PeticionOllama(BaseModel):
    url: str | None = Field(default=None, max_length=200)
    modelo: str | None = Field(default=None, max_length=128)
    fallback_local: bool | None = None


class EstadoOllamaOut(BaseModel):
    ok: bool
    mensaje: str
    modelos: list[str]


# respuestas de error comunes (se reutilizan en cada ruta). Mapa completo en errores_http.py.
NO_AUTENTICADO = {401: {"model": ErrorOut, "description": "No hay sesión válida: inicia sesión en `POST /auth/login`."}}
PETICION_INVALIDA = {400: {"model": ErrorOut, "description": "El cuerpo no es un JSON válido o está vacío."}}
VALIDACION = {422: {"model": ErrorOut, "description": "Datos no válidos o regla de negocio incumplida."}}
NO_ENCONTRADO = {404: {"model": ErrorOut, "description": "El recurso no existe (o no es del cliente)."}}
CONFLICTO = {409: {"model": ErrorOut, "description": "Choca con el estado actual (saldo, tope diario, operación ya procesada)."}}
CADUCADO = {410: {"model": ErrorOut, "description": "El código ha caducado."}}
BLOQUEADO = {423: {"model": ErrorOut, "description": "Demasiados intentos con el código: operación cancelada."}}
LIMITE = {429: {"model": ErrorOut, "description": "Límite de uso superado. La cabecera `Retry-After` indica los segundos de espera."}}
PROVEEDOR = {
    502: {"model": ErrorOut, "description": "Falla el servicio externo (IA o voz)."},
    504: {"model": ErrorOut, "description": "El servicio externo no responde a tiempo."},
}
