import os
from fastapi.testclient import TestClient


def _setup_env(csv_path: str):
    os.environ['API_LOAD_RESOURCES'] = '0'
    os.environ['PLAN_PROVIDER'] = 'csv'
    os.environ['PLAN_CSV_PATH'] = csv_path
    os.environ['LOG_LEVEL'] = 'WARNING'


def test_boiro_ordenanza_1_from_csv():
    _setup_env('datos/planes_municipales_sample.csv')
    from app.main import app
    client = TestClient(app)
    payload = {
        "municipio": "Boiro",
        "subzona": "Ordenanza 1",
        "zona": "urbano_consolidado",
        "uso_previsto": "residencial",
        "geometry": None,
    }
    r = client.post('/zoning/analyze', json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert float(data.get('altura_maxima_m') or 0) == 10.0
    assert float(data.get('retranqueo_min_m') or 0) == 3.0
    assert float(data.get('ocupacion_max') or 0) == 0.8
    assert float(data.get('edificabilidad_max_m2_m2') or 0) == 2.0


def test_boiro_ordenanza_3_from_csv():
    _setup_env('datos/planes_municipales_sample.csv')
    from app.main import app
    client = TestClient(app)
    payload = {
        "municipio": "Boiro",
        "subzona": "Ordenanza 3",
        "zona": "urbano_consolidado",
        "uso_previsto": "residencial",
        "geometry": None,
    }
    r = client.post('/zoning/analyze', json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert float(data.get('altura_maxima_m') or 0) == 7.0
    assert float(data.get('retranqueo_min_m') or 0) == 3.0
    assert float(data.get('ocupacion_max') or 0) == 0.5
    assert float(data.get('edificabilidad_max_m2_m2') or 0) == 0.8
