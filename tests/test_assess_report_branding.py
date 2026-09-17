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
    """El informe sin geometria no debe incluir el contenido cartografico."""
    body = {
        "geometry": None,
        "altura_maxima_m": 10.0,
        "retranqueo_min_m": 3.0,
    }
    b64 = _b64url(body)
    r = client.get("/zoning/assess-report", params={"body_b64": b64})
    assert r.status_code == 200, r.text
    html = r.text
    # Sin geometria, no hay contenido cartografico (SVG minimap)
    assert "Vista esquemática de la parcela" not in html
    assert "Sin geometría para mostrar" in html


def test_assess_report_includes_trazabilidad_y_bu(monkeypatch):
    """El informe rinde data_points con calidad/fuente y datos Catastro BU."""
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {
        'data_quality': 'alta',
        'catastro': {
            'available': True, 'refcat': '1234567AB1234C',
            'edificios_oficiales': 2, 'plantas_oficiales': 4,
        },
        'planeamiento': {'available': False},
        'siotuga': {'available': True, 'note': 'x'},
        'afecciones_preliminares': {'available': False, 'alerts': []},
        'provenance': {
            'query_timestamp': '2026-09-17T00:00:00Z',
            'api_version': '0.2.1',
            'sources': [],
        },
        'data_points': {
            'clasificacion_suelo': {
                'value': 'Suelo Urbano Consolidado', 'unit': None,
                'data_quality': 'official', 'source': 'SIOTUGA WFS',
                'source_ref': 'vectorial local', 'notes': None,
            },
            'altura': {
                'value': 14.2, 'unit': 'm', 'data_quality': 'measured',
                'source': 'PNOA LiDAR', 'source_ref': 'P90', 'notes': None,
            },
        },
    })
    b64 = _b64url({"geometry": None, "municipio": "Vigo"})
    r = client.get("/zoning/assess-report", params={"body_b64": b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert "Trazabilidad por dato" in html
    assert "Suelo Urbano Consolidado" in html
    assert "Oficial" in html and "Medido" in html
    assert "SIOTUGA WFS" in html and "PNOA LiDAR" in html
    assert "Edificios en parcela (Catastro INSPIRE BU)" in html
    assert "Plantas (Catastro INSPIRE BU)" in html


def test_assess_report_includes_official_context(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {
        'catastro': {
            'available': True,
            'refcat': '1234567AB1234C',
            'direccion': 'RUA DEMO 1 VIGO',
            'query_lon': -8.72,
            'query_lat': 42.23,
        },
        'planeamiento': {
            'available': True,
            'count': 1,
            'rows': [{'CONCELLO': 'Vigo', 'FIGURA': 'PXOM', 'ESTADO': 'Vixente'}],
        },
        'siotuga': {
            'available': True,
            'note': 'Contexto apoyado en inventario municipal y servicios WMS/WFS/proxy ya integrados',
        },
        'afecciones_preliminares': {
            'available': True,
            'land_cover_labels': ['agua'],
            'alerts': ['Entorno potencialmente sensible por presencia de agua'],
            'disclaimer': 'Prechequeo preliminar basado en SIOSE; no sustituye verificación sectorial oficial.',
        },
    }, raising=True)
    body = {
        'geometry': None,
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Datos oficiales y contexto' in html
    assert '1234567AB1234C' in html
    assert 'RUA DEMO 1 VIGO' in html
    assert 'PXOM' in html
    assert 'Afecciones preliminares' in html
    assert 'agua' in html


def test_assess_report_includes_surface_table(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {}, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'ocupacion_max': 0.5,
        'setback_front_m': 3.0,
        'setback_side_m': 3.0,
        'setback_back_m': 3.0,
        'front_direction': 'north',
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Cuadro de superficies' in html
    assert 'Superficie de parcela' in html
    assert 'Superficie libre estimada' in html
    assert 'Envolvente edificable' in html


def test_assess_report_includes_economic_estimate(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {}, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'ocupacion_max': 0.5,
        'edificabilidad_max_m2_m2': 1.25,
        'setback_front_m': 3.0,
        'setback_side_m': 3.0,
        'setback_back_m': 3.0,
        'front_direction': 'north',
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Estimación económica preliminar' in html
    assert 'Superficie edificable total estimada' in html
    assert 'Viviendas potenciales' in html


def test_assess_report_includes_shadow_analysis(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {}, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[-8.72, 42.23], [-8.71, 42.23], [-8.71, 42.24], [-8.72, 42.24], [-8.72, 42.23]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'ocupacion_max': 0.5,
        'edificabilidad_max_m2_m2': 1.25,
        'setback_front_m': 3.0,
        'setback_side_m': 3.0,
        'setback_back_m': 3.0,
        'front_direction': 'north',
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Análisis de sombras' in html
    assert 'Elevación solar' in html
    assert 'Azimut solar' in html
    assert 'Longitud sombra' in html


def test_assess_report_includes_diagnostic_comparison(monkeypatch):
    """El informe debe incluir el diagnóstico comparativo edificio vs subzona."""
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {}, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[-8.72, 42.23], [-8.71, 42.23], [-8.71, 42.24], [-8.72, 42.24], [-8.72, 42.23]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'height_m': 9.0,
        'levels': 3,
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'ocupacion_max': 0.5,
        'edificabilidad_max_m2_m2': 1.25,
        'setback_front_m': 3.0,
        'setback_side_m': 3.0,
        'setback_back_m': 3.0,
        'front_direction': 'north',
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Diagnóstico comparativo' in html
    assert 'Edificio' in html
    assert 'Norma' in html
    assert 'Estado' in html


def test_assess_report_includes_official_source_links(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {
        'catastro': {'available': True, 'refcat': '1234567AB1234C', 'direccion': 'RUA DEMO 1 VIGO', 'query_lon': -8.72, 'query_lat': 42.23},
        'planeamiento': {'available': True, 'count': 1, 'rows': [{'CONCELLO': 'Vigo', 'FIGURA': 'PXOM', 'ESTADO': 'Aprobado'}]},
        'siotuga': {'available': True, 'note': 'Contexto SIOTUGA'},
        'afecciones_preliminares': {'available': True, 'alerts': ['Revisar zona húmeda'], 'land_cover_labels': ['Agua'], 'disclaimer': 'Preliminar'},
    }, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[-8.72, 42.23], [-8.71, 42.23], [-8.71, 42.24], [-8.72, 42.24], [-8.72, 42.23]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Fuentes oficiales consultadas' in html
    assert 'sedecatastro.gob.es' in html
    assert 'OVCListaBienes' in html
    assert 'siotuga.xunta.gal' in html
    assert 'servicios.idee.es' in html
    assert 'GetFeatureInfo' in html or 'GetCapabilities' in html
    assert 'Ver parcela' in html or 'Buscador de inmuebles' in html
    assert 'target="_blank"' in html


def test_assess_report_has_professional_template(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {}, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'class="cover"' in html
    assert 'Informe de viabilidad urbanística preliminar' in html
    assert 'class="toc"' in html
    assert 'Índice' in html
    assert 'section-num' in html
    assert 'sec-1' in html
    assert 'sec-11' in html
    assert 'Resumen ejecutivo' in html
    assert 'Parámetros efectivos' in html


def test_assess_report_includes_provenance(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {
        'catastro': {'available': True, 'refcat': '1234567AB1234C', 'direccion': 'RUA DEMO 1 VIGO', 'query_lon': -8.72, 'query_lat': 42.23},
        'planeamiento': {'available': True, 'count': 1, 'rows': [{'CONCELLO': 'Vigo', 'FIGURA': 'PXOM', 'ESTADO': 'Aprobado'}]},
        'siotuga': {'available': True, 'note': 'Contexto SIOTUGA'},
        'afecciones_preliminares': {'available': True, 'alerts': ['Revisar zona húmeda'], 'land_cover_labels': ['Agua'], 'disclaimer': 'Preliminar'},
        'provenance': {
            'query_timestamp': '2025-01-15T12:00:00+00:00',
            'api_version': '0.2.1',
            'sources': [
                {'name': 'Catastro (OVC)', 'url': 'https://ovc.catastro.meh.es/', 'type': 'coordenadas/referencia'},
                {'name': 'SIOTUGA', 'url': 'https://siotuga.xunta.gal/', 'type': 'planeamiento territorial'},
            ],
        },
    }, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[-8.72, 42.23], [-8.71, 42.23], [-8.71, 42.24], [-8.72, 42.24], [-8.72, 42.23]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Proveniencia de los datos' in html
    assert 'Fecha de consulta' in html
    assert 'Versión de la API' in html
    assert 'Catastro (OVC)' in html
    assert 'SIOTUGA' in html


def test_assess_report_includes_enhanced_catastro(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {
        'catastro': {
            'available': True,
            'refcat': '1234567AB1234C',
            'direccion': 'RUA DEMO 1 VIGO',
            'query_lon': -8.72,
            'query_lat': 42.23,
            'superficie_terreno_m2': 350.5,
            'superficie_construida_m2': 180.0,
            'uso_principal': 'Residencial',
            'anio_construccion': 1985,
            'municipio_catastral': 'Vigo',
        },
        'planeamiento': {'available': False, 'count': 0, 'rows': []},
        'siotuga': {'available': True, 'note': 'Contexto SIOTUGA'},
        'afecciones_preliminares': {'available': False, 'alerts': []},
        'provenance': {
            'query_timestamp': '2025-01-15T12:00:00+00:00',
            'api_version': '0.2.1',
            'sources': [],
        },
    }, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[-8.72, 42.23], [-8.71, 42.23], [-8.71, 42.24], [-8.72, 42.24], [-8.72, 42.23]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Superficie terreno' in html
    assert '350.5' in html
    assert 'Superficie construida' in html
    assert '180.0' in html
    assert 'Uso principal' in html
    assert 'Residencial' in html
    assert 'Año construcción' in html
    assert '1985' in html


def test_assess_report_shows_data_quality(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_build_official_context', lambda **kwargs: {
        'catastro': {
            'available': True,
            'refcat': '1234567AB1234C',
            'direccion': 'RUA DEMO 1 VIGO',
            'query_lon': -8.72,
            'query_lat': 42.23,
            'coord_consistency': 'ok',
            'municipio_consistency': 'ok',
        },
        'planeamiento': {'available': True, 'count': 1, 'rows': []},
        'siotuga': {'available': True, 'note': 'Contexto SIOTUGA'},
        'afecciones_preliminares': {'available': True, 'alerts': [], 'land_cover_labels': []},
        'data_quality': 'alta',
        'provenance': {
            'query_timestamp': '2025-01-15T12:00:00+00:00',
            'api_version': '0.2.1',
            'sources': [],
        },
    }, raising=True)
    body = {
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[[-8.72, 42.23], [-8.71, 42.23], [-8.71, 42.24], [-8.72, 42.24], [-8.72, 42.23]]],
        },
        'municipio': 'Vigo',
        'subzona': 'R-1',
        'altura_maxima_m': 12.0,
        'retranqueo_min_m': 3.0,
        'crs': 'EPSG:4326',
    }
    b64 = _b64url(body)
    r = client.get('/zoning/assess-report', params={'body_b64': b64})
    assert r.status_code == 200, r.text
    html = r.text
    assert 'Calidad de datos' in html
    assert 'alta' in html
    assert 'Consistencia coordenadas' in html
    assert 'Consistencia municipio' in html
