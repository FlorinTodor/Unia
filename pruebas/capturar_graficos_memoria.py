"""Capturas de gráficos reales para la memoria (docs/memoria_latex/figuras). Levanta antes una COPIA de la app en el 8006
(nunca el 8000 del usuario): `TTS_MOTOR=piper uvicorn backend.main:app --port 8006 --no-proxy-headers` desde la copia.
Uso: python3 pruebas/capturar_graficos_memoria.py <carpeta_salida>. Edita PREGUNTAS para cambiar los gráficos."""
import sys, time, pathlib
from selenium import webdriver
from selenium.webdriver.firefox.options import Options

URL = "http://127.0.0.1:8006"
SALIDA = pathlib.Path(sys.argv[1])
PREGUNTAS = [
    ("config", "Consulta mis movimientos y hazme un gráfico de barras con dos series, una para restaurantes y otra para supermercados, con una barra por cada uno de los últimos tres meses. Ninguna fuente predefinida sirve: construye tú la configuración con los datos reales."),
]

o = Options(); o.add_argument("-headless")
o.set_preference("layout.css.devPixelsPerPx", "2")
o.add_argument("--width=1100"); o.add_argument("--height=1000")
d = webdriver.Firefox(options=o, service=webdriver.FirefoxService(executable_path="/snap/bin/geckodriver",
                                                                 log_output=str(SALIDA / "gecko.log")))
try:
    d.get(URL); time.sleep(2)
    d.find_element("id", "login-usuario").send_keys("alex")
    d.find_element("id", "login-contrasena").send_keys("alex2026")
    d.find_element("id", "btn-login").click(); time.sleep(3)
    for nombre, texto in PREGUNTAS:
        d.execute_script("const e=document.getElementById('entrada');e.value=arguments[0];"
                         "e.dispatchEvent(new Event('input',{bubbles:true}));", texto)
        d.execute_script("document.getElementById('btn-enviar').click();")
        fin = time.time() + 150; time.sleep(2)
        while time.time() < fin:
            ocupado = "ocupado" in (d.find_element("id", "chat").get_attribute("class") or "")
            if not ocupado and d.find_element("id", "btn-enviar").is_enabled():
                break
            time.sleep(1)
        time.sleep(2.5)  # animación de Chart.js
        print(nombre, "canvas:", d.execute_script("return document.querySelectorAll('canvas').length"))
        print("  respuesta:", d.execute_script("const b=document.querySelectorAll('.mensaje.asistente .burbuja');return b.length?b[b.length-1].innerText.slice(0,300):'';"))
        d.execute_script("document.querySelectorAll('.estado-herramienta.aviso').forEach(e=>e.style.display='none');")
        (SALIDA / f"pagina_{nombre}.png").write_bytes(d.get_screenshot_as_png())
        tarjetas = d.find_elements("css selector", ".tarjeta-grafico")
        if tarjetas:
            d.execute_script("arguments[0].scrollIntoView({block:'center'});", tarjetas[-1]); time.sleep(0.8)
            (SALIDA / f"grafico_{nombre}.png").write_bytes(tarjetas[-1].screenshot_as_png)
        mensajes = d.find_elements("css selector", ".mensaje.asistente")
        if mensajes:
            d.execute_script("arguments[0].scrollIntoView({block:'center'});", mensajes[-1]); time.sleep(0.8)
            (SALIDA / f"mensaje_{nombre}.png").write_bytes(mensajes[-1].screenshot_as_png)
        print("  html del último mensaje:", d.execute_script("const m=document.querySelectorAll('.mensaje.asistente');return m.length?m[m.length-1].outerHTML.slice(0,400):'';"))
finally:
    d.quit()
print("hecho")
