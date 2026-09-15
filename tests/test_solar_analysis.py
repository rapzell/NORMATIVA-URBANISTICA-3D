from fastapi.testclient import TestClient

from app.main import app
from src.solar_analysis import analyze_solar_exposure, render_solar_exposure_html

client = TestClient(app)

VIGO_LAT = 42.2325
VIGO_LON = -8.7225


def test_solar_exposure_returns_all_orientations():
    result = analyze_solar_exposure(VIGO_LAT, VIGO_LON)
    for date_name in ["equinoccio_primavera", "solsticio_verano", "equinoccio_otonio", "solsticio_invierno"]:
        assert date_name in result["dates"]
        hours = result["dates"][date_name]["hours_sun_by_orientation"]
        for orient in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]:
            assert orient in hours
            assert hours[orient] >= 0


def test_south_gets_more_sun_than_north_in_winter():
    result = analyze_solar_exposure(VIGO_LAT, VIGO_LON)
    winter = result["dates"]["solsticio_invierno"]["hours_sun_by_orientation"]
    assert winter["S"] > winter["N"]


def test_east_gets_morning_sun():
    result = analyze_solar_exposure(VIGO_LAT, VIGO_LON)
    summer = result["dates"]["solsticio_verano"]["hours_sun_by_orientation"]
    assert summer["E"] > 0
    assert summer["W"] > 0


def test_best_and_worst_orientation_identified():
    result = analyze_solar_exposure(VIGO_LAT, VIGO_LON)
    assert result["best_orientation"] in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    assert result["worst_orientation"] in ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def test_limitations_are_explicit():
    result = analyze_solar_exposure(VIGO_LAT, VIGO_LON)
    assert len(result["limitations"]) >= 3
    assert any("edificios colindantes" in l.lower() for l in result["limitations"])


def test_render_html_contains_summary_and_table():
    result = analyze_solar_exposure(VIGO_LAT, VIGO_LON)
    html = render_solar_exposure_html(result)
    assert "Resumen" in html
    assert "<table" in html
    assert "solsticio_invierno" in html


def test_api_returns_solar_exposure():
    response = client.get(f"/solar/exposicion?lat={VIGO_LAT}&lon={VIGO_LON}")
    assert response.status_code == 200
    data = response.json()
    assert "dates" in data
    assert "best_orientation" in data
    assert "limitations" in data
    assert data["dates"]["solsticio_invierno"]["hours_sun_by_orientation"]["S"] >= 0
