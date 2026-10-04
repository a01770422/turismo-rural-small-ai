from src import utils

PLACES = utils.load_json("places.json")
INTENTS = utils.load_json("intents.json")


def test_poco_visitado_confiable_gana_a_popular_patrocinado():
    ranked = utils.rank_places(PLACES)
    assert ranked[0]["id"] != 4
    assert ranked[-1]["id"] == 4


def test_busqueda():
    assert [p["id"] for p in utils.rank_places(PLACES, "cascada")] == [2]


def test_intencion_clara():
    assert utils.classify("How much does the tour cost?", INTENTS)[0] == ["precio"]
    assert utils.classify("Quanto tempo dura o passeio?", INTENTS)[0] == ["duracion"]


def test_varias_preguntas_en_un_mensaje():
    assert set(utils.classify("Cuánto cuesta y a qué hora abren?", INTENTS)[0]) == {"precio", "horario"}
    assert set(utils.classify("precio y donde", INTENTS)[0]) == {"precio", "direcciones"}


def test_failsafe_y_sin_falsos_positivos():
    assert utils.classify("asdf qwerty", INTENTS)[0] == []
    assert utils.classify("ahora mismo estamos cerca", INTENTS)[0] == []


def test_mensaje_delicado():
    assert utils.is_sensitive("I want a refund, there was an accident")
    assert not utils.is_sensitive("How much does it cost?")


def test_borrador_en_idioma_del_visitante():
    op = utils.load_json("operator.json")
    d = utils.draft_reply(["precio", "horario"], "fr", INTENTS, op)
    assert d.startswith("Bonjour") and "350" in d and "ouverts" in d
    assert utils.draft_reply(["precio"], "zz", INTENTS, op).startswith("¡Hola!")  # sin plantilla: cae a español
    assert "[price?]" in utils.draft_reply(["precio"], "es", INTENTS, {})


def test_idiomas_con_otra_escritura_sin_internet():
    casos = {"多少钱？在哪里集合？": ("zh", {"precio", "direcciones"}), "予約できますか？": ("ja", {"reserva"}),
             "몇 시에 열어요?": ("ko", {"horario"}), "كم سعر الجولة؟": ("ar", {"precio"}),
             "Сколько стоит экскурсия?": ("ru", {"precio"}), "टूर की कीमत क्या है?": ("hi", {"precio"}),
             "Vorrei prenotare per sabato": ("it", {"reserva"})}
    for texto, (lang, ints) in casos.items():
        assert utils.detect_lang(texto) == lang
        assert set(utils.classify(texto, INTENTS)[0]) == ints
    assert utils.classify("얼마나 걸려요?", INTENTS)[0] == ["duracion"]  # "얼마나" no es "얼마" (precio)
    assert utils.is_sensitive("我要退款") and not utils.is_sensitive("Сколько стоит?")


def test_todas_las_plantillas_tienen_los_mismos_idiomas():
    langs = set(INTENTS["precio"]["replies"])
    assert {"zh", "ar", "ru", "hi", "ja", "ko", "it"} <= langs
    assert all(set(d["replies"]) == langs for d in INTENTS.values())
    op = utils.load_json("operator.json")
    assert utils.draft_reply(["precio"], "zh", INTENTS, op).startswith("您好")


def test_busqueda_entiende_plurales_y_parecidas():
    lugares = [{"name": "Taller de cerámica", "desc": "Hecho a mano", "tags": []},
               {"name": "Finca", "desc": "Recorrido guiado por el cafetal", "tags": []},
               {"name": "Museo de Arte", "desc": "Museo", "tags": []}]
    lugares = [{**p, "id": i, "rating": None, "trust": None, "visits": None} for i, p in enumerate(lugares)]
    assert [p["id"] for p in utils.rank_places(lugares, "talleres")] == [0]
    assert [p["id"] for p in utils.rank_places(lugares, "tours")] == [1]
    assert [p["id"] for p in utils.rank_places(lugares, "museos de la ciudad")] == [2]  # alguna palabra basta
    assert utils.rank_places(lugares, "xyz") == []


def test_frasario_traduce_sin_internet():
    pb = utils.load_json("phrases.json")
    langs = set(pb["ui"])
    assert all(set(p["t"]) == langs for p in pb["phrases"])  # cada frase en todos los idiomas
    assert utils.phrase_lookup("¿Dónde está el baño?", "es", "ja", pb["phrases"]) == "トイレはどこですか？"
    assert utils.phrase_lookup("洗手间在哪里", "auto", "es", pb["phrases"]) == "¿Dónde está el baño?"
    assert utils.phrase_lookup("una frase que no existe", "es", "en", pb["phrases"]) is None


def test_errores_de_mymemory_no_son_traducciones(monkeypatch, tmp_path):
    monkeypatch.setattr(utils, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(utils, "_get", lambda url: {"responseStatus": 403, "responseData": {
        "translatedText": "'AUTO' IS AN INVALID SOURCE LANGUAGE . EXAMPLE: LANGPAIR=EN|IT"}})
    assert utils.translate("hola", "es", "en") is None
    assert utils.translate("hola", "auto", "en") is None
    monkeypatch.setattr(utils, "_get", lambda url: {"responseStatus": 200, "responseData": {"translatedText": "hello"}})
    assert utils.translate("hola", "es", "en") == "hello"
