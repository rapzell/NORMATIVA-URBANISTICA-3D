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
