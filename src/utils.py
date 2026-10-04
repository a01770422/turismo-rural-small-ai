"""Lógica ligera: ranking, intención, traducción y reseñas. Solo librería estándar."""
import concurrent.futures
import difflib
import hashlib
import json
import math
import os
import re
import threading
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
CACHE = DATA / "cache.json"

STOP = {
    "es": {"el", "la", "de", "que", "y", "para", "cuanto", "cuesta", "hola", "por", "un", "una", "donde", "como"},
    "en": {"the", "is", "and", "to", "how", "do", "what", "where", "can", "you", "hello", "much"},
    "fr": {"le", "les", "et", "est", "pour", "combien", "bonjour", "je", "vous", "ou", "comment"},
    "pt": {"o", "os", "e", "para", "quanto", "custa", "ola", "um", "uma", "onde", "voce", "obrigado", "tem"},
    "de": {"der", "die", "das", "und", "ist", "wie", "wo", "was", "ich", "sie", "kann", "hallo", "bitte", "viel", "wann"},
    "it": {"il", "di", "che", "per", "ciao", "sono", "dove", "grazie", "buongiorno", "vorrei", "posso", "gli", "della"},
}
# Idiomas con escritura propia: se reconocen por sus letras, sin internet.
SCRIPTS = [("ja", "[぀-ヿ]"), ("ko", "[가-힯ᄀ-ᇿ]"), ("zh", "[一-鿿]"),
           ("ar", "[؀-ۿ]"), ("ru", "[Ѐ-ӿ]"), ("hi", "[ऀ-ॿ]"),
           ("th", "[฀-๿]"), ("el", "[Ͱ-Ͽ]"), ("he", "[֐-׿]")]
ALERT = {"queja", "problema", "probleme", "problem", "reembolso", "devolucion", "accidente", "emergencia", "urgente",
         "denuncia", "complaint", "refund", "accident", "emergency", "urgent", "remboursement", "urgence",
         "reclamacao", "notfall", "beschwerde", "erstattung", "unfall", "reclamo", "rimborso", "incidente",
         "emergenza", "投诉", "退款", "事故", "紧急", "救命", "苦情", "返金", "緊急", "助けて", "불만", "환불", "사고",
         "긴급", "شكوى", "استرداد", "حادث", "طوارئ", "жалоб", "возврат", "авари", "срочно", "शिकायत", "रिफंड",
         "दुर्घटना", "आपात"}
GREET = {"es": "¡Hola! ", "en": "Hello! ", "fr": "Bonjour ! ", "pt": "Olá! ", "de": "Hallo! ", "it": "Ciao! ",
         "zh": "您好！", "ja": "こんにちは！", "ko": "안녕하세요! ", "ar": "مرحبًا! ", "ru": "Здравствуйте! ", "hi": "नमस्ते! "}
POS = {"excelente", "genial", "hermoso", "delicioso", "amable", "recomiendo", "great", "beautiful", "friendly", "delicious", "loved"}
NEG = {"caro", "sucio", "malo", "lejos", "tarde", "dirty", "expensive", "late", "bad", "far", "confuso"}
IGNORE = {"el", "la", "de", "que", "y", "un", "una", "muy", "con", "en", "the", "and", "was", "very", "a", "to", "is", "es", "fue"}


def load_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def vision_revisar(cat):
    """Devuelve el primer problema del catálogo de etiquetas en lenguaje claro, o None.
    El archivo está pensado para que lo edite quien conoce la zona, así que un olvido
    debe explicarse, no reventar con un error de programador."""
    if not isinstance(cat.get("grupos"), list) or not cat["grupos"]:
        return "falta la lista 'grupos'"
    if "{}" not in str(cat.get("plantilla", "")):
        return "'plantilla' debe contener {} donde va la etiqueta"
    for i, g in enumerate(cat["grupos"]):
        donde = f"grupo {g.get('id') or i + 1}"
        for clave in ("id", "nombre", "icon"):
            if not str(g.get(clave, "")).strip():
                return f"{donde}: falta '{clave}'"
        if not isinstance(g.get("labels"), list) or not g["labels"]:
            return f"{donde}: no tiene etiquetas"
        for j, lb in enumerate(g["labels"]):
            for clave in ("en", "es"):
                if not str((lb or {}).get(clave, "")).strip():
                    return f"{donde}, etiqueta {j + 1}: falta '{clave}'"
    return None


