"""Lugares reales de tu zona desde OpenStreetMap (API Overpass, gratis y sin llave).
Se guardan en caché local para usarlos sin internet."""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import db, utils

URL = "https://overpass-api.de/api/interpreter"
UA = "TurismoRuralSmallAI/1.0 (hackathon)"
LABELS = {"attraction": "Atracción", "museum": "Museo", "viewpoint": "Mirador", "gallery": "Galería",
          "zoo": "Zoológico", "picnic_site": "Zona de picnic", "camp_site": "Campamento",
          "waterfall": "Cascada", "peak": "Cerro", "spring": "Manantial"}
KEYS = ("description", "opening_hours", "website", "phone", "wikipedia")


def area():
    """Zona activa: la elegida en la interfaz (guardada en SQLite) o, si no hay, la de .env."""
    try:
        a = json.loads(db.meta_get("area") or "")
        return float(a["lat"]), float(a["lon"]), int(a["radius"]), a["name"]
    except Exception:
        return (float(os.getenv("AREA_LAT", "19.2826")), float(os.getenv("AREA_LON", "-99.6557")),
                int(os.getenv("AREA_RADIUS_M", "15000")), os.getenv("AREA_NAME", "Toluca"))


def _path():
    return Path(os.getenv("OSM_CACHE", utils.DATA / "osm_places.json"))


def _query(lat, lon, r):
    a = f"(around:{r},{lat},{lon})"
    return ("[out:json][timeout:25];("
            f'nwr{a}["tourism"~"attraction|museum|viewpoint|gallery|zoo|picnic_site|camp_site"];'
            f'nwr{a}["historic"];'
            f'nwr{a}["natural"~"waterfall|peak|spring"];'
            ");out center tags 120;")


def _post(query):
    req = urllib.request.Request(URL, data=urllib.parse.urlencode({"data": query}).encode(),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode("utf-8"))


def parse(elements):
    out, seen = [], set()
    for e in elements:
        t = e.get("tags", {})
        name = t.get("name:es") or t.get("name")
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if not name or lat is None or name.lower() in seen:
            continue
        seen.add(name.lower())
        label = (LABELS.get(t.get("tourism")) or ("Sitio histórico" if "historic" in t else None)
                 or LABELS.get(t.get("natural")) or "Lugar de interés")
        desc = t.get("description:es") or t.get("description") or label
        if t.get("opening_hours"):
            desc += f" · Horario: {t['opening_hours']}"
        out.append({"id": f"{e['type'][0]}{e['id']}", "name": name, "desc": desc[:200], "tags": [label.lower()],
                    "rating": None, "trust": None, "visits": None, "added": "", "lat": lat, "lon": lon,
                    "sponsored": False, "source": "osm",
                    "completeness": sum(k in t for k in KEYS) / len(KEYS)})
    return out


def refresh(lat=None, lon=None, radius=None, name=None):
    """Descarga lugares. Si se pasa una zona nueva, solo se guarda como activa si la descarga funcionó."""
    new = lat is not None
    cur = area()
    lat, lon = (lat, lon) if new else cur[:2]
    radius, name = radius or cur[2], name or cur[3]
    places = parse(_post(_query(lat, lon, radius)).get("elements", []))
    _path().write_text(json.dumps({"updated": time.strftime("%Y-%m-%d %H:%M"), "places": places},
                                  ensure_ascii=False), encoding="utf-8")
    if new:
        db.meta_set("area", json.dumps({"lat": lat, "lon": lon, "radius": radius, "name": name}))
    db.meta_set("osm_last", str(time.time()))
    return len(places)


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def geocode(q):
    """Busca una localidad por nombre (Nominatim, gratis; máx. 1 consulta/seg, solo por acción del usuario)."""
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": 5, "accept-language": "es"})
    return [{"name": ", ".join(x.strip() for x in r["display_name"].split(",")[:3]), "lat": float(r["lat"]), "lon": float(r["lon"])}
            for r in _get_json(url)]


def reverse(lat, lon):
    """Nombre de la localidad para unas coordenadas (None si no hay red)."""
    try:
        url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {"lat": lat, "lon": lon, "format": "json", "zoom": 10, "accept-language": "es"})
        a = _get_json(url).get("address", {})
        town = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("county")
        return ", ".join(x for x in (town, a.get("state")) if x) or None
    except Exception:
        return None


def refresh_if_stale(max_age=86400, retry=600):
    """Máx. 1 descarga al día; si falla, reintenta a los 10 min (Overpass es un servicio compartido)."""
    now = time.time()
    last, tried = float(db.meta_get("osm_last") or 0), float(db.meta_get("osm_try") or 0)
    if now - last < max_age or now - tried < retry:
        return
    db.meta_set("osm_try", str(now))
    refresh()


def cached():
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {"updated": None, "places": []}


def catalog():
    """Lugares reales (OpenStreetMap). Los de ejemplo (data/places.json, inventados) solo con SHOW_SAMPLE=1."""
    sample = utils.load_json("places.json") if os.getenv("SHOW_SAMPLE", "0") == "1" else []
    return sample + cached()["places"]
