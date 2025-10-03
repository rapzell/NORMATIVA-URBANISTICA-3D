import os
from fastapi.testclient import TestClient


def _setup_env(csv_path: str):
    os.environ['API_LOAD_RESOURCES'] = '0'
    os.environ['PLAN_PROVIDER'] = 'csv'
    os.environ['PLAN_CSV_PATH'] = csv_path
    os.environ['LOG_LEVEL'] = 'WARNING'


def test_fallback_to_municipio_default_when_subzona_missing():
    _setup_env('datos/plan_uploaded.csv')
    from app.main import app
    client = TestClient(app)
    payload = {
        "municipio": "Vigo",
        "subzona": "NO_EXISTE",
        "zona": "urbano_consolidado",
        "uso_previsto": "residencial",
        "geometry": None,
    }
    r = client.post('/zoning/analyze', json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    # Debe caer a la fila por defecto del municipio Vigo (subzona vacía): altura 7, retranqueo 3, ocupación 0.4, edificabilidad 0.7
    assert float(data.get('altura_maxima_m') or 0) == 7.0
    assert float(data.get('retranqueo_min_m') or 0) == 3.0
    assert float(data.get('ocupacion_max') or 0) == 0.4
    assert float(data.get('edificabilidad_max_m2_m2') or 0) == 0.7