def vision_firma(cat):
    """Identifica el catálogo de etiquetas: cambia si se añade, quita o reescribe cualquiera.
    Sirve para avisar de que los vectores guardados ya no corresponden y hay que recalcularlos."""
    textos = [cat.get("plantilla", "")]
    for g in cat.get("grupos", []):
        textos += [g["id"]] + [lb["en"] for lb in g["labels"]]
    return hashlib.sha256("\n".join(textos).encode("utf-8")).hexdigest()[:16]


def norm(text):
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w ]|_", " ", t).split())


# ---------- Algoritmo de selección ----------
def score_place(p):
    """Calidad + confianza verificada + bonus a lugares poco visitados.
    El patrocinio NO sube la posición (transparencia)."""
    if p.get("rating") is None:  # sin calificar (p. ej. OpenStreetMap): solo cuenta qué tan completa es su ficha
        return round(0.3 * p.get("completeness", 0), 4)
    n = p.get("n_reviews", 0)
    r = p["rating"]
    if n:  # promedio bayesiano: con pocas reseñas pesa más el valor neutro (3.5)
        r = (3 * 3.5 + r * n) / (3 + n)
    quality = r / 5
    trust = (p["trust"] or 0) / 100
    novelty = 1 / (1 + math.log1p(p["visits"] or n))
    return round(0.40 * quality + 0.35 * trust + 0.25 * novelty, 4)


# Búsqueda: entiende plurales ("talleres" -> taller) y palabras parecidas ("tour" -> recorrido, visita…).
SYN = {"tour": ["recorrido", "visita", "caminata", "guiad", "excursion"], "recorrido": ["tour", "visita", "caminata"],
       "taller": ["taller", "artesan", "workshop"], "naturaleza": ["cascada", "cerro", "manantial", "mirador",
       "bosque", "picnic", "campamento"], "historia": ["historic", "monumento", "museo"], "comida": ["cafe", "restaurante",
       "comida", "cocina"], "arte": ["museo", "galeria", "taller"], "agua": ["cascada", "manantial", "rio", "lago"]}
SEARCH_STOP = {"de", "la", "el", "los", "las", "y", "en", "un", "una", "con", "para", "por", "del", "al"}


