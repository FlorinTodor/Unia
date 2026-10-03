"""Raíz de composición: el ÚNICO lugar donde se conectan puertos con adaptadores.

Si mañana cambia la base de datos, el proveedor de voz o el framework web, solo se
toca este fichero y el adaptador correspondiente; dominio y aplicación no se enteran.
"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from .adaptadores.entrada.http import rutas_ajustes, rutas_banco, rutas_chat
from .adaptadores.entrada.http.app import crear_app
from .adaptadores.salida.llm.clientes import FabricaClientes
from .adaptadores.salida.llm.openai_compat import ProveedorLLMOpenAI
from .adaptadores.salida.llm.sonda import SondaOpenAI
from .adaptadores.salida.persistencia.ajustes_json import AjustesJson
from .adaptadores.salida.persistencia.sesiones_memoria import SesionesEnMemoria
from .adaptadores.salida.reloj import RelojSistema
from .adaptadores.salida.sqlite import esquema
from .adaptadores.salida.sqlite.conexion import BaseDeDatos
from .adaptadores.salida.sqlite.repositorios import (
    ConsultorMovimientosSqlite,
    RepositorioContactosSqlite,
    RepositorioCuentaSqlite,
)
from .adaptadores.salida.voz.piper import SintetizadorPiper
from .adaptadores.salida.voz.whisper import TranscriptorWhisper
from .aplicacion.agente import Agente
from .aplicacion.casos_uso.ajustes import GestionAjustes
from .aplicacion.casos_uso.banco import ConsultarMovimientos, ConsultarSaldo, EnviarBizum, ListarContactos
from .aplicacion.casos_uso.estado import ConsultarEstado
from .aplicacion.casos_uso.voz import SintetizarVoz, TranscribirAudio
from .aplicacion.chat import ServicioChat
from .aplicacion.herramientas import bizum, contactos, grafico, movimientos, saldo
from .aplicacion.herramientas.registro import RegistroHerramientas

RUTA_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def crear_aplicacion() -> FastAPI:
    load_dotenv()

    # ── adaptadores de salida (infraestructura) ──────────────────────────
    reloj = RelojSistema()
    bd = BaseDeDatos()
    cuentas = RepositorioCuentaSqlite(bd)
    agenda = RepositorioContactosSqlite(bd)
    consultor = ConsultorMovimientosSqlite(bd)
    ajustes = AjustesJson()
    clientes = FabricaClientes(ajustes)
    llm = ProveedorLLMOpenAI(clientes)
    sonda = SondaOpenAI(clientes)
    piper = SintetizadorPiper()
    whisper = TranscriptorWhisper(ajustes, clientes)
    sesiones = SesionesEnMemoria()

    # ── casos de uso (aplicación) ────────────────────────────────────────
    consultar_saldo = ConsultarSaldo(cuentas)
    listar_contactos = ListarContactos(agenda)
    enviar_bizum = EnviarBizum(cuentas, agenda, reloj)
    consultar_movimientos = ConsultarMovimientos(consultor)

    # Registro de herramientas: añadir una = crear su módulo y listarla aquí
    herramientas = RegistroHerramientas([
        saldo.crear(consultar_saldo),
        contactos.crear(listar_contactos),
        bizum.crear(enviar_bizum),
        movimientos.crear(consultar_movimientos),
        grafico.crear(),
    ])
    agente = Agente(llm, herramientas, ajustes)
    chat = ServicioChat(agente, sesiones, consultar_saldo, reloj)

    # ── adaptadores de entrada (HTTP) ────────────────────────────────────
    routers = [
        rutas_banco.crear_router(consultar_saldo, listar_contactos, enviar_bizum, consultar_movimientos),
        rutas_ajustes.crear_router(GestionAjustes(ajustes, sonda)),
        rutas_chat.crear_router(
            chat, TranscribirAudio(whisper, ajustes), SintetizarVoz(piper), ConsultarEstado(ajustes, piper)
        ),
    ]

    def al_arrancar() -> None:
        esquema.inicializar(bd, reloj)
        piper.precargar()

    return crear_app(routers, RUTA_FRONTEND, al_arrancar)
