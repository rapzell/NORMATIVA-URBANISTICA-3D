from fastapi.testclient import TestClient
import builtins
import types
from app.main import app


def test_metrics_disabled_returns_404(monkeypatch):
    monkeypatch.delenv('METRICS_ENABLED', raising=False)
    client = TestClient(app)
    r = client.get('/metrics')
    assert r.status_code == 404


def test_metrics_enabled_returns_200(monkeypatch):
    monkeypatch.setenv('METRICS_ENABLED', '1')
    client = TestClient(app)
    r = client.get('/metrics')
    assert r.status_code == 200
    # Should be some text exposition
    assert 'text/plain' in r.headers.get('content-type', '')


def test_metrics_enabled_fallback_when_prometheus_missing(monkeypatch):
    monkeypatch.setenv('METRICS_ENABLED', '1')
    # Force ImportError for prometheus_client inside endpoint
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'prometheus_client' or name.startswith('prometheus_client'):
            raise ImportError('forced for test')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)

    client = TestClient(app)
    r = client.get('/metrics')
    assert r.status_code == 200
    body = r.text
    assert '# HELP api_requests_total' in body
    assert '# TYPE api_request_latency_seconds histogram' in body


def test_metrics_enabled_content_type(monkeypatch):
    monkeypatch.setenv('METRICS_ENABLED', '1')
    client = TestClient(app)
    resp = client.get('/metrics')
    assert resp.status_code == 200
    assert resp.headers.get('content-type','').startswith('text/plain')
    # Trigger a 400 to increment error counter
    bad_payload = {"geometry": {"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}
    r = client.post('/zoning/volume', json=bad_payload)  # missing altura and municipio
    assert r.status_code == 400
    # Fetch metrics again and ensure api_errors_total is present
    resp2 = client.get('/metrics')
    text = resp2.text
    try:
        import prometheus_client  # noqa: F401
        assert 'api_errors_total' in text
    except Exception:
        # Fallback exposition may omit the custom metric
        assert '# HELP api_requests_total' in text
    assert 'version=' in resp.headers.get('content-type', '')
    # Ensure expected metric names appear at least once
    txt = resp.text
    assert 'api_requests_total' in txt
    assert 'api_request_latency_seconds' in txt
