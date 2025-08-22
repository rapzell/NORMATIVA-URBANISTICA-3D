from fastapi.testclient import TestClient
from app.main import app

def test_validate_plan_csv_path_cache_hit(tmp_path):
    p = tmp_path / 'planes.csv'
    p.write_text('municipio,subzona,altura_maxima_m\nFoo,,10\n', encoding='utf-8')
    client = TestClient(app)

    # First call: should not be cache hit
    r1 = client.post('/zoning/validate-plan-csv', json={'path': str(p)})
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1['valid'] is True
    assert data1.get('cache_hit') is False

    # Second call: same file/signature -> cache hit expected
    r2 = client.post('/zoning/validate-plan-csv', json={'path': str(p)})
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2['valid'] is True
    assert data2.get('cache_hit') is True

    # Modify file to invalidate cache
    p.write_text('municipio,subzona,altura_maxima_m\nFoo,,12\n', encoding='utf-8')

    r3 = client.post('/zoning/validate-plan-csv', json={'path': str(p)})
    assert r3.status_code == 200
    data3 = r3.json()
    assert data3['valid'] is True
    assert data3.get('cache_hit') is False
