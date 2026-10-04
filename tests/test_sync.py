import json
import os
import tempfile

import pytest

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")

from src import db, sync, utils  # noqa: E402

ONLINE = {"on": False}


def fake_translate(text, src, dst):
    if src == dst:
        return text
    return f"[{dst}] {text}" if ONLINE["on"] else None


@pytest.fixture(autouse=True)
def _sin_internet_real(monkeypatch):
    """Traducción simulada solo en este archivo (no afecta a otras pruebas)."""
    monkeypatch.setattr(utils, "translate", fake_translate)


def test_offline_guarda_pendiente_y_traduce_despues():
    ONLINE["on"] = False
    mid = sync.ingest("How much does the tour cost?")
    m = db.get(mid)
    assert m["status"] == "pending" and m["lang"] == "en" and m["intent"] == "precio"
    assert m["translated_text"] is None
    ONLINE["on"] = True
    sync.fill_translations()
    assert db.get(mid)["translated_text"].startswith("[es]")


def test_failsafe_sin_borrador():
    m = db.get(sync.ingest("asdf qwerty"))
    assert m["needs_human"] == 1 and m["proposed_response"] is None


def test_aprobado_espera_red_y_luego_se_traduce_y_sincroniza():
    ONLINE["on"] = True
    mid = sync.ingest("Where is the meeting point?")
    db.update(mid, final_response="Nos vemos en la entrada", final_is_es=1, status="approved")
    ONLINE["on"] = False
    assert sync.flush_outbox() == 0 and db.get(mid)["status"] == "approved"
    ONLINE["on"] = True
    assert sync.flush_outbox() >= 1
    m = db.get(mid)
    assert m["status"] == "synced" and m["final_response"].startswith("[en]")


def test_alerta_no_redacta_respuesta():
    m = db.get(sync.ingest("Tengo una queja sobre el guía"))
    assert m["intent"] == "alerta" and m["needs_human"] == 1 and m["proposed_response"] is None


def test_varias_intenciones_y_datos_editables():
    db.meta_set("operator", json.dumps({"price": "500 MXN"}))
    m = db.get(sync.ingest("How much and what time do you open?"))
    assert set(m["intent"].split(",")) == {"precio", "horario"}
    assert "500 MXN" in m["proposed_response"] and m["proposed_response"].startswith("Hello!")


def test_seguimiento_y_retencion():
    mid = sync.ingest("Where is the meeting point?")
    f = db.get(sync.followup(mid))
    assert f["intent"] == "seguimiento" and f["lang"] == "en" and f["proposed_response"].startswith("Thank you")
    db.update(mid, status="synced")
    with db.conn() as c:
        c.execute("UPDATE messages SET created_at='2000-01-01 00:00:00' WHERE id=?", (mid,))
    assert db.purge_old(30) >= 1 and db.get(mid) is None


def test_plantillas_con_respaldo_en_espanol():
    ts = {t["intent"]: t for t in sync.templates("en")}
    assert ts["precio"]["text"].startswith("The tour costs") and ts["precio"]["lang_ok"]
    assert not {t["intent"]: t for t in sync.templates("zz")}["precio"]["lang_ok"]


def test_corregir_idioma_rehace_borrador():
    ONLINE["on"] = False
    mid = sync.ingest("prezzo?", lang="es")
    assert db.get(mid)["proposed_response"].startswith("¡Hola!")
    sync.relang(mid, "it")
    m = db.get(mid)
    assert m["lang"] == "it" and m["proposed_response"].startswith("Ciao!")


def test_toda_la_informacion_en_un_mensaje():
    t = {x["intent"]: x for x in sync.templates("en")}["todo"]
    assert t["lang_ok"] and t["text"].startswith("The tour costs") and "\n" in t["text"]
    assert not {x["intent"]: x for x in sync.templates("th")}["todo"]["lang_ok"]  # sin plantilla: va en español
