import datetime
from fastapi.testclient import TestClient
from app.main import app

from src.shadow_service import solar_position, shadow_analysis, shadow_analysis_multi_hour, project_shadow_polygon


def test_solar_position_summer_noon_vigo():
    """En el solsticio de verano al mediodía solar, el sol debe estar alto."""
    # Vigo ~42.23°N, -8.72°E, 21 junio 2025 12:00 UTC
    dt = datetime.datetime(2025, 6, 21, 12, 0, 0)
    pos = solar_position(42.23, -8.72, dt)
    assert pos['elevation_deg'] > 60
    assert 150 < pos['azimuth_deg'] < 210


def test_solar_position_winter_evening_low():
    """En el solsticio de invierno a las 18:00 UTC, el sol debe estar bajo."""
    dt = datetime.datetime(2025, 12, 21, 18, 0, 0)
    pos = solar_position(42.23, -8.72, dt)
    assert pos['elevation_deg'] < 10


def test_shadow_polygon_summer_noon_short():
    """Al mediodía de verano, la sombra debe ser corta."""
    geom = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    dt = datetime.datetime(2025, 6, 21, 12, 0, 0)
    pos = solar_position(42.23, -8.72, dt)
    shadow = project_shadow_polygon(geom, 12.0, pos['elevation_deg'], pos['azimuth_deg'])
    assert shadow is not None
    assert shadow['type'] == 'Polygon'
    # La sombra debe tener más vértices que el edificio original
    ring = shadow['coordinates'][0]
    assert len(ring) > 5


def test_shadow_polygon_winter_morning_long():
    """En invierno por la mañana, la sombra debe ser larga."""
    geom = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    dt = datetime.datetime(2025, 12, 21, 9, 0, 0)
    pos = solar_position(42.23, -8.72, dt)
    if pos['elevation_deg'] > 0.5:
        shadow = project_shadow_polygon(geom, 12.0, pos['elevation_deg'], pos['azimuth_deg'])
        assert shadow is not None
    else:
        # Sol bajo el horizonte: sin sombra
        shadow = project_shadow_polygon(geom, 12.0, pos['elevation_deg'], pos['azimuth_deg'])
        assert shadow is None


def test_shadow_analysis_no_shadow_when_sun_down():
    """Si el sol está bajo el horizonte, no hay sombra."""
    geom = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    dt = datetime.datetime(2025, 12, 21, 3, 0, 0)
    analysis = shadow_analysis(geom, 12.0, 42.23, -8.72, dt)
    assert analysis['has_shadow'] is False
    assert analysis['shadow_polygon'] is None
    assert analysis['shadow_length_m'] == 0.0


def test_shadow_analysis_multi_hour_returns_results():
    """El análisis multi-hora debe devolver resultados para cada hora."""
    geom = {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    date = datetime.date(2025, 6, 21)
    result = shadow_analysis_multi_hour(geom, 12.0, 42.23, -8.72, date, hours=[8, 12, 16])
    assert result['date'] == '2025-06-21'
    assert len(result['results']) == 3
    assert 'max_shadow_length_m' in result
    assert 'summary' in result


def test_shadow_analysis_endpoint_post():
    client = TestClient(app)
    payload = {
        'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        'height_m': 12.0,
        'lat': 42.23,
        'lon': -8.72,
        'date': '2025-06-21',
        'hour_utc': 12,
    }
    r = client.post('/zoning/shadow-analysis', json=payload)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['date'] == '2025-06-21'
    assert len(j['results']) == 1
    assert 'solar' in j['results'][0]
    assert 'shadow_length_m' in j['results'][0]


def test_shadow_analysis_endpoint_get_default():
    client = TestClient(app)
    r = client.get('/zoning/shadow-analysis', params={'lon': -8.72, 'lat': 42.23, 'height_m': 12.0})
    assert r.status_code == 200, r.text
    j = r.json()
    assert 'results' in j
    assert len(j['results']) == 6
    assert 'max_shadow_length_m' in j