def _stem(w):
    for suf in ("es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[:-len(suf)]
    return w


def _found(tok, words):
    alts = {tok, _stem(tok), *SYN.get(_stem(tok), []), *SYN.get(tok, [])}
    return any(w.startswith(a) or _stem(w) == a for a in alts for w in words)


def rank_places(places, q=""):
    tokens = [t for t in norm(q).split() if t not in SEARCH_STOP]
    scored = []
    for p in places:
        words = norm(" ".join([p["name"], p["desc"], *p["tags"]])).split()
        hits = sum(_found(t, words) for t in tokens)
        scored.append((hits, {**p, "score": score_place(p)}))
    best = [p for h, p in scored if h == len(tokens)]  # todas las palabras
    if not best and tokens:  # si nada tiene todas, muestra lo que tenga alguna
        best = [p for h, p in sorted(scored, key=lambda x: -x[0]) if h]
    return sorted(best, key=lambda p: -p["score"])


def newest(places, n=3):
    return sorted([p for p in places if p.get("added")], key=lambda p: p["added"], reverse=True)[:n]


# ---------- Intención (lista cerrada de respuestas) ----------
def detect_lang(text):
    for lang, rx in SCRIPTS:
        if re.search(rx, text):
            return lang
    toks = set(norm(text).split())
    best = max(STOP, key=lambda k: len(toks & STOP[k]))
    return best if toks & STOP[best] else "es"


def _hit(k, t, toks):
    """'reserv*' = cualquier palabra que empiece así; sin '*' = palabra o frase completa (evita falsos positivos).
    Palabras en otras escrituras (chino, árabe, ruso…) se buscan dentro del texto: el chino no usa espacios."""
    star = k.endswith("*")
    k = norm(k.rstrip("*"))
    if not k.isascii():
        return k in t
    return any(w.startswith(k) for w in toks) if star else f" {k} " in f" {t} "


def classify(text, intents):
    """Devuelve (lista de intenciones, evidencia 0-1). Lista vacía = 'no estoy seguro, pregunta a una persona'."""
    t = norm(text)
    toks = t.split()
    scores = {n: sum(_hit(k, t, toks) for k in d["keywords"]) for n, d in intents.items()}
    top = max(scores.values())
    if top == 0:
        return [], 0.0
    names = sorted((n for n, sc in scores.items() if sc >= 1), key=lambda n: -scores[n])[:3]
    return names, round(top / (top + 1), 2)


def phrase_lookup(text, src, dst, phrases):
    """Frases guardadas (frasario): traducción exacta y sin internet. src puede ser 'auto'."""
    t = norm(text)
    if not t:
        return None
    for ph in phrases:
        for lang, txt in ph["t"].items():
            if (src in ("auto", lang)) and norm(txt) == t and dst in ph["t"]:
                return ph["t"][dst]
    return None


def is_sensitive(text):
    """Quejas, reembolsos, accidentes…: nunca se redacta respuesta automática."""
    t = norm(text)
    return any(_hit(k, t, t.split()) for k in ALERT)


class _Safe(dict):
    def __missing__(self, k):
        return f"[{k}?]"  # si falta un dato de la finca, se ve y la persona lo completa


def draft_reply(names, lang, intents, operator, greet=True):
    used = lang if all(lang in intents[n]["replies"] for n in names) else "es"
    body = " ".join(intents[n]["replies"][used].format_map(_Safe(operator)) for n in names)
    return (GREET[used] if greet and names != ["seguimiento"] else "") + body


# ---------- Red opcional con caché (funciona sin conexión) ----------
def _cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_CANDADO = threading.Lock()


def _save(key, value):
    # Con el desglose palabra por palabra se traduce en paralelo, así que varias hebras
    # pueden guardar a la vez: sin el candado se pierden entradas. Y se escribe aparte y
    # se sustituye de golpe, para que un corte no deje el caché a medias (es lo que hace
    # que la app siga traduciendo sin internet).
    with _CANDADO:
        c = _cache()
        c[key] = value
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, CACHE)


def _get(url, timeout=4):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


BAD_TR = ("INVALID", "MYMEMORY WARNING", "QUERY LENGTH LIMIT", "LANGPAIR", "PLEASE SELECT", "TESTVALUE")


def _bad(out):
    """MyMemory responde 200 aunque falle y pone el error en el texto: eso no es una traducción."""
    return not out or any(w in str(out).upper() for w in BAD_TR)


def translate(text, src, dst):
    """MyMemory (gratis, sin llave). Devuelve None si no hay conexión, si el servicio falla o sin caché."""
    if src == dst:
        return text
    if not (src.isalpha() and dst.isalpha()) or "auto" in (src, dst):
        return None  # MyMemory no detecta el idioma: hay que darle uno concreto
    key = f"tr|{src}|{dst}|{text}"
    hit = _cache().get(key)
    if hit and not _bad(hit):
        return hit
    try:
        q = urllib.parse.urlencode({"q": text, "langpair": f"{src}|{dst}"})
        r = _get("https://api.mymemory.translated.net/get?" + q)
        out = r["responseData"]["translatedText"]
        if int(r.get("responseStatus", 200)) != 200 or _bad(out):
            return None
        _save(key, out)
        return out
    except Exception:
        return None


