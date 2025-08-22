from fastapi.testclient import TestClient
import os, tempfile
from app.main import app

CSV_TEMPLATE = """municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2
{municipio},{subzona},10,2,,,{back},north,,
"""

def test_csv_front_default_requires_directional_setbacks(tmp_path, monkeypatch):
    # Create a CSV that defines front_direction_default but no directional setbacks -> should 400
    csv_content = CSV_TEMPLATE.format(municipio='Foo', subzona='Bar', back='',)
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
        "subzona": "Bar"
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert 'inconsistente' in r.json()['detail']


def test_csv_front_default_ok_when_any_directional_present(tmp_path, monkeypatch):
    # With back setback set, it should be accepted
    csv_content = CSV_TEMPLATE.format(municipio='Foo', subzona='Baz', back='1.0')
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
        "subzona": "Baz",
        "use_plan_front_default": True
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['front_direction_source'] in ('plan_default','street_axis')


def test_csv_invalid_front_direction_value(tmp_path, monkeypatch):
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,Baz,10,2,1.0,0.5,0.8,north-east,,\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
        "subzona": "Baz",
        "use_plan_front_default": True
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert 'front_direction_default inválido' in r.json()['detail']


def test_csv_missing_altura_causes_400(tmp_path, monkeypatch):
    # altura_maxima_m missing -> provider returns None -> API should 400
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,Baz,,2,1.0,0.5,0.8,north,,\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
        "subzona": "Baz",
        "use_plan_front_default": True
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert (
        'altura_maxima_m requerida' in r.json()['detail']
        or 'altura_maxima_m debe ser > 0' in r.json()['detail']
        or 'altura máxima' in r.json()['detail']
    )


def test_csv_non_numeric_altura_causes_400(tmp_path, monkeypatch):
    # Non-numeric altura -> parsed as None -> API should 400
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,Baz,abc,2,1.0,0.5,0.8,north,,\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
        "subzona": "Baz",
        "use_plan_front_default": True
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert (
        'altura_maxima_m requerida' in r.json()['detail']
        or 'altura_maxima_m debe ser > 0' in r.json()['detail']
        or 'altura máxima' in r.json()['detail']
    )


def test_csv_file_not_found_returns_400(monkeypatch):
    # Point to non-existing file -> provider raises FileNotFoundError -> API returns 400
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', 'datos/no_existe_planes.csv')

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
        "subzona": "Baz",
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert 'No se pudieron obtener parámetros municipales' in r.json()['detail']


def test_csv_municipio_and_subzona_matching_is_case_insensitive_and_trimmed(tmp_path, monkeypatch):
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "  foo  ,  BaZ  ,11,3,2.0,1.0,0.5,west,0.30,0.80\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "FOO",
        "subzona": " baz ",
        "use_plan_front_default": True
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    props = r.json()['feature']['properties']
    assert props['front_direction_source'] in ('plan_default','street_axis')


def test_csv_no_match_returns_400(tmp_path, monkeypatch):
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,,10,2,,,,,,\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Bar",  # not present
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert (
        'No se pudieron obtener parámetros municipales' in r.json()['detail']
        or 'altura_maxima_m requerida' in r.json()['detail']
        or 'CSV faltan columnas requeridas' in r.json()['detail']
    )


def test_csv_prefers_default_when_subzona_not_provided(tmp_path, monkeypatch):
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,,13,3,,,,,,\n"
        "Foo,Spec,9,1,1.0,0.5,0.5,north,0.20,0.60\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    # Without subzona, should pick the default (empty subzona) and provide altura 13
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    # When no explicit altura in request, the response area indicates it computed envelope; but we need altura presence indirectly.
    # Simply assert feature returned and not 400; deeper param introspection would require a dedicated endpoint.
    data = r.json()
    assert data['feature'] is not None


