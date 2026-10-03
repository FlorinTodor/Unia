"""Contraseñas con scrypt (biblioteca estándar): lento a propósito, con sal aleatoria por contraseña."""
import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1


def _derivar(contrasena: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(contrasena.encode(), salt=sal, n=n, r=r, p=p, dklen=32)


class HasheadorScrypt:
    def __init__(self):
        self._falso = self.hashear(secrets.token_urlsafe(16))

    def hashear(self, contrasena: str) -> str:
        sal = secrets.token_bytes(16)
        derivado = _derivar(contrasena, sal, _N, _R, _P)
        return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(sal).decode(), base64.b64encode(derivado).decode())

    def verificar(self, contrasena: str, hash_guardado: str) -> bool:
        try:
            _, n, r, p, sal, esperado = hash_guardado.split("$")
            derivado = _derivar(contrasena, base64.b64decode(sal), int(n), int(r), int(p))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(derivado, base64.b64decode(esperado))  # tiempo constante

    def gastar_tiempo(self, contrasena: str) -> None:
        self.verificar(contrasena, self._falso)
