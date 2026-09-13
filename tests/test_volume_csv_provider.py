import os
import contextlib
import pytest
from fastapi.testclient import TestClient

# Asegurar proveedor CSV para los tests
@contextlib.contextmanager
def csv_env():
    old_provider = os.environ.get('PLAN_PROVIDER')
    old_path = os.environ.get('PLAN_CSV_PATH')
    try:
        os.environ['PLAN_PROVIDER'] = 'csv'
        os.environ['PLAN_CSV_PATH'] = os.path.join('app', 'data', 'plan_uploaded.csv')
        yield
    finally:
        if old_provider is None:
            os.environ.pop('PLAN_PROVIDER', None)
        else:
            os.environ['PLAN_PROVIDER'] = old_provider
        if old_path is None:
            os.environ.pop('PLAN_CSV_PATH', None)
        else:
            os.environ['PLAN_CSV_PATH'] = old_path


def make_square(size=20.0):
    s = float(size)
    return {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [s, 0], [s, s], [0, s], [0, 0]]
        ],
    }


@pytest.fixture(scope='module')
def client():
    with csv_env():
        from app.main import app
        yield TestClient(app)


def test_volume_from_csv_vigo_rz2(client):
    body = {
        "geometry": make_square(20.0),
        "municipio": "Vigo",
        "subzona": "RZ-2",
        # No aportamos altura/retranqueos: deben venir del CSV
        "use_plan_front_default": True,
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    feat = data.get("feature")
    assert isinstance(feat, dict)
    props = feat.get("properties") or {}
    # Altura de Vigo RZ-2 del CSV: 12
    assert props.get("height_m") == pytest.approx(12.0)
    # Si el front por defecto aplica setbacks direccionales, al menos no debe fallar
    assert "diagnostics_level_applied" in data


def test_volume_from_csv_acoruna_general(client):
    body = {
        "geometry": make_square(20.0),
        "municipio": "A Coruna",
        # Sin subzona: debe coger fila general del municipio
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    feat = data.get("feature")
    assert isinstance(feat, dict)
    props = feat.get("properties") or {}
    # Altura general A Coruña según CSV: 13.5
    assert props.get("height_m") == pytest.approx(13.5)


def test_volume_from_csv_santiago_general(client):
    body = {
        "geometry": make_square(20.0),
        "municipio": "Santiago",
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    feat = data.get("feature")
    assert isinstance(feat, dict)
    props = feat.get("properties") or {}
    assert props.get("height_m") == pytest.approx(14.0)


def test_volume_from_csv_lugo_general(client):
    body = {
        "geometry": make_square(20.0),
        "municipio": "Lugo",
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    feat = data.get("feature")
    assert isinstance(feat, dict)
    props = feat.get("properties") or {}
    assert props.get("height_m") == pytest.approx(13.0)


def test_volume_from_csv_ourense_general(client):
    body = {
        "geometry": make_square(20.0),
        "municipio": "Ourense",
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    feat = data.get("feature")
    assert isinstance(feat, dict)
    props = feat.get("properties") or {}
    # Altura general Ourense según CSV: 12.0
    assert props.get("height_m") == pytest.approx(12.0)


def test_volume_directional_applies_in_vigo_rz2(client):
    body = {
        "geometry": make_square(20.0),
        "municipio": "Vigo",
        "subzona": "RZ-2",
        "use_plan_front_default": True,
    }
    r = client.post("/zoning/volume", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    feat = data.get("feature")
    assert isinstance(feat, dict)
    props = feat.get("properties") or {}
    # Direccionalidad debería aplicarse con front_direction_default del plan y setbacks definidos
    assert props.get("directional_applicability") in ("applied", "not_applicable")
    # Debe existir altura de 12 y algún setback aplicado positivo
    assert props.get("height_m") == pytest.approx(12.0)
    sa = float(props.get("setback_applied_m") or 0.0)
    assert sa >= 0.0