# Alfabetos que la mayoría no sabe leer: se ofrece cómo suena, letra a letra.
ROMAN = {
    "ru": {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"ye","ё":"yo","ж":"zh","з":"z","и":"i","й":"y",
           "к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f",
           "х":"j","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"},
    "el": {"α":"a","β":"v","γ":"g","δ":"d","ε":"e","ζ":"z","η":"i","θ":"th","ι":"i","κ":"k","λ":"l",
           "μ":"m","ν":"n","ξ":"x","ο":"o","π":"p","ρ":"r","σ":"s","ς":"s","τ":"t","υ":"i","φ":"f",
           "χ":"j","ψ":"ps","ω":"o"},
    "ar": {"ا":"a","ب":"b","ت":"t","ث":"z","ج":"ll","ح":"j","خ":"j","د":"d","ذ":"d","ر":"r","ز":"z",
           "س":"s","ش":"sh","ص":"s","ض":"d","ط":"t","ظ":"z","ع":"a","غ":"g","ف":"f","ق":"q","ك":"k",
           "ل":"l","م":"m","ن":"n","ه":"h","و":"u","ي":"i","ء":"'","ة":"a","ى":"a"},
    "he": {"א":"a","ב":"b","ג":"g","ד":"d","ה":"h","ו":"v","ז":"z","ח":"j","ט":"t","י":"i","כ":"k",
           "ך":"k","ל":"l","מ":"m","ם":"m","נ":"n","ן":"n","ס":"s","ע":"a","פ":"f","ף":"f","צ":"ts",
           "ץ":"ts","ק":"k","ר":"r","ש":"sh","ת":"t"},
    "hi": {"अ":"a","आ":"aa","इ":"i","ई":"ii","उ":"u","ऊ":"uu","ए":"e","ऐ":"ai","ओ":"o","औ":"au",
           "क":"ka","ख":"kha","ग":"ga","घ":"gha","च":"cha","छ":"chha","ज":"ja","झ":"jha","ट":"ta",
           "ठ":"tha","ड":"da","ढ":"dha","ण":"na","त":"ta","थ":"tha","द":"da","ध":"dha","न":"na",
           "प":"pa","फ":"pha","ब":"ba","भ":"bha","म":"ma","य":"ya","र":"ra","ल":"la","व":"va",
           "श":"sha","ष":"sha","स":"sa","ह":"ha","ं":"n","ा":"a","ि":"i","ी":"i","ु":"u","ू":"u",
           "े":"e","ै":"ai","ो":"o","ौ":"au","्":""},
}


VOCALES_HI = "ािीुूृेैोौं"   # signos que ya traen su vocal: anulan la "a" de la consonante
VIRAMA = "्"                    # marca que la consonante va sin vocal


def romanizar(text, lang):
    """Cómo suena, aproximadamente, en letras que se leen en español.
    No sirve para chino, japonés ni coreano: ahí cada signo representa una palabra o
    una sílaba completa, no un sonido, y haría falta un diccionario entero."""
    tabla = ROMAN.get(lang)
    if not tabla:
        return None
    out = []
    for c in text:
        # El griego se escribe con acentos que la tabla no lista: se quitan antes de buscar.
        base = unicodedata.normalize("NFD", c)
        base = "".join(ch for ch in base if not unicodedata.combining(ch)) or c
        if lang == "hi" and (c in VOCALES_HI or c == VIRAMA) and out and out[-1].endswith("a"):
            out[-1] = out[-1][:-1]   # la consonante anterior pierde su "a" implícita
        pieza = tabla.get(c, tabla.get(base.lower(), tabla.get(c.lower())))
        out.append(pieza if pieza is not None else c)
    r = "".join(out)
    return r if r.strip() and r != text else None


PALABRA = re.compile(r"[^\W\d_]+", re.UNICODE)
# Artículos y preposiciones: sueltas no significan nada útil ("el" sale como "By") y
# ocupan sitio en el desglose. No se usa STOP porque esa lista existe para detectar la
# intención e incluye palabras con contenido ("cuesta", "grazie") que aquí sí interesan.
ATADAS = {
    "es": {"el", "la", "los", "las", "un", "una", "de", "del", "al", "a", "y", "o", "en", "que"},
    "en": {"the", "a", "an", "of", "to", "and", "or", "in", "on", "at", "is", "are"},
    "fr": {"le", "la", "les", "un", "une", "de", "du", "des", "et", "ou", "à", "en"},
    "pt": {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "e", "ou", "em"},
    "de": {"der", "die", "das", "ein", "eine", "und", "oder", "von", "zu", "in"},
    "it": {"il", "lo", "la", "i", "gli", "le", "un", "una", "di", "del", "e", "o", "in"},
}


