"""Tests del downloader vectorial SIOTUGA con GML de fixture."""
import xml.etree.ElementTree as ET

from src.siotuga import vector_downloader as vd

LAYER = '_36057_PXOM_202505_AD_3CLAS_28719'

GML_PAGE = f'''<?xml version="1.0" encoding="utf-8"?>
<wfs:FeatureCollection xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
 xmlns:gml="http://www.opengis.net/gml" xmlns:wfs="http://www.opengis.net/wfs">
 <gml:featureMember>
  <ms:{LAYER} gml:id="{LAYER}.1">
   <gml:boundedBy><gml:Envelope srsName="EPSG:4326">
    <gml:lowerCorner>-8.72 42.23</gml:lowerCorner>
    <gml:upperCorner>-8.71 42.24</gml:upperCorner>
   </gml:Envelope></gml:boundedBy>
   <ms:msGeometry>
    <gml:Polygon srsName="EPSG:4326">
     <gml:exterior><gml:LinearRing>
      <gml:posList srsDimension="2">42.23 -8.72 42.23 -8.71 42.24 -8.71 42.24 -8.72 42.23 -8.72</gml:posList>
     </gml:LinearRing></gml:exterior>
    </gml:Polygon>
   </ms:msGeometry>
   <ms:cla_ley>SUC</ms:cla_ley>
   <ms:cat_ley>SUC</ms:cat_ley>
   <ms:id_recinto>28719-1</ms:id_recinto>
   <ms:denom>RESIDENCIAL</ms:denom>
   <ms:uso>VIV:90</ms:uso>
   <ms:sup_ficha>5000</ms:sup_ficha>
   <ms:edif_ficha>1.2</ms:edif_ficha>
  </ms:{LAYER}>
 </gml:featureMember>
 <gml:featureMember>
  <ms:{LAYER} gml:id="{LAYER}.2">
   <ms:msGeometry>
    <gml:Polygon srsName="EPSG:4326">
     <gml:exterior><gml:LinearRing>
      <gml:posList srsDimension="2">42.23 -8.70 42.23 -8.69 42.24 -8.69 42.24 -8.70 42.23 -8.70</gml:posList>
     </gml:LinearRing></gml:exterior>
    </gml:Polygon>
   </ms:msGeometry>
   <ms:cla_ley>SNR</ms:cla_ley>
   <ms:cat_ley>SNR</ms:cat_ley>
  </ms:{LAYER}>
 </gml:featureMember>
</wfs:FeatureCollection>'''

GML_EMPTY = b'''<?xml version="1.0"?>
<wfs:FeatureCollection xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
 xmlns:gml="http://www.opengis.net/gml" xmlns:wfs="http://www.opengis.net/wfs">
</wfs:FeatureCollection>'''


def _fake_fetch(url: str) -> bytes:
    if 'startindex=0' in url or 'startindex' not in url:
        return GML_PAGE.encode('utf-8')
    return GML_EMPTY


def test_feature_parse():
    root = ET.fromstring(GML_PAGE.encode('utf-8'))
    feats = [vd._feature_to_geojson(f, LAYER) for f in vd._iter_features(root, LAYER)]
    feats = [f for f in feats if f]
    assert len(feats) == 2
    assert feats[0]['geometry']['type'] == 'Polygon'
    assert feats[0]['properties']['cla_ley'] == 'SUC'
    assert feats[0]['geometry']['coordinates'][0][0] == [-8.72, 42.23]


def test_descarga_municipio(tmp_path, monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    monkeypatch.setattr(vd, 'disk_get', cache.disk_get)
    monkeypatch.setattr(vd, 'disk_set', cache.disk_set)
    fc = vd.descargar_clasificacion_municipio('36057', LAYER, fetch=_fake_fetch)
    assert fc['type'] == 'FeatureCollection'
    assert len(fc['features']) == 2
    assert fc['metadata']['data_quality'] == 'official'
    assert fc['metadata']['feature_count'] == 2


def test_consultar_punto_dentro(tmp_path, monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    vd.descargar_clasificacion_municipio('36057', LAYER, fetch=_fake_fetch)
    res = vd.consultar_clasificacion_punto(-8.715, 42.235, '36057', LAYER)
    assert res['clasificacion_ley'] == 'SUC'
    assert res['clasificacion_ley_label'] == 'Suelo Urbano Consolidado'
    assert res['edificabilidad_ficha'] == 1.2
    assert res['vectorial_local'] is True
    assert res['fuente'] == 'SIOTUGA WFS (vectorial local)'


def test_consultar_punto_fuera_recurre_wfs(tmp_path, monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    vd.descargar_clasificacion_municipio('36057', LAYER, fetch=_fake_fetch)
    # Punto fuera de la capa local → consulta WFS puntual (fixture vacía → {})
    res = vd.consultar_clasificacion_punto(-9.5, 43.0, '36057', LAYER,
                                         fetch=lambda u: GML_EMPTY)
    assert res == {}


def test_consultar_punto_sin_layer_ni_red_usa_cache(tmp_path, monkeypatch):
    """Sin layer_name ni red: resuelve desde cualquier capa cacheada."""
    from src import cache
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    vd.descargar_clasificacion_municipio('36057', LAYER, fetch=_fake_fetch)

    def _boom(url):
        raise RuntimeError('sin red')
    res = vd.consultar_clasificacion_punto(-8.715, 42.235, '36057',
                                         layer_name=None, fetch=_boom)
    assert res['clasificacion_ley'] == 'SUC'
    assert res['vectorial_local'] is True


def test_capa_cacheada_devuelve_la_mas_completa(tmp_path, monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    assert vd.capa_cacheada('36057') is None
    vd.descargar_clasificacion_municipio('36057', LAYER, fetch=_fake_fetch)
    fc = vd.capa_cacheada('36057')
    assert fc is not None
    assert len(fc['features']) == 2
    assert vd.capa_cacheada('99999') is None


def test_props_to_result_labels():
    res = vd.props_to_result({'cat_ley': 'SUNC', 'edif_ficha': '0.7',
                              'sup_ficha': '62780', 'uso': 'TER'})
    assert res['clasificacion_ley'] == 'SUNC'
    assert res['clasificacion_ley_label'] == 'Suelo Urbano No Consolidado'
    assert res['edificabilidad_ficha'] == 0.7
    assert res['sup_ficha_m2'] == 62780.0
    assert res['uso_zona'] == 'TER'


def test_obtener_capa_geojson_recorte(tmp_path, monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    out = vd.obtener_capa_geojson('36057', LAYER,
                                bbox=(-8.73, 42.22, -8.715, 42.245),
                                fetch=_fake_fetch)
    assert len(out['features']) == 1
    assert out['features'][0]['properties']['clase_ley'] == 'SUC'
    assert out['features'][0]['properties']['clasificacion'] == 'Suelo Urbano Consolidado'
    assert out['features'][0]['properties']['fuente'] == 'SIOTUGA WFS'
