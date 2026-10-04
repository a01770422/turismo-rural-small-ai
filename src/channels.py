"""Canal de mensajería: Telegram Bot API (gratis; por polling no necesita URL pública).
Para SMS/WhatsApp, reemplaza fetch_new() y send() y deja el resto igual."""
import json
import os
import urllib.parse
import urllib.request

URL = "https://api.telegram.org/bot{}/{}"


def enabled():
    return bool(os.getenv("TELEGRAM_BOT_TOKEN"))


def _call(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(URL.format(os.getenv("TELEGRAM_BOT_TOKEN"), method), data=data, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_new(offset):
    """Devuelve ([{chat_id, text}], siguiente_offset)."""
    out, last = [], offset
    for u in _call("getUpdates", offset=offset, timeout=0).get("result", []):
        last = u["update_id"] + 1
        m = u.get("message") or {}
        if m.get("text"):
            out.append({"chat_id": str(m["chat"]["id"]), "text": m["text"][:500]})
    return out, last


def send(chat_id, text):
    _call("sendMessage", chat_id=chat_id, text=text)