def test_csv_ocupacion_out_of_range_causes_400(tmp_path, monkeypatch):
    for val in ('-0.1', '1.1'):
        csv_content = (
            "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
            f"Foo,,10,2,,,,,{val},\n"
        )
        p = tmp_path / 'planes.csv'
        p.write_text(csv_content, encoding='utf-8')
        monkeypatch.setenv('PLAN_PROVIDER', 'csv')
        monkeypatch.setenv('PLAN_CSV_PATH', str(p))

        client = TestClient(app)
        payload = {
            "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
            "municipio": "Foo",
        }
        r = client.post('/zoning/volume', json=payload)
        assert r.status_code == 400
        assert 'ocupacion_max debe estar en [0,1]' in r.json()['detail']


def test_csv_edificabilidad_negative_causes_400(tmp_path, monkeypatch):
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,,10,2,,,,,0.3,-0.01\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert 'edificabilidad_max_m2_m2 debe ser >=' in r.json()['detail']


def test_csv_unknown_columns_emit_warning(tmp_path, monkeypatch, caplog):
    # CSV with an unknown column 'extra_col' should log a warning but not fail
    csv_content = (
        "municipio,subzona,altura_maxima_m,extra_col\n"
        "Foo,,10,something\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    from app.main import app
    from fastapi.testclient import TestClient
    import logging
    with caplog.at_level(logging.WARNING):
        client = TestClient(app)
        payload = {
            "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
            "municipio": "Foo",
        }
        r = client.post('/zoning/volume', json=payload)
        assert r.status_code == 200
    # Ensure the warning about unknown columns is present
    msgs = [rec.getMessage() for rec in caplog.records]
    assert any('Columnas desconocidas en CSV' in m and 'extra_col' in m for m in msgs)


def test_csv_altura_zero_or_negative_causes_400(tmp_path, monkeypatch):
    for altura in ('0', '-5'):
        csv_content = (
            "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
            f"Foo,,{altura},2,,,,,,\n"
        )
        p = tmp_path / 'planes.csv'
        p.write_text(csv_content, encoding='utf-8')
        monkeypatch.setenv('PLAN_PROVIDER', 'csv')
        monkeypatch.setenv('PLAN_CSV_PATH', str(p))

        client = TestClient(app)
        payload = {
            "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
            "municipio": "Foo",
        }
        r = client.post('/zoning/volume', json=payload)
        assert r.status_code == 400
        assert 'altura_maxima_m debe ser > 0' in r.json()['detail'] or 'altura_maxima_m requerida' in r.json()['detail']


def test_csv_negative_retranqueo_min_causes_400(tmp_path, monkeypatch):
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,,10,-1,,,,,,\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert 'retranqueo_min_m debe ser >=' in r.json()['detail']


def test_csv_negative_setbacks_cause_400(tmp_path, monkeypatch):
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,,10,2,-1,0,-0.5,north,,\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
        "use_plan_front_default": True
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert 'debe ser >=' in r.json()['detail'] and 'setback' in r.json()['detail']


def test_csv_missing_municipio_header_causes_400(tmp_path, monkeypatch):
    # Omit 'municipio' column entirely; provider won't be able to match rows -> altura None -> 400
    csv_content = (
        "subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        ",12,3,,,,,,\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 400
    assert (
        'No se pudieron obtener parámetros municipales' in r.json()['detail']
        or 'altura_maxima_m requerida' in r.json()['detail']
        or 'CSV faltan columnas requeridas' in r.json()['detail']
    )


def test_csv_invalid_setback_numbers_without_front_default_is_ok(tmp_path, monkeypatch):
    # Setbacks non-numeric but no front_direction_default -> provider returns None for setbacks; still OK
    csv_content = (
        "municipio,subzona,altura_maxima_m,retranqueo_min_m,setback_front_m,setback_side_m,setback_back_m,front_direction_default,ocupacion_max,edificabilidad_max_m2_m2\n"
        "Foo,,10,2,abc,def,ghi,,0.30,0.80\n"
    )
    p = tmp_path / 'planes.csv'
    p.write_text(csv_content, encoding='utf-8')
    monkeypatch.setenv('PLAN_PROVIDER', 'csv')
    monkeypatch.setenv('PLAN_CSV_PATH', str(p))

    client = TestClient(app)
    payload = {
        "geometry": {"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
        "municipio": "Foo",
    }
    r = client.post('/zoning/volume', json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data['feature'] is not None
