import base64
import binascii
import hmac
import json
import os
import re
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from . import db, places_osm, sync, utils  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
IMG = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jfif": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


@asynccontextmanager
async def lifespan(app):
    sync.start_background()
    yield


app = FastAPI(title="Turismo Rural – Small AI", lifespan=lifespan)
LOCAL = {"127.0.0.1", "::1", "localhost", "testclient"}
PUBLIC = re.compile(r"^/(chat|hero|static/.*|api/chat/[A-Za-z0-9-]+|api/phrases|api/ui)$")


@app.middleware("http")
async def solo_chat_desde_la_red(request: Request, call_next):
    """Si la app se abre en la wifi (HOST=0.0.0.0), otros teléfonos solo pueden usar el chat de visitantes.
    El panel de la persona a cargo (mensajes, datos, reseñas a moderar…) solo responde en este equipo."""
    host = request.client.host if request.client else ""
    if host not in LOCAL and not PUBLIC.match(request.url.path):
        return JSONResponse({"detail": "Solo disponible en el equipo de la persona a cargo."}, status_code=403)
    r = await call_next(request)
    # El navegador se quedaba con la versión vieja de la app tras actualizarla. Ahora revalida
    # siempre (en local cuesta nada), salvo el motor de static/vendor, que nunca cambia y pesa 22 MB.
    if request.url.path.startswith("/static/"):
        r.headers["Cache-Control"] = ("public, max-age=31536000, immutable"
                                      if request.url.path.startswith("/static/vendor/") else "no-cache")
    return r