def palabra_por_palabra(text, src, dst, frases, limite=8):
    """Qué significa cada palabra por separado. Ayuda a notar cuándo la traducción entera
    se fue por otro lado. Primero mira el frasario (gratis y sin internet); el resto va al
    traductor, en paralelo para que no se acumulen las esperas, y queda en caché."""
    vistas, pedir = set(), []
    for w in PALABRA.findall(text):
        bajo = w.lower()
        if bajo in vistas or len(w) < 2 or bajo in ATADAS.get(src, ()):
            continue
        vistas.add(bajo)
        pedir.append(w)
        if len(pedir) >= limite:
            break
    if not pedir:
        return []

    def una(w):
        return w, (phrase_lookup(w, src, dst, frases) or translate(w, src, dst))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(una, pedir))
    return [{"de": w, "a": t} for w, t in res if t and norm(t) != norm(w)]


def alternativas(text, src, dst, principal, limite=3):
    """Otras formas de decirlo que devuelve MyMemory. Solo se quedan las que vienen de
    una frase casi igual a la escrita: las demás son de otra oración y despistan más que ayudan."""
    if src == dst or not (src.isalpha() and dst.isalpha()) or "auto" in (src, dst):
        return []
    try:
        q = urllib.parse.urlencode({"q": text, "langpair": f"{src}|{dst}"})
        ms = _get("https://api.mymemory.translated.net/get?" + q).get("matches") or []
    except Exception:
        return []
    out, vistas = [], {norm(principal or "")}
    largo = len((principal or text).split())
    for m in sorted(ms, key=lambda x: -float(x.get("match") or 0)):
        t = (m.get("translation") or "").strip()
        if float(m.get("match") or 0) < 0.85 or _bad(t) or not t:
            continue
        # Fuera las que vienen de una oración entera que contiene la frase ("Q: How much is
        # the entrance fee in Ancient Kamiros?") y los trozos sueltos ("The bathroom?").
        if not (max(1, largo * 0.6) <= len(t.split()) <= max(3, largo * 1.4)):
            continue
        if norm(t) in vistas:
            continue
        # Y fuera las que solo cambian en un detalle ("good morning" / "good mornings"):
        # ocupan sitio sin decir nada nuevo.
        if any(difflib.SequenceMatcher(None, norm(t), v).ratio() > 0.9 for v in vistas):
            continue
        vistas.add(norm(t))
        out.append(t)
        if len(out) >= limite:
            break
    return out


def weather(lat, lon):
    """Open-Meteo (gratis, sin llave). Pronóstico de 3 días con caché."""
    key = f"wx|{lat}|{lon}"
    try:
        q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "forecast_days": 3, "timezone": "auto",
                                    "daily": "temperature_2m_max,precipitation_probability_max"})
        out = _get("https://api.open-meteo.com/v1/forecast?" + q)["daily"]
        _save(key, out)
        return {"data": out, "offline": False}
    except Exception:
        return {"data": _cache().get(key), "offline": True}


# ---------- Reseñas ----------
def analyze_reviews(reviews):
    words = {}
    pos = neg = 0
    for r in reviews:
        for w in norm(r).split():
            if w in POS:
                pos += 1
            if w in NEG:
                neg += 1
            if len(w) > 3 and w not in IGNORE:
                words[w] = words.get(w, 0) + 1
    top = sorted(words.items(), key=lambda x: -x[1])[:5]
    return {"n": len(reviews), "positivas": pos, "negativas": neg, "temas": [w for w, _ in top]}


LINK = re.compile(r"https?://|www\.|\.(com|net|org|mx)\b", re.I)


def check_review(author, text):
    """Validación básica anti-spam. Devuelve un mensaje de error o None."""
    if not 2 <= len(author.strip()) <= 30:
        return "El nombre o alias debe tener entre 2 y 30 caracteres."
    if not 10 <= len(text.strip()) <= 500:
        return "La reseña debe tener entre 10 y 500 caracteres."
    if LINK.search(author) or LINK.search(text):
        return "No se permiten enlaces."
    return None
