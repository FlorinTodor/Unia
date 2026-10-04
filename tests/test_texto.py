from backend.aplicacion.texto import limpiar_invisibles, normalizar_para_voz


def test_limpia_caracteres_de_ancho_cero():
    assert limpiar_invisibles("202​​2026") == "2022026"


def test_importes_a_palabras():
    assert normalizar_para_voz("Tienes 1.250,50 €") == "Tienes mil doscientos cincuenta euros con cincuenta céntimos"
    assert normalizar_para_voz("Cuesta 1 €") == "Cuesta un euro"
    assert "un céntimo" in normalizar_para_voz("2,01 €")


def test_numeros_largos_se_dejan_igual():
    assert normalizar_para_voz("Llama al 600111222") == "Llama al 600111222"
    assert normalizar_para_voz("el 18 de julio") == "el dieciocho de julio"


def test_uno_pierde_la_o_delante_de_masculino():
    assert normalizar_para_voz("Son 21 €") == "Son veintiún euros"
    assert normalizar_para_voz("Son 0,21 €") == "Son cero euros con veintiún céntimos"
    assert normalizar_para_voz("Son 101 €") == "Son ciento un euros"
    assert normalizar_para_voz("Son 31,01 €") == "Son treinta y un euros con un céntimo"


def test_detecta_promesas_sin_accion_y_no_confunde_respuestas_normales():
    from backend.aplicacion.texto import promete_sin_hacer

    assert promete_sin_hacer("Tienes razón. Voy a obtener los ingresos y a crear un gráfico con los 12 meses. Un momento…")
    assert promete_sin_hacer("Déjame comprobarlo.")
    assert not promete_sin_hacer("Tus ingresos de este mes son 1.480,00 €.")
    assert not promete_sin_hacer("¿Quieres que voy a comparar los dos años?")  # pregunta: no es promesa
    assert not promete_sin_hacer("Voy a explicarte primero. Este mes ingresaste 1.480,00 €.")  # la promesa no es lo último
    assert not promete_sin_hacer("")


def test_importes_sin_respaldo_detecta_cifras_inventadas():
    from backend.aplicacion.texto import afirma_haber_hecho_un_grafico, importes_en, importes_sin_respaldo

    assert importes_en("Has recibido 1.480,00 € y 96 770,00 € y 5,5 €") == {1480.0, 96770.0, 5.5}
    contexto = 'Este mes cobraste 1.480,00 € {"saldo": 4200.0, "importe": -12.99}'
    assert importes_sin_respaldo("Tu nómina fue de 1.480,00 € y tienes 4.200,00 €", contexto) == set()
    assert importes_sin_respaldo("Recibiste 96 770,00 € por Bizum", contexto) == {96770.0}
    assert afirma_haber_hecho_un_grafico("Texto.\n\n**Gráfico comparativo:** barras agrupadas")
    assert afirma_haber_hecho_un_grafico("Aquí tienes el gráfico de tus gastos")
    assert not afirma_haber_hecho_un_grafico("¿Quieres que te haga un gráfico?")


def test_pide_un_bizum_solo_con_orden_completa_y_viable():
    from backend.aplicacion.texto import pide_un_bizum

    assert pide_un_bizum("Envía 5 euros por Bizum a Ana con concepto prueba", 1000)
    assert pide_un_bizum("mándale un bizum de 12,50 € a Luis", 1000)
    for no in ("¿qué es un Bizum?", "cuánto he enviado por Bizum", "envía un bizum de 500 USD a María",
               "envía 5000 euros por bizum a Ana", "envía bizum a Ana", "he enviado 5 euros por bizum a Ana"):
        assert not pide_un_bizum(no, 1000), no


def test_pide_un_bizum_acepta_importe_sin_unidad_si_la_orden_es_inequivoca():
    from backend.aplicacion.texto import datos_de_orden_bizum, pide_un_bizum

    for si in ("Haz un bizum de 5 a dani", "hazme un bizum de 5,50 a mamá", "mándale 10 a mamá", "enviale 5 a dani", "envíale 2.5 a Dani",
               "bizum de 5 a dani", "envía un bizum de 5 a carmen con concepto cena", "mandale un bizum de 5 a dani"):
        assert pide_un_bizum(si, 1000), si
    for no in ("¿qué es un Bizum?", "cuánto he enviado por Bizum", "he enviado 5 euros por bizum a Ana", "envía 5 dólares por bizum a ana",
               "envía 5000 a dani por bizum", "haz un bizum de 5000 a dani", "envía 5 euros y 7 euros por bizum a ana",
               "haz un bizum de 5 a dani?", "mándale a dani el recibo del día 3 de octubre", "envía un bizum a dani el 3 de octubre"):
        assert not pide_un_bizum(no, 1000), no


def test_datos_de_orden_bizum_saca_destinatario_importe_y_concepto_solo_si_los_dijo():
    from backend.aplicacion.texto import datos_de_orden_bizum

    assert datos_de_orden_bizum("Haz un bizum de 5 a dani", 1000) == {"destinatario": "dani", "importe": 5.0}
    assert datos_de_orden_bizum("envía un bizum de 5 a carmen con concepto cena", 1000) == {
        "destinatario": "carmen", "importe": 5.0, "concepto": "cena"}
    assert datos_de_orden_bizum("envía 5 euros por bizum a Pepe", 1000)["destinatario"] == "Pepe"
    assert datos_de_orden_bizum("¿qué es un Bizum?", 1000) is None
