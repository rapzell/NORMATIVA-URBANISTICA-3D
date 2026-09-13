import base64
import json
from fastapi.testclient import TestClient

# Import the FastAPI app
from app.main import app

client = TestClient(app)


def _b64url(data: dict) -> str:
    s = json.dumps(data, separators=(",", ":"))
    raw = base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")
    return raw.rstrip("=")


def test_zoning_analyze_smoke():
    # Minimal ZoneInput; geometry is optional in /zoning/analyze
    payload = {
        "zona": "urbano_consolidado",
        "uso_previsto": "residencial",
        "municipio": "Vigo",
        "subzona": None,
        "geometry": None,
        "crs": None,
    }
    r = client.post("/zoning/analyze", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, dict)
    # The response may vary depending on provider, just ensure basic keys exist
    assert "zona_normalizada" in data or "apto_residencial" in data


def test_assess_report_includes_branding_notes_source():
    # Build a minimal volume/assess body
    body = {
        "geometry": None,
        "municipio": "Vigo",
        "subzona": None,
        "use_plan_front_default": True,
    }
    b64 = _b64url(body)
    params = {
        "body_b64": b64,
        "title": "Informe de prueba",
        "client": "AC8",
        "project": "Proyecto Demo",
        "brand_color": "#0044aa",
        "signature": "true",
        "sign_by": "DVR",
        "sign_place": "Vigo, 2025-09-19",
        "notes": "Observaciones de prueba",
        "source_ref": "https://example.com/norma",
    }
    r = client.get("/zoning/assess-report", params=params)
    assert r.status_code == 200, r.text
    html = r.text
    # Check key rendered sections
    assert "Observaciones" in html
    assert "Observaciones de prueba" in html
    assert "Fuente normativa" in html
    assert "https://example.com/norma" in html or "example.com/norma" in html
    assert "DVR" in html  # signature block


def test_assess_report_includes_cartographic_composition():
    """El informe con geometria debe incluir la composicion cartografica SVG."""
    body = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-8.725, 42.23], [-8.715, 42.23],
                [-8.715, 42.24], [-8.725, 42.24],
                [-8.725, 42.23]
            ]]
        },
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 3.0,
        "setback_front_m": 3.0,
        "setback_side_m": 3.0,
        "setback_back_m": 3.0,
        "front_direction": "north",
        "crs": "EPSG:4326",
    }
    b64 = _b64url(body)
    r = client.get("/zoning/assess-report", params={"body_b64": b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert "Composición cartográfica" in html or "cartográfica" in html
    assert "<svg" in html
    assert "Parcela" in html


def test_assess_report_without_geometry_omits_cartographic():
    """El informe sin geometria no debe incluir la composicion cartografica."""
    body = {
        "geometry": None,
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 3.0,
    }
    b64 = _b64url(body)
    r = client.get("/zoning/assess-report", params={"body_b64": b64})
    assert r.status_code == 200, r.text
    html = r.text
    # Sin geometria, no hay seccion cartografica
    assert "Composición cartográfica" not in html
