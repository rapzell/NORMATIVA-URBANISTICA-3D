import json
from urllib.error import HTTPError
from fastapi.testclient import TestClient
from app.main import app
import types

client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert isinstance(j.get("version"), str)
    assert isinstance(j.get("time"), int)


def test_proxy_siose_amortize_4xx(monkeypatch):
    # Simula que el WFS externo responde 400 para que el proxy devuelva FeatureCollection vacío (200)
    def fake_urlopen(req, timeout=15):
        # urllib.error.HTTPError: (url, code, msg, hdrs, fp)
        raise HTTPError(url=getattr(req, 'full_url', 'http://fake'), code=400, msg='Bad Request', hdrs=None, fp=None)

    import urllib.request as _ur
    monkeypatch.setattr(_ur, 'urlopen', fake_urlopen, raising=True)

    r = client.get("/proxy/siose", params={
        'bbox': '-8.72,42.21,-8.70,42.23,EPSG:4326',
        'typeNames': 'elu:LandCoverUnit',
        'srsName': 'EPSG:4326',
        'version': '2.0.0'
    })
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, dict)
    assert j.get('type') == 'FeatureCollection'
    assert isinstance(j.get('features'), list)


def test_proxy_wmscap_amortize_4xx(monkeypatch):
    # Simula 400 para que el proxy responda XML mínimo (200)
    def fake_urlopen(req, timeout=15):
        raise HTTPError(url=getattr(req, 'full_url', 'http://fake'), code=404, msg='Not Found', hdrs=None, fp=None)

    import urllib.request as _ur
    monkeypatch.setattr(_ur, 'urlopen', fake_urlopen, raising=True)

    r = client.get("/proxy/wmscap", params={
        'url': 'https://mapas.xunta.gal/servizos/ows?service=WMS&request=GetCapabilities'
    })
    assert r.status_code == 200
    # Debe ser XML mínimo; no validamos estructura completa, solo tipo de contenido y comienzo de payload
    ctype = r.headers.get('content-type', '')
    assert 'xml' in ctype
    txt = r.text.strip()
    assert txt.startswith('<WMS_Capabilities')


def test_official_catastro_by_coords_parses_xml(monkeypatch):
    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self):
            return b'''<?xml version="1.0" encoding="utf-8"?>
<consulta_coordenadas>
  <coordenadas>
    <coord>
      <pc><pc1>1234567</pc1><pc2>AB1234C</pc2></pc>
      <geo><xcen>-8.72</xcen><ycen>42.23</ycen><srs>EPSG:4326</srs></geo>
      <ldt>RUA DEMO 1 VIGO</ldt>
    </coord>
  </coordenadas>
</consulta_coordenadas>'''

    import app.main as _m
    monkeypatch.setattr(_m, 'urlopen', lambda req, timeout=20: _FakeResp(), raising=True)
    r = client.get('/official/catastro/by-coords', params={'lon': -8.72, 'lat': 42.23})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['found'] is True
    assert j['refcat'] == '1234567AB1234C'
    assert 'VIGO' in j['direccion']


def test_catastro_parser_handles_default_namespace():
    import app.main as _m
    raw = b'''<?xml version="1.0" encoding="utf-8"?>
<consulta_coordenadas xmlns="http://www.catastro.meh.es/">
  <coordenadas><coord>
    <pc><pc1>3057003</pc1><pc2>NG2725N</pc2></pc>
    <geo><xcen>-8.723</xcen><ycen>42.2311</ycen><srs>EPSG:4326</srs></geo>
    <ldt>RU MARQUES DE ALCEDO 13 VIGO (PONTEVEDRA)</ldt>
  </coord></coordenadas>
</consulta_coordenadas>'''
    parsed = _m._parse_catastro_rccoor_xml(raw)
    assert parsed['found'] is True
    assert parsed['refcat'] == '3057003NG2725N'
    assert 'VIGO' in parsed['direccion']


