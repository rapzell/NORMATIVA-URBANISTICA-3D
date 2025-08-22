from fastapi.testclient import TestClient
from app.main import app


def test_validate_csv_text_valid_minimal():
    client = TestClient(app)
    csv_text = "municipio,subzona,altura_maxima_m\nFoo,,10\n"
    r = client.post('/zoning/validate-plan-csv', json={"csv_text": csv_text})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert data["errors"] == []


def test_validate_csv_text_missing_required_header():
    client = TestClient(app)
    csv_text = "subzona,altura_maxima_m\n,10\n"  # falta municipio
    r = client.post('/zoning/validate-plan-csv', json={"csv_text": csv_text})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is False
    assert any("faltan columnas requeridas" in e.get("message", "") for e in data["errors"])  # error listado


def test_validate_csv_text_unknown_column_warning():
    client = TestClient(app)
    csv_text = "municipio,subzona,altura_maxima_m,extra_col\nBar,,11,x\n"
    r = client.post('/zoning/validate-plan-csv', json={"csv_text": csv_text})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is True
    assert any("Columnas desconocidas" in w and "extra_col" in w for w in data["warnings"])


def test_validate_csv_path_invalid_values(tmp_path):
    # altura_maxima_m <= 0 provoca error
    p = tmp_path / 'planes.csv'
    p.write_text("municipio,subzona,altura_maxima_m\nBaz,,0\n", encoding='utf-8')
    client = TestClient(app)
    r = client.post('/zoning/validate-plan-csv', json={"path": str(p)})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is False
    assert any("altura_maxima_m" in e.get("message", "") for e in data["errors"])  # mensaje de altura inválida


def test_validate_csv_path_not_found():
    client = TestClient(app)
    r = client.post('/zoning/validate-plan-csv', json={"path": "no_existe.csv"})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is False
    assert any("CSV no encontrado" in e.get("message", "") for e in data["errors"])


def test_validate_csv_text_duplicate_rows_flagged():
    client = TestClient(app)
    csv_text = (
        "municipio,subzona,altura_maxima_m\n"
        "Foo,,10\n"
        "Foo,,12\n"
    )
    r = client.post('/zoning/validate-plan-csv', json={"csv_text": csv_text})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is False
    assert any("Fila duplicada" in e.get("message", "") for e in data["errors"])


def test_validate_csv_path_duplicate_rows_flagged(tmp_path):
    p = tmp_path / 'planes.csv'
    p.write_text(
        "municipio,subzona,altura_maxima_m\nFoo,,10\nFoo,,12\n",
        encoding='utf-8'
    )
    client = TestClient(app)
    r = client.post('/zoning/validate-plan-csv', json={"path": str(p)})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] is False
    assert any("Fila duplicada" in e.get("message", "") for e in data["errors"])
