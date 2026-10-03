"""Estado de la aplicación que debe SOBREVIVIR a un reinicio del servidor.

Sesiones de login, operaciones pendientes de confirmar, SMS del móvil simulado y conversaciones del chat. Antes vivían
en memoria: cada reinicio (o cada recarga automática de uvicorn en desarrollo) desconectaba al cliente, tiraba su
operación a medias y borraba el SMS con el código. Aquí se guardan en SQLite; las versiones en memoria siguen
existiendo para los tests.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta

from ....dominio.modelos import LlamadaHerramienta, Mensaje
from ....dominio.operaciones import EstadoOperacion, OperacionPendiente
from ....aplicacion.puertos.infraestructura import Reloj
from ..sqlite.conexion import BaseDeDatos

HORAS_SESION = 8


def _huella(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SesionesAutenticadasSqlite:
    """El token es opaco y aleatorio; en la base de datos solo se guarda su huella."""

    def __init__(self, bd: BaseDeDatos, reloj: Reloj):
        self._bd = bd
        self._reloj = reloj

    def crear(self, cliente_id: int) -> str:
        token = secrets.token_urlsafe(32)
        ahora = self._reloj.ahora()
        con = self._bd.abrir()
        try:
            with con:
                con.execute("DELETE FROM sesiones_auth WHERE caduca <= ?", (ahora.isoformat(),))  # limpieza oportunista
                con.execute(
                    "INSERT INTO sesiones_auth (huella, cliente_id, caduca) VALUES (?,?,?)",
                    (_huella(token), cliente_id, (ahora + timedelta(hours=HORAS_SESION)).isoformat()),
                )
        finally:
            con.close()
        return token

    def cliente_de(self, token: str) -> int | None:
        con = self._bd.abrir()
        try:
            fila = con.execute("SELECT cliente_id, caduca FROM sesiones_auth WHERE huella = ?", (_huella(token),)).fetchone()
            if fila is None:
                return None
            if self._reloj.ahora() >= datetime.fromisoformat(fila["caduca"]):
                with con:
                    con.execute("DELETE FROM sesiones_auth WHERE huella = ?", (_huella(token),))
                return None
            return fila["cliente_id"]
        finally:
            con.close()

    def cerrar(self, token: str) -> None:
        con = self._bd.abrir()
        try:
            with con:
                con.execute("DELETE FROM sesiones_auth WHERE huella = ?", (_huella(token),))
        finally:
            con.close()


class OperacionesSqlite:
    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def guardar(self, o: OperacionPendiente) -> None:
        con = self._bd.abrir()
        try:
            with con:
                con.execute(
                    "INSERT OR REPLACE INTO operaciones_pendientes (id, cliente_id, destinatario, telefono, importe, concepto, "
                    "huella, creada, caduca, alertas, intentos_restantes, estado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (o.id, o.cliente_id, o.destinatario, o.telefono, o.importe, o.concepto, o.huella, o.creada.isoformat(),
                     o.caduca.isoformat(), json.dumps(list(o.alertas), ensure_ascii=False), o.intentos_restantes, o.estado.value),
                )
        finally:
            con.close()

    def obtener(self, id_operacion: str) -> OperacionPendiente | None:
        con = self._bd.abrir()
        try:
            f = con.execute("SELECT * FROM operaciones_pendientes WHERE id = ?", (id_operacion,)).fetchone()
        finally:
            con.close()
        if f is None:
            return None
        return OperacionPendiente(
            id=f["id"], cliente_id=f["cliente_id"], destinatario=f["destinatario"], telefono=f["telefono"],
            importe=f["importe"], concepto=f["concepto"], huella=f["huella"], creada=datetime.fromisoformat(f["creada"]),
            caduca=datetime.fromisoformat(f["caduca"]), alertas=tuple(json.loads(f["alertas"])),
            intentos_restantes=f["intentos_restantes"], estado=EstadoOperacion(f["estado"]),
        )


class MovilSqlite:
    """El «teléfono» del cliente: recibe los SMS con el OTP. Es un canal aparte del chat."""

    def __init__(self, bd: BaseDeDatos, reloj: Reloj):
        self._bd = bd
        self._reloj = reloj

    def enviar(self, cliente_id: int, texto: str) -> None:
        ahora = self._reloj.ahora()
        con = self._bd.abrir()
        try:
            with con:
                con.execute(
                    "INSERT INTO sms_movil (cliente_id, momento, hora, texto) VALUES (?,?,?,?)",
                    (cliente_id, ahora.isoformat(), ahora.strftime("%H:%M"), texto),
                )
        finally:
            con.close()

    def mensajes(self, cliente_id: int) -> list[dict]:
        con = self._bd.abrir()
        try:
            return [
                {"remitente": "Unicaja", "texto": f["texto"], "hora": f["hora"]}
                for f in con.execute(
                    "SELECT texto, hora FROM sms_movil WHERE cliente_id = ? ORDER BY id DESC LIMIT 10", (cliente_id,)
                )
            ]
        finally:
            con.close()


def _mensaje_a_dict(m: Mensaje) -> dict:
    return {
        "rol": m.rol, "contenido": m.contenido, "id_llamada": m.id_llamada,
        "llamadas": [{"id": ll.id, "nombre": ll.nombre, "argumentos": ll.argumentos} for ll in m.llamadas],
    }


def _dict_a_mensaje(d: dict) -> Mensaje:
    return Mensaje(
        d["rol"], d["contenido"], tuple(LlamadaHerramienta(ll["id"], ll["nombre"], ll["argumentos"]) for ll in d["llamadas"]), d["id_llamada"]
    )


class SesionesChatSqlite:
    """La conversación sigue donde estaba tras un reinicio, en vez de que el asistente «olvide» de qué se hablaba."""

    def __init__(self, bd: BaseDeDatos):
        self._bd = bd

    def obtener(self, id_sesion: str) -> list[Mensaje] | None:
        con = self._bd.abrir()
        try:
            f = con.execute("SELECT mensajes FROM sesiones_chat WHERE clave = ?", (id_sesion,)).fetchone()
        finally:
            con.close()
        return [_dict_a_mensaje(d) for d in json.loads(f["mensajes"])] if f else None

    def guardar(self, id_sesion: str, mensajes: list[Mensaje]) -> None:
        con = self._bd.abrir()
        try:
            with con:
                con.execute(
                    "INSERT OR REPLACE INTO sesiones_chat (clave, mensajes, actualizada) VALUES (?,?,datetime('now'))",
                    (id_sesion, json.dumps([_mensaje_a_dict(m) for m in mensajes], ensure_ascii=False)),
                )
        finally:
            con.close()
