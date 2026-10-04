"""Catálogo de etiquetas de la cámara y los vectores que se calculan a partir de él.

El modelo que mira la foto corre en el navegador, así que aquí no se prueba el acierto:
se prueba que el catálogo esté bien formado y que servidor y navegador no se desincronicen.
"""
import base64
import json
import os
import tempfile

import pytest

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["OSM_CACHE"] = os.path.join(tempfile.mkdtemp(), "osm.json")

from fastapi import HTTPException  # noqa: E402

from src import api, utils  # noqa: E402


def test_catalogo_bien_formado():
    cat = utils.load_json("vision_labels.json")
    assert "{}" in cat["plantilla"]
    ids = [g["id"] for g in cat["grupos"]]
    assert len(ids) == len(set(ids)), "hay grupos con el mismo id"
    vistos = set()
    for g in cat["grupos"]:
        assert g["nombre"] and g["icon"] and g["labels"]
        # Con demasiadas opciones parecidas el modelo empieza a confundirse.
        assert len(g["labels"]) <= 15, f"el grupo {g['id']} tiene demasiadas etiquetas"
        for lb in g["labels"]:
            assert lb["en"].strip() and lb["es"].strip()
            assert lb["en"] not in vistos, f"etiqueta repetida: {lb['en']}"
            vistos.add(lb["en"])


def test_la_firma_cambia_al_editar_una_etiqueta():
    cat = utils.load_json("vision_labels.json")
    antes = utils.vision_firma(cat)
    assert antes == utils.vision_firma(cat), "la firma debe ser estable"
    cat["grupos"][0]["labels"][0]["en"] += " azul"
    assert utils.vision_firma(cat) != antes


def test_cambiar_solo_el_espanol_no_altera_la_firma():
    """El texto en español es solo para mostrar; no se le pregunta al modelo,
    así que cambiarlo no obliga a recalcular los vectores."""
    cat = utils.load_json("vision_labels.json")
    antes = utils.vision_firma(cat)
    cat["grupos"][0]["labels"][0]["es"] = "otra cosa"
    assert utils.vision_firma(cat) == antes


def test_endpoint_devuelve_firma_y_grupos():
    d = api.vision_labels()
    assert d["firma"] == utils.vision_firma(utils.load_json("vision_labels.json"))
    assert d["grupos"]


def test_vectores_guardados_coinciden_con_el_catalogo():
    """Si falla: entrar a Mirar y pulsar recalcular."""
    if not api.EMB_FILE.exists():
        pytest.skip("aún no se han generado; la app lo avisa en pantalla")
    emb, cat = api.vision_embeddings(), utils.load_json("vision_labels.json")
    n = sum(len(g["labels"]) for g in cat["grupos"])
    assert emb["n"] == n, "sobran o faltan vectores"
    assert emb["firma"] == utils.vision_firma(cat), "las etiquetas cambiaron tras calcular los vectores"
    assert len(base64.b64decode(emb["datos"])) == emb["n"] * emb["dim"] * (emb.get("bits", 8) // 8)


def test_rechaza_vectores_con_tamano_que_no_cuadra():
    cuerpo = api.EmbIn(modelo="x", plantilla="a photo of {}", dim=512, escala=1.0,
                       n=44, firma="abc", datos=base64.b64encode(b"corto").decode())
    with pytest.raises(HTTPException) as e:
        api.save_vision_embeddings(cuerpo)
    assert e.value.status_code == 400


def vectores(n, dim, bits=16, firma="f1"):
    return api.EmbIn(modelo="m", plantilla="a photo of {}", dim=dim, escala=32767.0, bits=bits,
                     n=n, firma=firma, datos=base64.b64encode(bytes(n * dim * (bits // 8))).decode())


def test_guardar_y_releer(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "EMB_FILE", tmp_path / "emb.json")
    assert api.save_vision_embeddings(vectores(2, 8))["n"] == 2
    assert json.loads((tmp_path / "emb.json").read_text(encoding="utf-8"))["bits"] == 16
    assert api.vision_embeddings()["firma"] == "f1"


def test_sigue_aceptando_los_vectores_de_8_bits(tmp_path, monkeypatch):
    """Los archivos generados antes de pasar a 16 bits deben seguir valiendo."""
    monkeypatch.setattr(api, "EMB_FILE", tmp_path / "emb.json")
    assert api.save_vision_embeddings(vectores(2, 8, bits=8))["n"] == 2
    assert api.vision_embeddings()["bits"] == 8


def test_avisa_si_no_hay_vectores(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "EMB_FILE", tmp_path / "no_existe.json")
    with pytest.raises(HTTPException) as e:
        api.vision_embeddings()
    assert e.value.status_code == 404


def test_rechaza_base64_invalido():
    cuerpo = api.EmbIn(modelo="x", plantilla="a photo of {}", dim=8, escala=1.0,
                       n=1, firma="abc", datos="esto no es base64 !!")
    with pytest.raises(HTTPException) as e:
        api.save_vision_embeddings(cuerpo)
    assert e.value.status_code == 400


def test_no_deja_el_archivo_a_medias(tmp_path, monkeypatch):
    """Un guardado que falle no debe truncar los vectores que ya funcionaban."""
    dest = tmp_path / "emb.json"
    monkeypatch.setattr(api, "EMB_FILE", dest)
    api.save_vision_embeddings(vectores(2, 8))
    malo = api.EmbIn(modelo="m", plantilla="a photo of {}", dim=8, escala=1.0, n=99,
                     firma="f2", datos=base64.b64encode(bytes(32)).decode())
    with pytest.raises(HTTPException):
        api.save_vision_embeddings(malo)
    assert json.loads(dest.read_text(encoding="utf-8"))["firma"] == "f1"


@pytest.mark.parametrize("romper,espera", [
    (lambda c: c["grupos"][0]["labels"][0].pop("en"), "falta 'en'"),
    (lambda c: c["grupos"][0].pop("icon"), "falta 'icon'"),
    (lambda c: c["grupos"][1].update(labels=[]), "no tiene etiquetas"),
    (lambda c: c.update(plantilla="una foto"), "plantilla"),
    (lambda c: c.update(grupos=[]), "grupos"),
])
def test_explica_que_falta_si_editan_mal_las_etiquetas(romper, espera):
    """El archivo lo edita quien conoce la zona, no un programador: un olvido tiene que
    explicarse, no reventar con un error incomprensible."""
    cat = utils.load_json("vision_labels.json")
    romper(cat)
    fallo = utils.vision_revisar(cat)
    assert fallo and espera in fallo


def test_el_catalogo_actual_pasa_la_revision():
    assert utils.vision_revisar(utils.load_json("vision_labels.json")) is None


def test_el_motor_lo_sirve_este_equipo():
    """Si el motor se trae de un CDN, la app no arranca sin internet por muy guardados que
    estén los modelos. Ya pasó una vez: estos archivos tienen que estar y nadie debe
    volver a apuntar a una dirección de fuera."""
    vendor = api.STATIC / "vendor"
    for f in ("transformers.min.js", "ort-wasm-simd-threaded.jsep.mjs",
              "ort-wasm-simd-threaded.jsep.wasm"):
        assert (vendor / f).is_file(), f"falta src/static/vendor/{f}"
    ai = (api.STATIC / "ai.js").read_text(encoding="utf-8")
    assert "https://cdn." not in ai and "http://" not in ai, "ai.js no debe cargar nada de internet"
    # Las rutas se calculan desde la del propio ai.js, para que la app funcione igual en la
    # raíz del servidor local que dentro de una carpeta en un hosting.
    assert "import.meta.url" in ai and "vendor/" in ai
