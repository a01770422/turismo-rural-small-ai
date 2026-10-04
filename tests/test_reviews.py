import os
import tempfile

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")

from src import db, utils  # noqa: E402


def test_validacion():
    assert utils.check_review("Ana", "Muy bonito lugar, lo recomiendo") is None
    assert utils.check_review("A", "Muy bonito lugar, lo recomiendo")
    assert utils.check_review("Ana", "corto")
    assert utils.check_review("Ana", "Visita www.spam.com para ofertas")


def test_stats_y_ocultar():
    a = db.add_review("t-1", "Ana", 5, "Excelente recorrido por el cafetal")
    db.add_review("t-1", "Luis", 3, "Estuvo bien pero llegamos tarde")
    avg, n = db.review_stats()["t-1"]
    assert n == 2 and avg == 4
    assert db.has_review("t-1", "Ana", "Excelente recorrido por el cafetal")
    db.hide_review(a)
    assert db.review_stats()["t-1"][1] == 1 and len(db.list_reviews("t-1")) == 1


def test_una_sola_reseña_5_estrellas_no_supera_a_lo_verificado():
    verificado = utils.load_json("places.json")[0]
    una = {**verificado, "trust": None, "rating": 5.0, "n_reviews": 1, "visits": None}
    assert utils.score_place(una) < utils.score_place(verificado)
