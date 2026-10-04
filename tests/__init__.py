import os

# El administrador no tiene contraseña por defecto: los tests le ponen una propia (nunca la real del .env).
os.environ["CONTRASENA_ADMIN"] = "clave-de-prueba-del-administrador"
