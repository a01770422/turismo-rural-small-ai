"""Desglose de una traducción: cómo suena, palabra por palabra y otras formas de decirlo.

Nada aquí toca la red: lo que se comprueba es el filtrado, que es donde se decide
qué se le enseña a la persona y qué sería ruido.
"""
import os
import tempfile

import pytest

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")

from src import utils  # noqa: E402


@pytest.mark.parametrize("texto,lang,espera", [
    ("Спасибо", "ru", "spasibo"),
    ("Здравствуйте", "ru", "zdravstvuytye"),
    ("Καλημέρα", "el", "kalimera"),      # el acento no debe quedarse sin convertir
    ("नमस्ते", "hi", "namaste"),          # la vocal implícita se quita ante vocal o virama
])
def test_como_suena(texto, lang, espera):
    assert utils.romanizar(texto, lang) == espera


def test_no_se_inventa_pronunciacion_donde_no_puede():
    """Chino, japonés y coreano necesitan un diccionario entero: mejor no decir nada
    que decir algo que no se pronuncia así."""
    for t, l in [("你好", "zh"), ("こんにちは", "ja"), ("안녕하세요", "ko")]:
        assert utils.romanizar(t, l) is None


def test_no_molesta_con_lo_que_ya_se_lee():
    assert utils.romanizar("hola", "es") is None
    assert utils.romanizar("hello", "en") is None


def test_palabra_por_palabra_salta_articulos_y_repetidas(monkeypatch):
    """'el' suelto sale como 'By' y no aporta; y una palabra repetida no se pregunta dos veces."""
    pedidas = []

    def falso(w, src, dst):
        pedidas.append(w)
        return "en:" + w

    monkeypatch.setattr(utils, "translate", falso)
    out = utils.palabra_por_palabra("el precio de la entrada y el precio del guía", "es", "en", [])
    assert [p["de"] for p in out] == ["precio", "entrada", "guía"]
    assert pedidas.count("precio") == 1, "no debe preguntarse dos veces lo mismo"


def test_palabra_por_palabra_respeta_el_limite(monkeypatch):
    """Una frase larga no debe disparar veinte consultas al traductor."""
    pedidas = []
    monkeypatch.setattr(utils, "translate", lambda w, s, d: pedidas.append(w) or ("en:" + w))
    texto = ("lunes martes miercoles jueves viernes sabado domingo enero febrero marzo "
             "abril mayo junio julio agosto")
    assert len(utils.palabra_por_palabra(texto, "es", "en", [], limite=5)) == 5
    assert len(pedidas) == 5, "no debe traducir las que no va a mostrar"


def test_palabra_por_palabra_omite_lo_que_no_cambia(monkeypatch):
    """Si la 'traducción' es la misma palabra, no se enseña: suele ser un nombre propio
    o que el traductor devolvió lo que le entró."""
    monkeypatch.setattr(utils, "translate", lambda w, s, d: w)
    assert utils.palabra_por_palabra("Toluca museo", "es", "en", []) == []


def test_palabra_por_palabra_usa_primero_el_frasario(monkeypatch):
    """Lo que ya está guardado no debe gastar el traductor: funciona sin internet."""
    def nada(w, s, d):
        raise AssertionError("no debía salir a internet")

    monkeypatch.setattr(utils, "translate", nada)
    frases = [{"id": "x", "t": {"es": "gracias", "en": "thank you"}}]
    assert utils.palabra_por_palabra("gracias", "es", "en", frases) == [{"de": "gracias", "a": "thank you"}]


def _matches(*pares):
    return {"matches": [{"translation": t, "match": m} for t, m in pares]}


def test_alternativas_descarta_lo_que_despista(monkeypatch):
    monkeypatch.setattr(utils, "_get", lambda url, timeout=4: _matches(
        ("Where is the bathroom?", 0.98),                       # igual a la principal
        ("Where is the toilet?", 0.97),                         # sirve
        ("Q: Where is the bathroom in the old museum?", 0.97),  # otra oración más larga
        ("The bathroom?", 0.96),                                # trozo suelto
        ("where is the bathrooms?", 0.95),                      # casi idéntica
        ("Hello", 0.40),                                        # no se parece a lo escrito
    ))
    out = utils.alternativas("¿dónde está el baño?", "es", "en", "Where is the bathroom?")
    assert out == ["Where is the toilet?"]


def test_alternativas_no_falla_sin_internet(monkeypatch):
    def cae(url, timeout=4):
        raise OSError("sin red")

    monkeypatch.setattr(utils, "_get", cae)
    assert utils.alternativas("hola", "es", "en", "hello") == []


def test_alternativas_no_pregunta_si_no_tiene_sentido():
    """Mismo idioma o 'auto' no dan alternativas: no hay nada que comparar."""
    assert utils.alternativas("hola", "es", "es", "hola") == []
    assert utils.alternativas("hola", "auto", "en", "hello") == []
