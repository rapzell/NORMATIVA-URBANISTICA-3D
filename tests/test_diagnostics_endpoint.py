from fastapi.testclient import TestClient
import os
from app.main import app

def test_diagnostics_log_config_disabled():
    client = TestClient(app)
    # Ensure disabled
    if 'DIAGNOSTICS_ENABLED' in os.environ:
        del os.environ['DIAGNOSTICS_ENABLED']
    r = client.get('/diagnostics/log-config')
    assert r.status_code == 404


def test_diagnostics_log_config_enabled(monkeypatch):
    monkeypatch.setenv('DIAGNOSTICS_ENABLED', '1')
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    client = TestClient(app)
    r = client.get('/diagnostics/log-config')
    assert r.status_code == 200
    data = r.json()
    assert 'root' in data and 'loggers' in data
    assert 'handlers' in data['root']
    assert 'volume' in data['loggers']