def test_siose_gml_parser_returns_geojson():
    import app.main as _m
    raw = b'''<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:lcv="http://inspire.ec.europa.eu/schemas/lcv/4.0" xmlns:xlink="http://www.w3.org/1999/xlink">
<wfs:member><lcv:LandCoverUnit><lcv:geometry><gml:Surface><gml:patches><gml:PolygonPatch><gml:exterior><gml:LinearRing><gml:posList>-8.72 42.23 -8.71 42.23 -8.71 42.24 -8.72 42.23</gml:posList></gml:LinearRing></gml:exterior></gml:PolygonPatch></gml:patches></gml:Surface></lcv:geometry><lcv:landCoverObservation><lcv:LandCoverObservation><lcv:class xlink:href="https://registro.idee.es/codelist/CODIIGEValue/112"/></lcv:LandCoverObservation></lcv:landCoverObservation></lcv:LandCoverUnit></wfs:member>
</wfs:FeatureCollection>'''
    parsed = _m._parse_siose_gml(raw)
    assert parsed['type'] == 'FeatureCollection'
    assert len(parsed['features']) == 1
    assert parsed['features'][0]['geometry']['type'] == 'Polygon'
    assert parsed['features'][0]['properties']['code'] == '112'
    assert parsed['features'][0]['properties']['label'] == 'Área de expansión urbana'


def test_official_context_includes_planeamiento_without_geometry(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_load_inventario', lambda: [
        {'CONCELLO': 'Vigo', 'FIGURA': 'PXOM', 'ESTADO': 'Vixente'},
        {'CONCELLO': 'Lugo', 'FIGURA': 'PXOM', 'ESTADO': 'Vixente'},
    ], raising=True)
    r = client.get('/official/context', params={'municipio': 'Vigo'})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['planeamiento']['available'] is True
    assert j['planeamiento']['count'] == 1
    assert j['catastro']['available'] is False


def test_official_catastro_rejects_coords_outside_galicia():
    """Coordenadas fuera de Galicia deben devolver found=False sin consultar el Catastro."""
    r = client.get('/official/catastro/by-coords', params={'lon': -3.70, 'lat': 40.42})  # Madrid
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['found'] is False
    assert 'fuera de Galicia' in (j.get('error') or '')


