"""Tests del cliente Catastro (parsers con XML de fixture)."""
from src.catastro import client

BU_XML = b'''<?xml version="1.0" encoding="ISO-8859-1"?>
<gml:FeatureCollection xmlns:bu-core2d="http://inspire.jrc.ec.europa.eu/schemas/bu-core2d/2.0"
 xmlns:bu-ext2d="http://inspire.jrc.ec.europa.eu/schemas/bu-ext2d/2.0"
 xmlns:base="urn:x-inspire:specification:gmlas:BaseTypes:3.2"
 xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:xsi="http://www.w3.org/1999/xlink">
 <gml:featureMember>
  <bu-core2d:Building>
   <bu-core2d:inspireId><base:Identifier>
    <base:localId>3865011NG2736S</base:localId>
    <base:namespace>ES.SDGC.BU</base:namespace>
   </base:Identifier></bu-core2d:inspireId>
   <bu-core2d:beginLifespanVersion>2003-11-24T00:00:00</bu-core2d:beginLifespanVersion>
   <bu-core2d:conditionOfConstruction>functional</bu-core2d:conditionOfConstruction>
   <bu-core2d:dateOfConstruction><bu-core2d:DateOfEvent>
    <bu-core2d:beginning>1965-01-01T00:00:00</bu-core2d:beginning>
   </bu-core2d:DateOfEvent></bu-core2d:dateOfConstruction>
   <bu-ext2d:currentUse>1_residential</bu-ext2d:currentUse>
   <bu-ext2d:numberOfFloorsAboveGround>4</bu-ext2d:numberOfFloorsAboveGround>
   <bu-core2d:geometry><bu-core2d:BuildingGeometry>
    <bu-core2d:geometry><gml:Polygon srsName="EPSG:4326">
     <gml:exterior><gml:LinearRing>
      <gml:posList>-8.72 42.23 -8.71 42.23 -8.71 42.24 -8.72 42.24 -8.72 42.23</gml:posList>
     </gml:LinearRing></gml:exterior>
    </gml:Polygon></bu-core2d:geometry>
    <bu-core2d:referenceGeometry>true</bu-core2d:referenceGeometry>
   </bu-core2d:BuildingGeometry></bu-core2d:geometry>
  </bu-core2d:Building>
 </gml:featureMember>
</gml:FeatureCollection>'''

DNPRC_XML = b'''<?xml version="1.0" encoding="utf-8"?>
<consulta_dnp xmlns="http://www.catastro.meh.es/">
 <lrcdnp>
  <rcdnp>
   <rc><pc1>3865011</pc1><pc2>NG2736S</pc2><car>0001</car></rc>
   <loint><pt>00</pt><pu>A</pu></loint>
   <debi><luso>Residencial</luso><sfc>120,5</sfc><ant>1965</ant></debi>
  </rcdnp>
  <rcdnp>
   <rc><pc1>3865011</pc1><pc2>NG2736S</pc2><car>0002</car></rc>
   <loint><pt>BJ</pt><pu>B</pu></loint>
   <debi><luso>Comercial</luso><sfc>80</sfc><ant>1965</ant></debi>
  </rcdnp>
 </lrcdnp>
</consulta_dnp>'''


def test_parse_bu_edificio():
    res = client.parse_bu_xml(BU_XML)
    assert res['num_edificios'] == 1
    ed = res['edificios'][0]
    assert ed['referencia'] == '3865011NG2736S'
    assert ed['uso'] == '1_residential'
    assert ed['anio_construccion'] == 1965
    assert ed['plantas'] == 4
    assert ed['condicion'] == 'functional'
    assert ed['geometry']['type'] == 'Polygon'
    assert res['fuente'] == 'Catastro INSPIRE WFS BU'


def test_parse_bu_vacio():
    assert client.parse_bu_xml(b'<gml:FeatureCollection/>') == {}


def test_parse_dnprc():
    res = client.parse_dnprc_xml(DNPRC_XML)
    assert res['superficie_construida_m2'] == 200.5
    assert res['uso_principal'] == 'Residencial'
    assert res['anio_construccion'] == 1965
    assert res['num_unidades'] == 2
    assert len(res['unidades_comerciales']) == 1
    assert res['unidades_comerciales'][0]['planta'] == 'BJ'
    assert res['superficie_comercial_m2'] == 80


def test_obtener_edificios_por_parcela(tmp_path, monkeypatch):
    from src import cache
    monkeypatch.setattr(cache, 'CACHE_ROOT', str(tmp_path))
    res = client.obtener_edificios_por_parcela(
        '3865011NG2736S', fetch=lambda u: BU_XML)
    assert res['num_edificios'] == 1
    # segunda llamada → caché
    res2 = client.obtener_edificios_por_parcela(
        '3865011NG2736S', fetch=lambda u: b'<bad/>')
    assert res2['num_edificios'] == 1


def test_atom_feed_url():
    url = client.obtener_atom_feed_url('36057')
    assert '36' in url and '36057' in url


def test_obtener_por_coordenadas_parse():
    xml = b'''<consulta_coordenadas><coordenadas><coord>
    <pc><pc1>1234567</pc1><pc2>AB1234C</pc2></pc>
    <geo><xcen>-8.72</xcen><ycen>42.23</ycen></geo>
    <ldt>RUA DEMO</ldt></coord></coordenadas></consulta_coordenadas>'''
    res = client.obtener_por_coordenadas(-8.72, 42.23, fetch=lambda u: xml)
    assert res['found'] is True
    assert res['refcat'] == '1234567AB1234C'