class Msg(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    lang: str | None = None
    chat_id: str | None = None


class Approve(BaseModel):
    response: str = Field(min_length=1, max_length=500)
    in_spanish: bool = False


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    lang: str = Field(min_length=2, max_length=8, pattern=r"^[a-z]+$")
    name: str = Field("", max_length=30)


class HostIn(BaseModel):
    channel: str = Field(max_length=20)
    chat_id: str = Field(max_length=80)
    text: str = Field(min_length=1, max_length=500)
    host_text: str = Field("", max_length=500)
    in_spanish: bool = False


class LangIn(BaseModel):
    lang: str = Field(min_length=2, max_length=8, pattern=r"^[a-z]+$")


class TrIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    src: str = Field(min_length=2, max_length=8, pattern=r"^[a-z]+$")  # 'auto' = detectar
    dst: str = Field(min_length=2, max_length=8, pattern=r"^[a-z]+$")


class AreaIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: int = Field(15000, ge=1000, le=30000)
    name: str = Field("", max_length=200)


class OperatorIn(BaseModel):
    price: str = Field("", max_length=120)
    hours: str = Field("", max_length=120)
    meeting_point: str = Field("", max_length=120)
    contact: str = Field("", max_length=120)
    duration: str = Field("", max_length=120)
    includes: str = Field("", max_length=120)
    payment: str = Field("", max_length=120)


class EmbIn(BaseModel):
    modelo: str = Field(max_length=120)
    plantilla: str = Field(max_length=200)
    dim: int = Field(ge=8, le=4096)
    escala: float = Field(gt=0)
    bits: int = Field(16, ge=8, le=16, multiple_of=8)  # 8 = archivos de antes
    n: int = Field(ge=1, le=500)
    firma: str = Field(max_length=64)
    datos: str = Field(max_length=8_000_000)  # enteros en base64, n x dim


class Reviews(BaseModel):
    reviews: list[str]


class ReviewIn(BaseModel):
    author: str = Field(max_length=30)
    rating: int = Field(ge=1, le=5)
    text: str = Field(max_length=500)


def _catalog():
    """Catálogo + calificación calculada con las reseñas publicadas."""
    stats = db.review_stats()
    return [{**p, "rating": stats[str(p["id"])][0], "n_reviews": stats[str(p["id"])][1]}
            if str(p["id"]) in stats else p for p in places_osm.catalog()]


@app.get("/api/places")
def places(q: str = ""):
    return utils.rank_places(_catalog(), q)


@app.get("/api/news")
def news():
    return [{**p, "score": utils.score_place(p)} for p in utils.newest(_catalog())]


@app.get("/api/area")
def area_info():
    _, _, r, name = places_osm.area()
    c = places_osm.cached()
    return {"name": name, "radius_km": r // 1000, "count": len(c["places"]), "updated": c["updated"]}


@app.post("/api/places/refresh")
def refresh_places():
    try:
        return {"count": places_osm.refresh()}
    except Exception:
        raise HTTPException(503, "sin conexión: se conservan los lugares guardados")


@app.get("/api/geocode")
def geocode(q: str = Query(min_length=2, max_length=100)):
    try:
        return places_osm.geocode(q)
    except Exception:
        raise HTTPException(503, "sin conexión")


@app.post("/api/area")
def set_area(a: AreaIn):
    """Cambia la zona (buscada por nombre o por ubicación actual) y descarga sus lugares."""
    name = a.name.strip() or places_osm.reverse(a.lat, a.lon) or "Mi ubicación"
    try:
        n = places_osm.refresh(a.lat, a.lon, a.radius_m, name)
    except Exception:
        raise HTTPException(503, "sin conexión: se conserva la zona anterior")
    return {"count": n, "name": name}


@app.get("/api/weather/{pid}")
def weather(pid: str):
    p = next((x for x in _catalog() if str(x["id"]) == pid), None)
    return utils.weather(p["lat"], p["lon"]) if p else {"data": None, "offline": True}


# ---------- Reseñas ----------
@app.get("/api/places/{pid}/reviews")
def get_reviews(pid: str):
    rs = db.list_reviews(pid)
    s = db.review_stats().get(pid)
    return {"reviews": rs, "n": s[1] if s else 0, "avg": s[0] if s else None,
            "summary": utils.analyze_reviews([r["text"] for r in rs])}


@app.post("/api/places/{pid}/reviews")
def add_review(pid: str, r: ReviewIn):
    if not any(str(p["id"]) == pid for p in places_osm.catalog()):
        raise HTTPException(404, "Lugar no encontrado.")
    author, text = r.author.strip(), r.text.strip()
    err = utils.check_review(author, text)
    if err:
        raise HTTPException(422, err)
    if db.recent_reviews() >= 10:
        raise HTTPException(429, "Demasiadas reseñas seguidas; intenta en un minuto.")
    if db.has_review(pid, author, text):
        raise HTTPException(409, "Esa reseña ya fue publicada.")
    return {"id": db.add_review(pid, author, r.rating, text, utils.detect_lang(text))}


@app.post("/api/reviews/{rid}/hide")
def hide_review(rid: int, x_token: str | None = Header(None)):
    """Moderación por la persona a cargo (requiere API_TOKEN). La reseña se oculta, no se borra."""
    token = os.getenv("API_TOKEN")
    if not token or not hmac.compare_digest(x_token or "", token):
        raise HTTPException(403, "token inválido")
    if not db.hide_review(rid):
        raise HTTPException(404, "no existe")
    return {"hidden": rid}


# ---------- Mensajería (store-and-forward) ----------
@app.post("/api/messages")
def new_message(m: Msg):
    """Entrada manual desde la interfaz local (simula un mensaje de turista)."""
    return db.get(sync.ingest(m.text, "manual", m.chat_id, m.lang))


@app.post("/api/inbox")
def webhook(m: Msg, x_token: str | None = Header(None)):
    """Entrada para proveedores externos (SMS/WhatsApp gateway). Solo activo si API_TOKEN está definido."""
    token = os.getenv("API_TOKEN")
    if not token or not hmac.compare_digest(x_token or "", token):
        raise HTTPException(403, "token inválido")
    return db.get(sync.ingest(m.text, "webhook", m.chat_id, m.lang))


@app.get("/api/messages")
def messages(status: str | None = None):
    return db.list_messages(status)


@app.post("/api/messages/{mid}/followup")
def followup(mid: int):
    new = sync.followup(mid)
    if not new:
        raise HTTPException(404, "no existe")
    return db.get(new)


@app.post("/api/messages/{mid}/lang")
def set_lang(mid: int, b: LangIn):
    """Corregir el idioma del visitante si la detección automática se equivocó."""
    if not sync.relang(mid, b.lang):
        raise HTTPException(404, "no existe o ya fue respondido")
    return db.get(mid)


PHRASES = sync.PHRASES
EMB_FILE = utils.DATA / "vision_labels_emb.json"


@app.get("/api/phrases")
def phrases():
    return PHRASES


@app.get("/api/ui")
def ui():
    """Textos del panel en otros idiomas. La clave es el texto en español tal cual, así que
    traducir es copiar el bloque y cambiar el lado derecho (data/ui.json). Se relee en cada
    consulta para no tener que reiniciar al editarlo."""
    return utils.load_json("ui.json")


@app.get("/api/vision-labels")
def vision_labels():
    """Etiquetas con las que la cámara identifica una foto. Son texto editable (data/vision_labels.json):
    quien conoce la zona puede corregirlas sin tocar el código. 'firma' cambia si se editan, y así
    la app avisa de que los vectores guardados ya no corresponden.
    Se relee en cada consulta (son pocos KB) para no tener que reiniciar al editarlas.
    Si el archivo quedó mal editado se dice exactamente qué falta: es un archivo pensado
    para que lo toque quien conoce la zona, no un programador."""
    try:
        cat = utils.load_json("vision_labels.json")
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"data/vision_labels.json no es JSON válido (línea {e.lineno}): {e.msg}")
    fallo = utils.vision_revisar(cat)
    if fallo:
        raise HTTPException(400, f"data/vision_labels.json: {fallo}")
    return {**cat, "firma": utils.vision_firma(cat)}


@app.get("/api/vision-embeddings")
def vision_embeddings():
    """Vectores de las etiquetas, ya calculados. Gracias a esto el teléfono solo descarga el
    reconocedor de imágenes y no el de texto (que pesa el doble y solo hace falta para generarlos)."""
    if not EMB_FILE.exists():
        raise HTTPException(404, "aún no se han generado")
    return json.loads(EMB_FILE.read_text(encoding="utf-8"))


@app.post("/api/vision-embeddings")
def save_vision_embeddings(b: EmbIn):
    """Guarda los vectores que acaba de calcular el navegador. Solo desde este equipo (ver middleware):
    hace falta tras editar las etiquetas, p. ej. al añadir términos locales."""
    try:
        crudo = base64.b64decode(b.datos, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(400, "los datos no son base64 válido")
    if b.n * b.dim * (b.bits // 8) != len(crudo):
        raise HTTPException(400, "el tamaño de los datos no coincide con n x dim x bits")
    # Se escribe aparte y se sustituye de golpe: si el proceso muere a mitad, el archivo
    # anterior sigue entero en vez de quedar truncado y romper la cámara para siempre.
    tmp = EMB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(b.model_dump(), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, EMB_FILE)
    return {"ok": True, "n": b.n, "dim": b.dim}


@app.post("/api/translate")
def translate(b: TrIn):
    """Traductor: 1) frases guardadas (sin internet)  2) internet (MyMemory, con caché).
    Devuelve el texto, el idioma de origen y de dónde salió la traducción; text=null si no se pudo."""
    src = utils.detect_lang(b.text) if b.src == "auto" else b.src
    hit = utils.phrase_lookup(b.text, b.src, b.dst, PHRASES["phrases"])
    if hit:
        return {"text": hit, "src": src, "via": "frase"}
    out = utils.translate(b.text, src, b.dst)
    return {"text": out, "src": src, "via": "internet" if out is not None else None}


@app.post("/api/translate/detail")
def translate_detail(b: TrIn):
    """Lo mismo que /api/translate pero desglosado, para cuando alguien quiere comprobar
    qué dijo realmente: otras formas de decirlo, qué significa cada palabra y cómo suena.
    Se pide solo cuando se abre el detalle, no en cada mensaje: gasta cuota del traductor."""
    src = utils.detect_lang(b.text) if b.src == "auto" else b.src
    frases = PHRASES["phrases"]
    principal = utils.phrase_lookup(b.text, b.src, b.dst, frases) or utils.translate(b.text, src, b.dst)
    return {
        "text": principal,
        "src": src,
        "alternativas": utils.alternativas(b.text, src, b.dst, principal),
        "palabras": utils.palabra_por_palabra(b.text, src, b.dst, frases),
        "roman_origen": utils.romanizar(b.text, src),
        "roman_destino": utils.romanizar(principal or "", b.dst),
    }


@app.get("/api/templates")
def templates(lang: str = "es"):
    return sync.templates(lang if lang.isalpha() and len(lang) <= 8 else "es")


@app.get("/api/langs")
def langs():
    return sorted({lg for d in sync.INTENTS.values() for lg in d["replies"]})


@app.get("/api/operator")
def get_operator():
    return sync.operator()


@app.put("/api/operator")
def put_operator(o: OperatorIn):
    data = {k: v.strip() for k, v in dict(o).items() if v.strip()}
    db.meta_set("operator", json.dumps(data, ensure_ascii=False))
    return sync.operator()


@app.post("/api/messages/{mid}/approve")
def approve(mid: int, a: Approve):
    """Aprobación humana: solo desde aquí un mensaje pasa a la cola de salida."""
    m = db.get(mid)
    if not m:
        raise HTTPException(404, "no existe")
    if m["status"] != "pending":
        raise HTTPException(409, "ya fue aprobado")
    db.update(mid, final_response=a.response, final_is_es=int(a.in_spanish), status="approved")
    try:
        sync.flush_outbox()
    except Exception:
        pass
    return db.get(mid)


@app.post("/api/sync")
def sync_now():
    got, sent = sync.run_once()
    return {"recibidos": got, "enviados": sent}


@app.post("/api/reviews")
def reviews(r: Reviews):
    return utils.analyze_reviews(r.reviews)


# ---------- Chat estilo WhatsApp ----------
TOKEN = re.compile(r"^[A-Za-z0-9-]{8,64}$")


@app.get("/chat")
def chat_page():
    """Página del visitante: la abre en su teléfono (misma wifi) para escribirte."""
    return FileResponse(STATIC / "chat.html")


@app.post("/api/chat/{token}")
def visitor_send(token: str, m: ChatIn):
    if not TOKEN.match(token):
        raise HTTPException(400, "chat inválido")
    if db.recent_in_chat(token) >= 20:
        raise HTTPException(429, "Demasiados mensajes seguidos; espera un momento.")
    sync.ingest(m.text.strip(), "web", token, m.lang, m.name.strip() or None)
    return {"ok": True}


@app.get("/api/chat/{token}")
def visitor_read(token: str, after: int = 0):
    if not TOKEN.match(token):
        raise HTTPException(400, "chat inválido")
    return sync.visitor_view(token, after)


@app.get("/api/chats")
def chat_list():
    return sync.chats()


@app.get("/api/chats/thread")
def chat_thread(channel: str, chat_id: str):
    return db.chat_rows(channel, chat_id)


@app.post("/api/chats/send")
def chat_send(b: HostIn):
    mid = sync.send_host(b.channel, b.chat_id, b.text.strip(), b.host_text.strip() or None, b.in_spanish)
    if not mid:
        raise HTTPException(404, "no existe ese chat")
    return db.get(mid)


def _lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no envía nada: solo elige la interfaz de la red local
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@app.get("/api/share")
def share():
    """Dirección que el visitante abre en su teléfono para chatear."""
    host, port = os.getenv("HOST", "127.0.0.1"), int(os.getenv("PORT", "8000"))
    lan = host not in ("127.0.0.1", "localhost")
    return {"url": f"http://{_lan_ip() if lan else '127.0.0.1'}:{port}/chat", "lan": lan}


@app.get("/hero")
def hero():
    """Imagen de portada: la primera imagen de la carpeta assets/ (se sirve local, funciona sin internet)."""
    imgs = sorted(f for f in ASSETS.glob("*") if f.suffix.lower() in IMG) if ASSETS.is_dir() else []
    if not imgs:
        raise HTTPException(404, "sin imagen de portada")
    return FileResponse(imgs[0], media_type=IMG[imgs[0].suffix.lower()], headers={"Cache-Control": "max-age=86400"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
