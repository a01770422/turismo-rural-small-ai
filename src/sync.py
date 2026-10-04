"""Store-and-forward: guarda local, procesa, y envía cuando hay señal."""
import json
import os
import threading
import time
import uuid

from . import channels, db, places_osm, utils

INTENTS = utils.load_json("intents.json")
PHRASES = utils.load_json("phrases.json")
DEFAULT_OP = {"price": "(sin definir)", "hours": "(sin definir)", "meeting_point": "(sin definir)",
              "contact": "(sin definir)", "duration": "(sin definir)", "includes": "(sin definir)", "payment": "(sin definir)"}
INFO = ["precio", "horario", "duracion", "direcciones", "incluye", "pago"]  # "Toda la información" en un solo mensaje


def operator():
    """Datos de la finca: valores por defecto < operator.json < lo guardado desde la web ("Mis datos").

    operator.json lleva el precio y el teléfono de quien instale la app, así que no va al
    repositorio. Si no existe (recién clonado), se parte del ejemplo y, si tampoco está,
    de los valores por defecto: la app arranca igual y se rellena desde "Mis datos"."""
    op = dict(DEFAULT_OP)
    for nombre in ("operator.json", "operator.example.json"):
        try:
            op.update(utils.load_json(nombre))
            break
        except FileNotFoundError:
            continue
    try:
        op.update(json.loads(db.meta_get("operator") or "{}"))
    except Exception:
        pass
    return op


def templates(lang):
    """Respuestas rápidas (lista cerrada) en el idioma del visitante; si falta el idioma, cae a español."""
    op = operator()
    out = [{"intent": n, "label": d["label"], "icon": d.get("icon", ""), "lang_ok": lang in d["replies"],
            "text": utils.draft_reply([n], lang, INTENTS, op, greet=False)} for n, d in INTENTS.items()]
    full = "\n".join(utils.draft_reply([n], lang, INTENTS, op, greet=False) for n in INFO)
    out.append({"intent": "todo", "label": "Toda la información", "icon": "list",
                "lang_ok": all(lang in INTENTS[n]["replies"] for n in INFO), "text": full})
    return out


def relang(mid, lang):
    """La persona corrige el idioma detectado: se rehace la traducción y el borrador en ese idioma."""
    m = db.get(mid)
    if not m or m["status"] != "pending":
        return None
    names = [n for n in (m["intent"] or "").split(",") if n in INTENTS]
    draft = utils.draft_reply(names, lang, INTENTS, operator()) if names else m["proposed_response"]
    db.update(mid, lang=lang, translated_text=utils.translate(m["original_text"], lang, "es"), proposed_response=draft)
    return mid


def tr(text, src, dst):
    """Frases guardadas primero (sin internet); si no, traductor en línea (None si no hay red)."""
    return utils.phrase_lookup(text, src, dst, PHRASES["phrases"]) or utils.translate(text, src, dst)


def ingest(text, channel="manual", chat_id=None, lang=None, name=None):
    """Mensaje entrante -> SQLite como 'pending' (la traducción puede quedar pendiente si no hay red)."""
    lang = lang or utils.detect_lang(text)
    chat_id = chat_id or "m" + uuid.uuid4().hex[:10]  # sin conversación previa: chat nuevo
    if utils.is_sensitive(text):
        names, conf, draft = ["alerta"], 1.0, None  # mensaje delicado: lo atiende una persona
    else:
        names, conf = utils.classify(text, INTENTS)
        draft = utils.draft_reply(names, lang, INTENTS, operator()) if names else None
    return db.add_message(
        channel=channel, chat_id=chat_id, lang=lang, original_text=text, name=name,
        translated_text=tr(text, lang, "es"), intent=",".join(names) or None, confidence=conf,
        needs_human=int(draft is None), proposed_response=draft)


# ---------- Chat (estilo WhatsApp) ----------
def send_host(channel, chat_id, text, host_text=None, in_spanish=False):
    """La persona a cargo escribe en el chat: queda en la cola y se envía (traducido) en cuanto se pueda."""
    rows = db.chat_rows(channel, chat_id)
    if not rows:
        return None
    lang = next((r["lang"] for r in reversed(rows) if r["original_text"]), rows[-1]["lang"]) or "es"
    mid = db.add_message(channel=channel, chat_id=chat_id, lang=lang, host_text=host_text or text,
                         final_response=text, final_is_es=int(in_spanish and lang != "es"), status="approved")
    db.mark_answered(channel, chat_id)
    try:
        flush_outbox()
    except Exception:
        pass
    return mid


