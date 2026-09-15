from types import SimpleNamespace

from src.report_service import render_assess_report_html


def _result():
    return SimpleNamespace(
        viability="condicionado",
        reasons=["Prechequeo"],
        params_effective={},
        geometry_summary=None,
        feature=None,
    )


def _parcel_geometry():
    return {
        "type": "Polygon",
        "coordinates": [[[-8.7225, 42.2325], [-8.7220, 42.2325], [-8.7220, 42.2330], [-8.7225, 42.2330], [-8.7225, 42.2325]]],
    }


def test_report_includes_solar_exposure_section():
    body = {"municipio": "Vigo", "geometry": _parcel_geometry()}
    html = render_assess_report_html(body, _result())
    assert "Soleamiento por orientación" in html
    assert "solsticio_invierno" in html
    assert "Mejor orientación" in html


def test_report_includes_cost_estimate_section():
    body = {
        "municipio": "Vigo",
        "geometry": _parcel_geometry(),
        "costes": {
            "superficie_util_m2": 50,
            "coste_obra_m2": 800,
            "valor_venta_esperado": 120000,
            "fuente_costes": "Presupuesto AC8",
        },
    }
    html = render_assess_report_html(body, _result())
    assert "Estimación de costes de conversión" in html
    assert "Inversión total" in html
    assert "Presupuesto AC8" in html


def test_report_cost_section_shows_roi():
    body = {
        "municipio": "Vigo",
        "geometry": _parcel_geometry(),
        "costes": {
            "superficie_util_m2": 50,
            "coste_obra_m2": 800,
            "valor_venta_esperado": 120000,
        },
    }
    html = render_assess_report_html(body, _result())
    assert "ROI (venta)" in html
    assert "Beneficio bruto (venta)" in html


def test_report_without_cost_data_has_no_cost_section():
    body = {"municipio": "Vigo", "geometry": _parcel_geometry()}
    html = render_assess_report_html(body, _result())
    assert "Estimación de costes de conversión" not in html


def test_report_solar_section_has_limitations():
    body = {"municipio": "Vigo", "geometry": _parcel_geometry()}
    html = render_assess_report_html(body, _result())
    assert "edificios colindantes" in html.lower()


def test_report_includes_building_osm_data():
    body = {
        "municipio": "Vigo",
        "geometry": _parcel_geometry(),
        "edificio_osm": {
            "tipo": "retail",
            "altura_m": 4.5,
            "altura_fuente": "osm_tag_building_height",
            "plantas": "1",
            "huella_m2": 120.5,
            "osm_id": "123456789",
            "nombre": "Local comercial",
        },
    }
    html = render_assess_report_html(body, _result())
    assert "Datos del edificio (OpenStreetMap)" in html
    assert "retail" in html
    assert "4.5 m" in html
    assert "osm_tag_building_height" in html
    assert "123456789" in html
    assert "openstreetmap.org/way/123456789" in html


def test_report_without_building_osm_data_has_no_section():
    body = {"municipio": "Vigo", "geometry": _parcel_geometry()}
    html = render_assess_report_html(body, _result())
    assert "Datos del edificio (OpenStreetMap)" not in html
