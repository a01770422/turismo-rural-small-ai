"""Idioma de la app: el panel se muestra en el del navegador y, si no está traducido, en inglés.

Lo que se vigila aquí es la deriva: la clave del diccionario es el texto en español tal cual
aparece en el código, así que si alguien cambia una frase y no toca data/ui.json, la
traducción deja de aplicarse en silencio. Estas pruebas lo detectan.
"""
import json
import os
import re
import tempfile

import pytest

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")

from src import api, utils  # noqa: E402

UI = utils.load_json("ui.json")
PANEL = (api.STATIC / "index.html").read_text(encoding="utf-8")
JS = PANEL[PANEL.index("<script>", PANEL.index("<body")):] + (api.STATIC / "ai.js").read_text(encoding="utf-8")
# En el código las frases largas van partidas en varias líneas; al buscarlas hay que
# comparar con los espacios ya normalizados, igual que hace la app. Se suman los archivos
# de datos cuyos textos también se traducen al mostrarlos (nombres de los grupos de la cámara).
FUENTE = re.sub(r"\s+", " ", "\n".join([
    PANEL[PANEL.index("<body"):],
    (api.STATIC / "ai.js").read_text(encoding="utf-8"),
    (utils.DATA / "vision_labels.json").read_text(encoding="utf-8"),
]))


def test_el_bloque_de_cada_idioma_existe_y_no_esta_vacio():
    assert UI["idiomas"]["es"], "el español es el original y debe estar listado"
    for codigo in UI["idiomas"]:
        if codigo == "es":
            continue
        assert UI.get(codigo), f"'{codigo}' aparece en 'idiomas' pero no tiene traducciones"


def test_ninguna_traduccion_quedo_en_blanco():
    for codigo in UI["idiomas"]:
        for clave, valor in (UI.get(codigo) or {}).items():
            assert str(valor).strip(), f"{codigo}: '{clave}' está sin traducir"


def test_las_claves_no_llevan_espacios_de_mas():
    """Se buscan por texto exacto (ya normalizado), así que un doble espacio no casaría nunca."""
    for codigo in UI["idiomas"]:
        for clave in (UI.get(codigo) or {}):
            assert re.sub(r"\s+", " ", clave) == clave, f"{codigo}: '{clave}' tiene espacios raros"


def test_todo_lo_envuelto_en_T_tiene_traduccion():
    """Si el código llama a T('algo'), ese 'algo' tiene que estar en el diccionario.
    Si no, la app se queda en español en ese punto sin avisar."""
    usadas = set(re.findall(r"T\('((?:[^'\\]|\\.)*)'\)", JS))
    usadas |= set(re.findall(r'T\("((?:[^"\\]|\\.)*)"\)', JS))
    usadas = {u.replace("\\'", "'").replace('\\"', '"') for u in usadas}
    faltan = sorted(u for u in usadas if u not in UI["en"])
    assert not faltan, "T() usa textos que no están en data/ui.json: " + "; ".join(faltan[:8])


def test_el_diccionario_no_arrastra_claves_muertas():
    """Lo contrario: una clave que ya no usa nadie solo estorba al traducir a otro idioma."""
    muertas = [c for c in UI["en"] if re.sub(r"\s+", " ", c) not in FUENTE]
    assert not muertas, "sobran en data/ui.json (ya no aparecen en la app): " + "; ".join(muertas[:8])


def test_el_selector_y_el_endpoint_existen():
    assert 'id="uilang"' in PANEL, "falta el selector de idioma"
    d = api.ui()
    assert d["idiomas"] and d["en"]


def test_el_chat_del_visitante_puede_leer_los_idiomas():
    """chat.html se abre desde otros teléfonos: el endpoint tiene que estar permitido."""
    assert api.PUBLIC.match("/api/ui"), "/api/ui debe ser accesible desde la red local"


@pytest.mark.parametrize("ruta", ["/api/operator", "/api/chats", "/api/sync"])
def test_el_panel_sigue_siendo_solo_de_este_equipo(ruta):
    assert not api.PUBLIC.match(ruta), f"{ruta} no debe quedar expuesto"
