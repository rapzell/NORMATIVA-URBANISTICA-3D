import os
import io
import tempfile
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

CSV_SAMPLE = """municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2
Vigo,,12,3,,,,,,
"""

def setup_module(module):
    # Crear CSV temporal y configurar provider
    fd, path = tempfile.mkstemp(prefix="plan_", suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(CSV_SAMPLE)
    os.environ["PLAN_PROVIDER"] = "csv"
    os.environ["PLAN_CSV_PATH"] = path
    module._csv_path = path

def teardown_module(module):
    try:
        os.remove(module._csv_path)
    except Exception:
        pass
    for k in ("PLAN_PROVIDER","PLAN_CSV_PATH"):
        try:
            del os.environ[k]
        except Exception:
            pass

def test_plan_summary_ok():
    r = client.get("/admin/plan-summary")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["provider"] == "csv"
    assert j["rows"] >= 1
    assert isinstance(j.get("items"), list)
    assert j["items"][0]["municipio"] == "Vigo"


def test_plan_download_ok():
    r = client.get("/admin/plan-download")
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers.get("content-type","")
    # Contenido mínimo esperado
    assert b"municipio,subzona,altura_maxima_m" in r.content
