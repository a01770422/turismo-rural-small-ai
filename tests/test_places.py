import os
import tempfile

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["OSM_CACHE"] = os.path.join(tempfile.mkdtemp(), "osm.json")

from src import places_osm, utils  # noqa: E402

EL = [
    {"type": "node", "id": 1, "lat": 19.3, "lon": -99.6, "tags": {"name": "Cascada X", "natural": "waterfall", "description": "Bonita"}},
    {"type": "way", "id": 2, "center": {"lat": 19.2, "lon": -99.7}, "tags": {"name": "Museo Y", "tourism": "museum", "opening_hours": "Mo-Su 10:00-17:00", "website": "x"}},
    {"type": "node", "id": 3, "lat": 1, "lon": 1, "tags": {"tourism": "viewpoint"}},  # sin nombre: se descarta
]


def test_parse_osm():
    ps = places_osm.parse(EL)
    assert [p["id"] for p in ps] == ["n1", "w2"]
    assert ps[0]["tags"] == ["cascada"] and "Horario" in ps[1]["desc"]
    assert all(p["rating"] is None and p["trust"] is None for p in ps)


def test_sin_calificar_no_supera_a_verificado():
    osm = places_osm.parse(EL)[1]
    ejemplo = utils.load_json("places.json")[0]
    assert utils.score_place(osm) < utils.score_place(ejemplo)


def test_catalogo_ejemplo_y_osm():
    os.environ["SHOW_SAMPLE"] = "0"
    assert places_osm.catalog() == places_osm.cached()["places"]
    os.environ["SHOW_SAMPLE"] = "1"
    assert len(places_osm.catalog()) == 4 + len(places_osm.cached()["places"])


def test_zona_elegida_solo_se_guarda_si_la_descarga_funciona():
    places_osm._post = lambda q: {"elements": EL}
    assert places_osm.refresh(19.0, -99.0, 5000, "Villa X") == 2
    assert places_osm.area() == (19.0, -99.0, 5000, "Villa X")

    def sin_red(q):
        raise OSError("sin red")
    places_osm._post = sin_red
    try:
        places_osm.refresh(10.0, 10.0, 5000, "Otra")
    except OSError:
        pass
    assert places_osm.area()[3] == "Villa X"


def test_geocode():
    places_osm._get_json = lambda url: [{"display_name": "A, B, C, D", "lat": "1.5", "lon": "-2.5"}]
    assert places_osm.geocode("x") == [{"name": "A, B, C", "lat": 1.5, "lon": -2.5}]