def chats():
    """Lista de conversaciones (la más reciente primero) con vista previa y mensajes sin responder."""
    out = {}
    for r in reversed(db.recent_rows()):
        k = (r["channel"], r["chat_id"])
        c = out.setdefault(k, {"channel": r["channel"], "chat_id": r["chat_id"], "name": None, "lang": r["lang"],
                               "pending": 0, "alert": False})
        if r["original_text"]:
            c["lang"] = r["lang"]
            c["pending"] += r["status"] == "pending"
            c["alert"] = c["alert"] or (r["intent"] == "alerta" and r["status"] == "pending")
            c["preview"], c["from"] = (r["translated_text"] or r["original_text"]), "them"
        if r["final_response"]:
            c["preview"], c["from"] = (r["host_text"] or r["final_response"]), "me"
        c["name"] = r["name"] or c["name"]
        c["at"], c["last_id"] = r["created_at"], r["id"]
    return sorted(out.values(), key=lambda c: -c["last_id"])


def visitor_view(chat_id, after=0):
    """Lo que ve el visitante: sus mensajes y las respuestas ya enviadas (en su idioma)."""
    out = []
    for r in db.chat_rows("web", chat_id):
        if r["original_text"]:
            out.append({"id": r["id"] * 2, "who": "me", "text": r["original_text"], "at": r["created_at"]})
        if r["final_response"] and r["status"] == "synced":
            out.append({"id": r["id"] * 2 + 1, "who": "host", "text": r["final_response"], "at": r["created_at"]})
    return [m for m in out if m["id"] > after]


def followup(mid):
    """Seguimiento al visitante (agradecer y pedir reseña): crea un borrador que la persona debe aprobar."""
    m = db.get(mid)
    if not m:
        return None
    return db.add_message(
        channel=m["channel"], chat_id=m["chat_id"], lang=m["lang"], original_text="(Seguimiento al visitante)",
        translated_text="(Seguimiento al visitante)", intent="seguimiento", confidence=1.0, needs_human=0,
        proposed_response=utils.draft_reply(["seguimiento"], m["lang"], INTENTS, operator()))


def poll_inbox():
    if not channels.enabled():
        return 0
    msgs, last = channels.fetch_new(int(db.meta_get("tg_offset") or 0))
    n = 0
    for m in msgs:
        if m["text"].startswith("/"):  # /start y otros comandos de Telegram no son consultas
            continue
        ingest(m["text"], "telegram", m["chat_id"])
        n += 1
    db.meta_set("tg_offset", str(last))
    return n


def fill_translations():
    for m in db.list_messages("pending"):
        if m["translated_text"] is None:
            t = utils.translate(m["original_text"], m["lang"], "es")
            if t is None:
                break  # sigue sin red
            db.update(m["id"], translated_text=t)


def flush_outbox():
    """Envía lo aprobado. Sin red / sin traducción -> se queda 'approved' y se reintenta."""
    sent = 0
    for m in db.list_messages("approved"):
        text = m["final_response"]
        if m["final_is_es"] and m["lang"] != "es":
            text = tr(text, "es", m["lang"])
            if text is None:
                continue
            db.update(m["id"], final_response=text, final_is_es=0)
        try:
            if m["channel"] == "telegram":
                channels.send(m["chat_id"], text)
        except Exception:
            continue
        db.update(m["id"], status="synced")  # chat web / manual: el visitante ya lo ve
        sent += 1
    return sent


def run_once():
    got = 0
    try:
        places_osm.refresh_if_stale()
    except Exception:
        pass
    try:
        got = poll_inbox()
    except Exception:
        pass
    try:
        days = int(os.getenv("RETENTION_DAYS", "30"))
        if days > 0:
            db.purge_old(days)
    except Exception:
        pass
    try:
        fill_translations()
        return got, flush_outbox()
    except Exception:
        return got, 0


def _loop(every):
    while True:
        run_once()
        time.sleep(every)


def start_background():
    every = int(os.getenv("AUTO_SYNC_SECONDS", "30"))
    if every > 0:
        threading.Thread(target=_loop, args=(every,), daemon=True).start()
