"""Raíz de composición: el ÚNICO lugar donde se conectan puertos con adaptadores.

Si mañana cambia la base de datos, el proveedor de voz o el framework web, solo se
toca este fichero y el adaptador correspondiente; dominio y aplicación no se enteran.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from .adaptadores.entrada.http import (
    rutas_ajustes,
    rutas_auth,
    rutas_banco,
    rutas_chat,
    rutas_operaciones,
    rutas_uso,
)
from .adaptadores.entrada.http.app import crear_app
from .adaptadores.entrada.http.seguridad import crear_dependencia
from .adaptadores.salida.llm.clientes import FabricaClientes
from .adaptadores.salida.llm.openai_compat import ProveedorLLMOpenAI
from .adaptadores.salida.llm.sonda import SondaOpenAI
from .adaptadores.salida.persistencia.ajustes_json import AjustesJson
from .adaptadores.salida.persistencia.limitador import LimitadorEnMemoria
from .adaptadores.salida.persistencia.memoria_seguridad import IntentosEnMemoria
from .adaptadores.salida.persistencia.sqlite_estado import (
    MovilSqlite,
    OperacionesSqlite,
    SesionesAutenticadasSqlite,
    SesionesChatSqlite,
)
from .adaptadores.salida.reloj import RelojSistema
from .adaptadores.salida.seguridad.codigos import GeneradorCodigosSeguro
from .adaptadores.salida.seguridad.hasheador import HasheadorScrypt
from .adaptadores.salida.sqlite import esquema
from .adaptadores.salida.sqlite.auditoria import AuditoriaSqlite
from .adaptadores.salida.sqlite.conexion import BaseDeDatos
from .adaptadores.salida.sqlite.consultor import ConsultorMovimientosSqlite
from .adaptadores.salida.sqlite.uso import UsoSqlite
from .adaptadores.salida.sqlite.repositorios import (
    RepositorioClientesSqlite,
    RepositorioContactosSqlite,
    RepositorioCuentaSqlite,
)
from .adaptadores.salida.voz.piper import SintetizadorPiper
from .adaptadores.salida.voz.whisper import TranscriptorWhisper
from .aplicacion.agente import Agente
from .aplicacion.casos_uso.acceso import CerrarSesion, IdentificarCliente, IniciarSesion
from .aplicacion.casos_uso.ajustes import GestionAjustes
from .aplicacion.casos_uso.banco import ConsultarMovimientos, ConsultarSaldo, ListarContactos
from .aplicacion.casos_uso.bizum import CancelarOperacion, ConfirmarOperacion, SolicitarBizum
from .aplicacion.casos_uso.estado import ConsultarEstado
from .aplicacion.casos_uso.movil import LeerMensajesMovil
from .aplicacion.casos_uso.uso import ConsultarUso
from .aplicacion.casos_uso.voz import SintetizarVoz, TranscribirAudio
from .aplicacion.chat import ServicioChat
from .aplicacion.herramientas import bizum, contactos, grafico, movimientos, saldo
from .aplicacion.herramientas.registro import RegistroHerramientas
from .dominio.uso import PresupuestoUso

RUTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def _presupuesto_desde_entorno() -> PresupuestoUso:
    """Límites de uso de la IA; cada uno se puede ajustar con una variable de entorno (ver .env.example)."""
    def entero(nombre: str, defecto: int) -> int:
        try:
            return int(os.getenv(nombre, defecto))
        except ValueError:
            return defecto

    d = PresupuestoUso()
    return PresupuestoUso(
        tokens_por_dia=entero("TOKENS_DIA_CLIENTE", d.tokens_por_dia),
        tokens_por_turno=entero("TOKENS_MAX_TURNO", d.tokens_por_turno),
        max_caracteres_mensaje=entero("MAX_CARACTERES_MENSAJE", d.max_caracteres_mensaje),
        max_tokens_respuesta=entero("MAX_TOKENS_RESPUESTA", d.max_tokens_respuesta),
        peticiones_por_minuto=entero("PETICIONES_POR_MINUTO", d.peticiones_por_minuto),
        max_tokens_historial=entero("MAX_TOKENS_HISTORIAL", d.max_tokens_historial),
        max_caracteres_resultado=entero("MAX_CARACTERES_RESULTADO", d.max_caracteres_resultado),
    )


def crear_aplicacion() -> FastAPI:
    load_dotenv()
    presupuesto = _presupuesto_desde_entorno()

    # ── adaptadores de salida (infraestructura) ──────────────────────────
    reloj = RelojSistema()
    bd = BaseDeDatos()
    cuentas = RepositorioCuentaSqlite(bd)
    agenda = RepositorioContactosSqlite(bd)
    clientes = RepositorioClientesSqlite(bd)
    consultor = ConsultorMovimientosSqlite(bd)
    auditoria = AuditoriaSqlite(bd, reloj)
    uso_ia = UsoSqlite(bd)
    limitador = LimitadorEnMemoria(presupuesto.peticiones_por_minuto)
    ajustes = AjustesJson()
    fabrica = FabricaClientes(ajustes)
    llm = ProveedorLLMOpenAI(fabrica)
    sonda = SondaOpenAI(fabrica)
    piper = SintetizadorPiper()
    whisper = TranscriptorWhisper(ajustes, fabrica)
    sesiones_chat = SesionesChatSqlite(bd)  # el estado sobrevive a los reinicios (ver persistencia/sqlite_estado.py)
    hasheador = HasheadorScrypt()
    sesiones_auth = SesionesAutenticadasSqlite(bd, reloj)
    intentos = IntentosEnMemoria()
    operaciones = OperacionesSqlite(bd)
    codigos = GeneradorCodigosSeguro()
    movil = MovilSqlite(bd, reloj)  # canal OTP y bandeja de entrada del móvil: el mismo objeto

    # ── casos de uso (aplicación) ────────────────────────────────────────
    consultar_saldo = ConsultarSaldo(cuentas)
    listar_contactos = ListarContactos(agenda)
    consultar_movimientos = ConsultarMovimientos(consultor, auditoria)
    solicitar_bizum = SolicitarBizum(cuentas, agenda, operaciones, codigos, movil, reloj, auditoria)
    confirmar_operacion = ConfirmarOperacion(cuentas, operaciones, reloj, auditoria)
    cancelar_operacion = CancelarOperacion(operaciones, auditoria)
    iniciar_sesion = IniciarSesion(clientes, hasheador, sesiones_auth, intentos, reloj, auditoria)
    identificar = IdentificarCliente(sesiones_auth, clientes)
    cerrar_sesion = CerrarSesion(sesiones_auth, auditoria)

    # Registro de herramientas: añadir una = crear su módulo y listarla aquí
    herramientas = RegistroHerramientas([
        saldo.crear(consultar_saldo),
        contactos.crear(listar_contactos),
        bizum.crear(solicitar_bizum),
        movimientos.crear(consultar_movimientos, presupuesto.max_caracteres_resultado),
        grafico.crear(),
    ])
    agente = Agente(llm, herramientas, ajustes, uso_ia, presupuesto, reloj)
    chat = ServicioChat(agente, sesiones_chat, reloj, uso_ia, limitador, presupuesto, operaciones)
    consultar_uso = ConsultarUso(uso_ia, presupuesto, reloj)

    # ── adaptadores de entrada (HTTP) ────────────────────────────────────
    cliente_actual = crear_dependencia(identificar)
    cookie_segura = os.getenv("COOKIE_SEGURA") == "1"  # activar al servir por HTTPS
    routers = [
        rutas_auth.crear_router(iniciar_sesion, cerrar_sesion, cliente_actual, cookie_segura),
        rutas_banco.crear_router(consultar_saldo, listar_contactos, solicitar_bizum, consultar_movimientos, cliente_actual),
        rutas_operaciones.crear_router(confirmar_operacion, cancelar_operacion, LeerMensajesMovil(movil), cliente_actual),
        rutas_uso.crear_router(consultar_uso, cliente_actual),
        rutas_ajustes.crear_router(GestionAjustes(ajustes, sonda), cliente_actual),
        rutas_chat.crear_router(
            chat, TranscribirAudio(whisper, ajustes), SintetizarVoz(piper), ConsultarEstado(ajustes, piper), cliente_actual
        ),
    ]

    def al_arrancar() -> None:
        esquema.inicializar(bd, reloj, hasheador)
        piper.precargar()

    documentar = os.getenv("DOCS_API") == "1"  # Swagger/OpenAPI solo bajo petición: por defecto no se publica el mapa de la API
    return crear_app(routers, RUTA_FRONTEND, al_arrancar, documentar)
