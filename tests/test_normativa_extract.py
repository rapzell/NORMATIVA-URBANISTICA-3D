import json
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post_extract(text: str, municipio: str | None = None):
    payload = {"text": text}
    if municipio:
        payload["municipio"] = municipio
    r = client.post("/normativa/extract", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_extract_basic_fields():
    data = post_extract(
        "Uso residencial. Altura máxima 12 m. Retranqueo mínimo 3 m. Art. 5.2",
        municipio="Vigo",
    )
    assert data["municipio"] == "Vigo"
    assert data["uso_suelo"] == "residencial"
    assert data["altura_maxima_m"] == 12.0
    assert data["retranqueo_min_m"] == 3.0
    assert any("Art." in r for r in data.get("referencias", []))


def test_extract_setbacks_by_side():
    data = post_extract(
        "Retranqueo al frente 4 m, laterales 3 m, posterior 5 m."
    )
    assert data["setback_front_m"] == 4.0
    assert data["setback_side_m"] == 3.0
    assert data["setback_back_m"] == 5.0


def test_extract_ocupacion_and_edificabilidad():
    data = post_extract(
        "Ocupación máxima 35%. Edificabilidad 1.2 m2/m2."
    )
    assert data["ocupacion_max"] == 0.35
    assert data["edificabilidad_max_m2_m2"] == 1.2


def test_extract_subzona_codes():
    data = post_extract("Zona U6.1 en casco urbano. Alternativa NR-1.")
    assert data["subzona"] in {"U6.1", "NR-1"}
