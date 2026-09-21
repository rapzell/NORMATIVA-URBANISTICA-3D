"""Cliente de servicios oficiales gratuitos del Catastro de España.

Servicios usados:

- **OVC RCCOOR** — referencia catastral y dirección por coordenadas.
- **OVC CPMRC** — centroide y dirección por referencia catastral.
- **OVC DNPRC** — desglose por unidad (uso, superficie, planta, puerta, año).
- **INSPIRE wfsCP** — geometría y superficie oficial de la parcela.
- **INSPIRE wfsBU** — edificios oficiales de la parcela (huella, uso,
  fecha de construcción, plantas cuando el servicio las publica).
- **ATOM BU** — URL de descarga masiva de edificios por municipio
  (documentada; la descarga puede superar 50 MB, usar bajo demanda).

Todas las funciones aceptan un ``fetch`` inyectable ``fetch(url) -> bytes``
para tests y una caché en disco vía :mod:`src.cache` (TTL configurable).

Ejemplo::

    from src.catastro import client
    b = client.obtener_edificios_por_parcela('3865011NG2736S')
    b['edificios'][0]['uso']  # '1_residential'
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Callable
from urllib.parse import urlencode

from src.cache import disk_get, disk_set, http_get

CAT_TTL_S = 30 * 24 * 3600  # Catastro se actualiza semestralmente

RCCOOR_URL = (
    'https://ovc.catastro.meh.es/ovcservweb/ovcswlocalizacionrc/'
    'ovccoordenadas.asmx/Consulta_RCCOOR'
)
CPMRC_URL = (
    'https://ovc.catastro.meh.es/ovcservweb/ovcswlocalizacionrc/'
    'ovccoordenadas.asmx/Consulta_CPMRC'
)
DNPRC_URL = (
    'https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/'
    'COVCCallejero.svc/rest/Consulta_DNPRC'
)
WFS_CP_URL = 'https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx'
WFS_BU_URL = 'https://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx'
ATOM_BU_URL = 'https://www.catastro.minhap.es/INSPIRE/buildings/ES.SDGC.BU.atom.xml'

Fetch = Callable[[str], bytes]


def _default_fetch(url: str) -> bytes:
    return http_get(url, timeout=15, retries=2)


def _try_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _try_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _strip_ns(root: ET.Element) -> ET.Element:
    for elem in root.iter():
        if '}' in elem.tag:
            elem.tag = elem.tag.rsplit('}', 1)[-1]
    return root


def parse_rccoor_xml(raw: bytes) -> dict:
    """Parsea la respuesta de Consulta_RCCOOR → {found, refcat, direccion}."""
    try:
        root = _strip_ns(ET.fromstring(raw))
    except Exception:
        return {'found': False, 'error': 'Respuesta Catastro no parseable'}
    coord = root.find('.//coord')
    if coord is None:
        return {'found': False}
    pc1 = coord.findtext('./pc/pc1') or ''
    pc2 = coord.findtext('./pc/pc2') or ''
    refcat = (pc1 + pc2).strip() or None
    return {
        'found': bool(refcat),
        'refcat': refcat,
        'direccion': coord.findtext('./ldt') or None,
        'srs': coord.findtext('./geo/srs') or coord.findtext('./srs') or 'EPSG:4326',
        'x': coord.findtext('./geo/xcen') or coord.findtext('./xcen'),
        'y': coord.findtext('./geo/ycen') or coord.findtext('./ycen'),
        'fuente': 'Catastro OVC RCCOOR',
    }


def obtener_por_coordenadas(lon: float, lat: float, srs: str = 'EPSG:4326',
                            fetch: Fetch | None = None) -> dict:
    """Referencia catastral y dirección en unas coordenadas (OVC RCCOOR)."""
    fetch = fetch or _default_fetch
    url = f"{RCCOOR_URL}?{urlencode({'SRS': srs, 'Coordenada_X': lon, 'Coordenada_Y': lat})}"
    return parse_rccoor_xml(fetch(url))


def parse_dnprc_xml(raw: bytes) -> dict:
    """Parsea Consulta_DNPRC → usos, superficies, unidades no residenciales."""
    try:
        root = ET.fromstring(raw)
    except Exception:
        return {}
    rcdnps = root.findall('.//{*}rcdnp')
    if not rcdnps:
        return {}
    result: dict[str, Any] = {}
    usos: dict[str, float] = {}
    total_sfc = 0.0
    anios: set[int] = set()
    unidades_comerciales: list[dict] = []
    for r in rcdnps:
        debi = r.find('.//{*}debi')
        if debi is None:
            continue
        luso = (debi.findtext('{*}luso') or '').strip()
        sfc = _try_float((debi.findtext('{*}sfc') or '').strip().replace(',', '.'))
        ant = _try_int((debi.findtext('{*}ant') or '').strip())
        car = (r.findtext('.//{*}rc/{*}car') or '').strip()
        loint = r.find('.//{*}loint')
        planta = (loint.findtext('{*}pt') or '').strip() if loint is not None else ''
        puerta = (loint.findtext('{*}pu') or '').strip() if loint is not None else ''
        if sfc and sfc > 0:
            total_sfc += sfc
            usos[luso] = usos.get(luso, 0) + sfc
            if luso in ('Comercial', 'Oficinas', 'Almacen-Estacionamiento'):
                unidades_comerciales.append(
                    {'car': car, 'uso': luso, 'sfc': sfc,
                     'planta': planta, 'puerta': puerta})
        if ant and 1800 < ant < 2100:
            anios.add(ant)
    if total_sfc > 0:
        result['superficie_construida_m2'] = round(total_sfc, 2)
    if usos:
        result['uso_principal'] = max(usos, key=usos.get)
        result['usos_detalle'] = usos
    if anios:
        result['anio_construccion'] = min(anios)
    if unidades_comerciales:
        result['unidades_comerciales'] = unidades_comerciales
        result['superficie_comercial_m2'] = round(
            sum(u['sfc'] for u in unidades_comerciales), 2)
    result['num_unidades'] = len(rcdnps)
    result['fuente'] = 'Catastro OVC DNPRC'
    return result


def obtener_detalles_por_ref(refcat: str, fetch: Fetch | None = None) -> dict:
    """Datos DNPRC por referencia catastral (usos, superficies, unidades)."""
    fetch = fetch or _default_fetch
    rc = ''.join(ch for ch in (refcat or '') if ch.isalnum()).upper()[:14]
    if len(rc) < 14:
        return {}
    cached = disk_get('catastro', f'dnprc_{rc}', CAT_TTL_S)
    if cached is not None:
        return cached
    url = f"{DNPRC_URL}?{urlencode({'Provincia': '', 'Municipio': '', 'RefCat': rc})}"
    try:
        result = parse_dnprc_xml(fetch(url))
    except Exception:
        return {}
    if result:
        disk_set('catastro', f'dnprc_{rc}', result)
    return result


def parse_parcel_wfs_xml(raw: bytes) -> dict:
    """Parsea GetParcel (wfsCP) → superficie oficial, label, geometría."""
    try:
        root = ET.fromstring(raw)
    except Exception:
        return {}
    result: dict[str, Any] = {}
    for elem in root.iter():
        if elem.tag.endswith('areaValue'):
            val = _try_float(elem.text)
            if val and val > 0:
                result['superficie_parcela_m2'] = val
                break
    for elem in root.iter():
        if elem.tag.endswith('label'):
            result['label'] = (elem.text or '').strip()
            break
    for elem in root.iter():
        if elem.tag.endswith('posList'):
            coords_txt = (elem.text or '').strip()
            if coords_txt:
                pairs = coords_txt.split()
                coords = [[float(pairs[i + 1]), float(pairs[i])]
                          for i in range(0, len(pairs) - 1, 2)]
                if len(coords) >= 4:
                    result['geometry'] = {
                        'type': 'Polygon', 'coordinates': [coords]}
                break
    if result:
        result['fuente'] = 'Catastro INSPIRE WFS CP'
    return result


def obtener_parcela_por_ref(refcat: str, fetch: Fetch | None = None) -> dict:
    """Geometría y superficie oficial de la parcela (INSPIRE wfsCP)."""
    fetch = fetch or _default_fetch
    rc = ''.join(ch for ch in (refcat or '') if ch.isalnum()).upper()[:14]
    if len(rc) < 14:
        return {}
    cached = disk_get('catastro', f'parcel_{rc}', CAT_TTL_S)
    if cached is not None:
        return cached
    url = (
        f'{WFS_CP_URL}?service=wfs&version=2&request=getfeature'
        f'&STOREDQUERIE_ID=GetParcel&refcat={rc}&srsname=EPSG:4326'
    )
    try:
        result = parse_parcel_wfs_xml(fetch(url))
    except Exception:
        return {}
    if result:
        disk_set('catastro', f'parcel_{rc}', result)
    return result


def parse_bu_xml(raw: bytes) -> dict:
    """Parsea GetBuildingByParcel (wfsBU) → lista de edificios oficiales.

    Extrae por cada ``bu:Building``: referencia, uso, fecha de
    construcción, estado, plantas sobre rasante (cuando el servicio las
    publica) y geometría de huella en EPSG:4326.
    """
    try:
        root = ET.fromstring(raw)
    except Exception:
        return {}
    edificios: list[dict] = []
    for b in root.iter():
        if not b.tag.endswith('}Building') and b.tag != 'Building':
            continue
        ed: dict[str, Any] = {}
        for elem in b.iter():
            tag = elem.tag.split('}')[-1]
            if tag == 'localId' and 'referencia' not in ed:
                ed['referencia'] = (elem.text or '').strip()
            elif tag == 'currentUse':
                ed['uso'] = (elem.text or '').strip()
            elif tag == 'dateOfConstruction':
                pass  # fecha viene dentro de DateOfEvent/beginning
            elif tag == 'beginning' and 'anio_construccion' not in ed:
                txt = (elem.text or '').strip()[:4]
                anio = _try_int(txt)
                if anio and anio > 1700:
                    ed['anio_construccion'] = anio
            elif tag == 'conditionOfConstruction':
                ed['condicion'] = (elem.text or '').strip()
            elif tag == 'numberOfFloorsAboveGround':
                n = _try_int(elem.text)
                if n:
                    ed['plantas'] = n
            elif tag == 'posList' and 'geometry' not in ed:
                pairs = (elem.text or '').strip().split()
                coords = [[float(pairs[i + 1]), float(pairs[i])]
                          for i in range(0, len(pairs) - 1, 2)]
                if len(coords) >= 4:
                    ed['geometry'] = {
                        'type': 'Polygon', 'coordinates': [coords]}
        if ed.get('referencia') or ed.get('geometry'):
            edificios.append(ed)
    if not edificios:
        return {}
    return {
        'edificios': edificios,
        'num_edificios': len(edificios),
        'fuente': 'Catastro INSPIRE WFS BU',
    }


def obtener_edificios_por_parcela(refcat: str, fetch: Fetch | None = None) -> dict:
    """Edificios oficiales de una parcela (INSPIRE wfsBU GetBuildingByParcel)."""
    fetch = fetch or _default_fetch
    rc = ''.join(ch for ch in (refcat or '') if ch.isalnum()).upper()[:14]
    if len(rc) < 14:
        return {}
    cached = disk_get('catastro', f'bu_{rc}', CAT_TTL_S)
    if cached is not None:
        return cached
    url = (
        f'{WFS_BU_URL}?service=wfs&version=2&request=getfeature'
        f'&STOREDQUERIE_ID=GetBuildingByParcel&refcat={rc}&srsname=EPSG:4326'
    )
    try:
        result = parse_bu_xml(fetch(url))
    except Exception:
        return {}
    if result:
        disk_set('catastro', f'bu_{rc}', result)
    return result


def obtener_plantas_buildingpart(refcat: str,
                                 fetch: Fetch | None = None) -> dict:
    """Plantas oficiales del edificio vía BU.BUILDINGPART.

    El WFS INSPIRE de Catastro no publica ``numberOfFloorsAboveGround``
    en ``bu:Building`` pero sí en ``bu:BuildingPart`` (stored query
    ``GetBuildingPartByParcel``). Devuelve el máximo de plantas sobre
    rasante entre las partes del edificio, los sótanos y el nº de
    partes — ``{}`` si el servicio no tiene la volumetría.
    """
    fetch = fetch or _default_fetch
    rc = ''.join(ch for ch in (refcat or '') if ch.isalnum()).upper()[:14]
    if len(rc) < 14:
        return {}
    cached = disk_get('catastro', f'bup_{rc}', CAT_TTL_S)
    if cached is not None:
        return cached
    url = (
        f'{WFS_BU_URL}?service=wfs&version=2&request=getfeature'
        f'&STOREDQUERIE_ID=GetBuildingPartByParcel&refcat={rc}'
        '&srsname=EPSG:4326'
    )
    try:
        root = ET.fromstring(fetch(url))
    except Exception:
        return {}
    above: list[int] = []
    below: list[int] = []
    for elem in root.iter():
        tag = elem.tag.split('}')[-1]
        if tag == 'numberOfFloorsAboveGround':
            n = _try_int(elem.text)
            if n is not None:
                above.append(n)
        elif tag == 'numberOfFloorsBelowGround':
            n = _try_int(elem.text)
            if n is not None:
                below.append(n)
    if not above:
        return {}
    result = {
        'plantas_sobre_rasante': max(above),
        'sotanos': max(below) if below else 0,
        'partes': len(above),
        'fuente': 'Catastro INSPIRE WFS BU (BuildingPart)',
    }
    disk_set('catastro', f'bup_{rc}', result)
    return result


def obtener_atom_feed_url(codigo_ine: str) -> str:
    """URL del feed ATOM INSPIRE BU para descarga masiva por municipio.

    La descarga puede superar 50 MB; pensada para carga programada en
    ``datos/cache/catastro/``, no para consulta en línea.
    """
    return (
        'https://www.catastro.minhap.es/INSPIRE/buildings/'
        f'{str(codigo_ine)[:2]}/{codigo_ine}/ES.SDGC.BU.atom.xml'
    )


def obtener_edificio_por_coordenadas(lon: float, lat: float,
                                    fetch: Fetch | None = None) -> dict:
    """Datos oficiales del inmueble en unas coordenadas.

    Encadena RCCOOR → DNPRC → parcela INSPIRE → edificios BU.
    Devuelve un dict consolidado con claves planas compatibles con el
    contexto oficial actual.
    """
    fetch = fetch or _default_fetch
    result = obtener_por_coordenadas(lon, lat, fetch=fetch)
    refcat = result.get('refcat')
    if refcat and len(refcat) >= 14:
        for fn in (obtener_detalles_por_ref, obtener_parcela_por_ref,
                   obtener_edificios_por_parcela):
            try:
                extra = fn(refcat, fetch=fetch)
                if extra:
                    result.update(extra)
            except Exception:
                continue
    return result
