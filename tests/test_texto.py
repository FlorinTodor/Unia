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
