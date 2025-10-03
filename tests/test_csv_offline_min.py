import os
from fastapi.testclient import TestClient


def _setup_env(csv_path: str):
    os.environ['API_LOAD_RESOURCES'] = '0'
    os.environ['PLAN_PROVIDER'] = 'csv'
    os.environ['PLAN_CSV_PATH'] = csv_path
    os.environ['LOG_LEVEL'] = 'WARNING'


def test_vigo_u3_from_csv():
    _setup_env('datos/plan_uploaded.csv')
    # Import tardío para que coja las env vars
    from app.main import app
    client = TestClient(app)
    payload = {
        "municipio": "Vigo",
        "subzona": "U3",
        "zona": "urbano_consolidado",
        "uso_previsto": "residencial",
        "geometry": None,
    }
    r = client.post('/zoning/analyze', json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    # Valores esperados desde el CSV aplicado por la herramienta admin
    assert float(data.get('altura_maxima_m') or 0) == 10.5
    assert float(data.get('retranqueo_min_m') or 0) == 3.0
    assert float(data.get('ocupacion_max') or 0) == 0.6
    assert float(data.get('edificabilidad_max_m2_m2') or 0) == 1.0


def test_acoruna_nr1_from_csv():
    _setup_env('datos/plan_uploaded.csv')
    from app.main import app
    client = TestClient(app)
    payload = {
        "municipio": "A Coruna",
        "subzona": "NR-1",
        "zona": "urbano_consolidado",
        "uso_previsto": "residencial",
        "geometry": None,
    }
    r = client.post('/zoning/analyze', json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert float(data.get('altura_maxima_m') or 0) == 18.0
    assert float(data.get('retranqueo_min_m') or 0) == 3.0
    assert float(data.get('ocupacion_max') or 0) == 0.8
    assert float(data.get('edificabilidad_max_m2_m2') or 0) == 2.5