def test_official_context_includes_data_quality(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_load_inventario', lambda: [], raising=True)
    monkeypatch.setattr(_m, '_fetch_catastro_by_coords', lambda lon, lat, srs='EPSG:4326': {
        'found': True, 'refcat': '1234567AB1234C', 'direccion': 'RUA DEMO', 'x': '-8.72', 'y': '42.23',
    }, raising=True)
    monkeypatch.setattr(_m, '_fetch_siose_precheck', lambda lon, lat, delta=0.0015: {
        'available': True, 'land_cover_labels': [], 'alerts': [],
    }, raising=True)
    r = client.get('/official/context', params={'municipio': 'Vigo', 'lon': -8.72, 'lat': 42.23})
    assert r.status_code == 200, r.text
    j = r.json()
    assert 'data_quality' in j
    assert j['data_quality'] in ('alta', 'media', 'baja')
    assert 'coord_consistency' in j['catastro']


def test_building_diagnostic_compatible(monkeypatch):
    """Diagnóstico de edificio compatible con la subzona."""
    import src.subzones_service as _ss
    # Mock find_subzone_by_name to return a subzone with altura_maxima_m=12
    monkeypatch.setattr(_ss, 'find_subzone_by_name', lambda municipio, subzona: {
        'subzona': 'R-1', 'municipio': 'Vigo', 'altura_maxima_m': 12.0,
        'ocupacion_max': 0.6, 'edificabilidad_max_m2_m2': 1.5, 'retranqueo_min_m': 3.0,
    }, raising=True)
    r = client.get('/zoning/building-diagnostic', params={
        'height_m': 9.0, 'levels': 3, 'subzona': 'R-1', 'municipio': 'Vigo',
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['available'] is True
    assert j['verdict'] == 'compatible'
    assert len(j['comparisons']) >= 2
    # La comparación de altura debe cumplir
    alt_comp = [c for c in j['comparisons'] if c['parametro'] == 'Altura'][0]
    assert alt_comp['cumple'] is True
    assert 'margen' in alt_comp['diferencia']


def test_building_diagnostic_marks_pilot_as_orientative(monkeypatch):
    import src.subzones_service as _ss
    monkeypatch.setattr(_ss, 'find_subzone_by_name', lambda municipio, subzona: {
        'subzona': 'R-1', 'municipio': 'Vigo', 'altura_maxima_m': 12.0,
        'normative_status': 'pilot', 'fuente': 'PXOM Vigo (piloto)',
    }, raising=True)
    r = client.get('/zoning/building-diagnostic', params={
        'height_m': 9.0, 'subzona': 'R-1', 'municipio': 'Vigo',
    })
    assert r.status_code == 200
    data = r.json()
    assert data['verdict'] == 'orientativo_dentro'
    assert data['normative_status'] == 'pilot'
    assert data['comparisons'][0]['cumple'] is None
    assert data['comparisons'][0]['resultado_orientativo'] == 'dentro'
    assert 'no oficial' in data['warning']


def test_building_diagnostic_exceeds(monkeypatch):
    """Diagnóstico de edificio que supera la altura de subzona."""
    import src.subzones_service as _ss
    monkeypatch.setattr(_ss, 'find_subzone_by_name', lambda municipio, subzona: {
        'subzona': 'R-1', 'municipio': 'Vigo', 'altura_maxima_m': 10.0,
        'ocupacion_max': 0.5, 'edificabilidad_max_m2_m2': 1.0, 'retranqueo_min_m': 3.0,
    }, raising=True)
    r = client.get('/zoning/building-diagnostic', params={
        'height_m': 15.0, 'levels': 5, 'subzona': 'R-1', 'municipio': 'Vigo',
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['available'] is True
    assert j['verdict'] == 'supera_altura'
    assert len(j['issues']) >= 1
    alt_comp = [c for c in j['comparisons'] if c['parametro'] == 'Altura'][0]
    assert alt_comp['cumple'] is False
    assert 'exceso' in alt_comp['diferencia']



def test_official_context_includes_siose_precheck(monkeypatch):
    import app.main as _m
    monkeypatch.setattr(_m, '_load_inventario', lambda: [], raising=True)
    monkeypatch.setattr(_m, '_fetch_catastro_by_coords', lambda lon, lat, srs='EPSG:4326': {'found': False}, raising=True)
    monkeypatch.setattr(_m, '_fetch_siose_precheck', lambda lon, lat, delta=0.0015: {
        'available': True,
        'land_cover_labels': ['agua'],
        'alerts': ['Entorno potencialmente sensible por presencia de agua'],
        'disclaimer': 'Prechequeo preliminar basado en SIOSE; no sustituye verificación sectorial oficial.',
    }, raising=True)
    r = client.get('/official/context', params={'municipio': 'Vigo', 'lon': -8.72, 'lat': 42.23})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['afecciones_preliminares']['available'] is True
    assert 'agua' in j['afecciones_preliminares']['land_cover_labels']
    assert j['afecciones_preliminares']['alerts']


def test_official_afecciones_returns_geojson(monkeypatch):
    import app.main as _m
    fake_data = {
        'type': 'FeatureCollection',
        'features': [
            {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, 'properties': {'label': 'Bosque frondoso'}},
            {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, 'properties': {'label': 'Cauce fluvial'}},
        ]
    }
    monkeypatch.setattr(_m, '_fetch_siose_afecciones_geojson', lambda bbox: {
        'type': 'FeatureCollection',
        'features': [
            {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, 'properties': {'label': 'Bosque frondoso', 'clase': 'sensible_natural', 'alerta': 'Revisar afección ambiental/paisajística por cobertura Bosque frondoso', 'source': 'SIOSE (IDEE)'}},
            {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[1,1],[0,1],[0,0]]]}, 'properties': {'label': 'Cauce fluvial', 'clase': 'sensible_agua', 'alerta': 'Entorno potencialmente sensible por presencia de Cauce fluvial', 'source': 'SIOSE (IDEE)'}},
        ]
    }, raising=True)
    r = client.get('/official/afecciones', params={'bbox': '-8.72,42.21,-8.70,42.23'})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['type'] == 'FeatureCollection'
    assert len(j['features']) == 2
    assert j['features'][0]['properties']['clase'] == 'sensible_natural'
    assert j['features'][1]['properties']['clase'] == 'sensible_agua'
