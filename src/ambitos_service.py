"""Índice de ámbitos de planeamiento municipal (API / SUB / SUNC / PE).

Carga ``datos/normativa/{ine}/ambitos.json`` — generado por
``scripts/extract_vigo_ambitos.py`` desde los PDFs oficiales del
planeamiento (SIOTUGA) — y resuelve:

- ``get_ambito(ine, codigo)`` → ficha/ámbito oficial o ``None``.
- ``detectar_codigo_en_texto(texto)`` → código normalizado si la
  pregunta del usuario lo menciona («API-106», «api 106», «SUNC 201»).
- ``detectar_ambito_en_clasificacion(clasificacion)`` → código desde
  los atributos oficiales del polígono SIOTUGA (``observaciones_zona``
  lleva «API-106»; ``denominacion_zona`` lleva «201 Guixar-Santa
  Tegra» cuyo número inicial es el código de la ficha del anexo).

Todo lo devuelto es ``data_quality: official`` con página y fichero
fuente; lo que no está indexado se declara ``unavailable`` — nunca se
inventa un ámbito ni sus parámetros.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

_CACHE: dict[str, tuple[float, dict | None]] = {}
_TTL_S = 600

_AMBITO_RE = re.compile(
    r'\b(API|SUB|SUNC|SUNP|SUOC|PE)[-\s]?(\d{1,4}[a-zA-Z]?)'
    r'(?:[_\-\s]P[-\s]?\d+)?\b', re.I)

# denominacion_zona «201 Guixar-Santa Tegra» → SUNC-201 solo cuando la
# clase del polígono es de ámbito de desarrollo (el número inicial es
# el código del ámbito). En SUC el número es un código de zona/dotación
# y no corresponde a ninguna ficha.
_CATS_AMBITO = {'SUB', 'SUNC', 'SUNP', 'SUOC'}

_DENOM_NUM_RE = re.compile(r'^\s*(\d{1,4}[a-z]?)\s+')


def _path(ine: str) -> str:
    return os.path.join('datos', 'normativa', str(ine), 'ambitos.json')


def cargar_ambitos(ine: str | None) -> dict | None:
    """Lee el índice del municipio (cacheado en memoria, TTL 10 min)."""
    if not ine:
        return None
    now = time.time()
    hit = _CACHE.get(ine)
    if hit and now - hit[0] < _TTL_S:
        return hit[1]
    data = None
    try:
        with open(_path(ine), encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = None
    _CACHE[ine] = (now, data)
    return data


def normalizar_codigo(raw: str | None) -> str | None:
    """«api 106» → «API-106»; «API-201_P-8» → «API-201»;
    «sunc 702a» → «SUNC-702A»."""
    if not raw:
        return None
    m = _AMBITO_RE.search(raw)
    if not m:
        return None
    return f"{m.group(1).upper()}-{m.group(2).upper()}"


def detectar_codigo_en_texto(texto: str | None) -> str | None:
    return normalizar_codigo(texto)


def _variantes(code: str) -> list[str]:
    """«SUNC-702A» → [SUNC-702A, SUNC-702, SUNC-702a] (el índice puede
    llevar el número sin letra o la letra en minúscula)."""
    out = [code]
    m = re.match(r'(.*-)(\d+)([A-Z])$', code)
    if m:
        out += [m.group(1) + m.group(2),
                m.group(1) + m.group(2) + m.group(3).lower()]
    return out


def get_ambito(ine: str | None, codigo: str | None) -> dict | None:
    """Entrada oficial del ámbito (API o ficha SUB/SUNC/PE)."""
    idx = cargar_ambitos(ine)
    if not idx:
        return None
    code = normalizar_codigo(codigo)
    if not code:
        return None
    apis = idx.get('apis') or {}
    fichas = idx.get('fichas') or {}
    for cand in _variantes(code):
        if cand in apis:
            code = cand
            break
        if cand in fichas:
            code = cand
            break
    if code in apis:
        out = dict(idx['apis'][code])
        out['tipo'] = 'api'
        out['data_quality'] = 'official'
        out['fuente'] = (f"{(idx.get('fuentes') or {}).get('apis')}"
                         f" — pág. PDF {out.get('pagina')}")
        return out
    if code in fichas:
        out = dict(idx['fichas'][code])
        out['tipo'] = 'ficha'
        out['data_quality'] = 'official'
        out['fuente'] = (f"{(idx.get('fuentes') or {}).get('fichas')}"
                         f" — pág. PDF {out.get('pagina_inicio')}")
        return out
    return None


def detectar_ambito_en_clasificacion(clas: dict | None) -> dict | None:
    """Detecta el ámbito desde atributos oficiales del polígono.

    Devuelve ``{codigo, origen, confianza}`` o ``None``. La presencia
    del código en ``obsv``/``denom`` es evidencia oficial del ámbito;
    la confianza refleja lo literal del dato (no la geometría — el
    punto ya está dentro del polígono que porta el atributo).
    """
    clas = clas or {}
    obsv = str(clas.get('observaciones_zona') or '')
    m = _AMBITO_RE.search(obsv)
    if m and m.group(1).upper() == 'API':
        sufijo = bool(re.search(r'[_\-\s]P[-\s]?\d+', m.group(0), re.I))
        return {'codigo': f"API-{m.group(2).upper()}",
                'origen': 'observaciones_zona (obsv) oficial SIOTUGA',
                'confianza': 'media' if sufijo else 'alta'}
    denom = str(clas.get('denominacion_zona') or '')
    m = _AMBITO_RE.search(denom)
    if m:
        return {'codigo': f"{m.group(1).upper()}-{m.group(2).upper()}",
                'origen': 'denominacion_zona oficial SIOTUGA',
                'confianza': 'alta'}
    cat = str(clas.get('clasificacion_plan')
              or clas.get('clasificacion_ley') or '').upper()
    if cat in _CATS_AMBITO:
        nm = _DENOM_NUM_RE.match(denom)
        if nm:
            return {'codigo': f"{cat}-{nm.group(1).upper()}",
                    'origen': 'denominacion_zona + clasificacion_plan '
                              'oficiales SIOTUGA',
                    'confianza': 'alta'}
    return None


_TREE_CACHE: dict[str, tuple[float, Any]] = {}
_TREE_TTL_S = 3600


def _ambito_tree(ine: str):
    """STRtree de los polígonos 3CLAS cacheados que portan un código
    de ámbito (obsv «API-n» o denom numerado en SUB/SUNC/SUNP).

    Solo se indexan los features candidatos (~200 en Vigo de los
    ~3.500 de la capa) — basta un punto-en-polígono barato por
    edificio para etiquetarlo sin recorrer toda la capa.
    """
    if not cargar_ambitos(ine):
        return None
    hit = _TREE_CACHE.get(ine)
    if hit and time.time() - hit[0] < _TREE_TTL_S:
        return hit[1]
    tree = None
    try:
        from shapely.geometry import shape
        from shapely.strtree import STRtree
        from src.siotuga.vector_downloader import capa_cacheada
        fc = capa_cacheada(ine)
        feats = []
        geoms = []
        for f in (fc or {}).get('features') or []:
            p = f.get('properties') or {}
            obsv = str(p.get('obsv') or '')
            cat = str(p.get('cat_plan') or p.get('cat_ley') or ''
                        ).upper()
            denom = str(p.get('denom') or '')
            es_api = bool(re.search(r'API[-\s]?\d+', obsv, re.I)) \
                or bool(re.search(r'API[-\s]?\d+', denom, re.I))
            es_ambito = cat in _CATS_AMBITO and \
                bool(_DENOM_NUM_RE.match(denom))
            if not (es_api or es_ambito):
                continue
            try:
                geoms.append(shape(f['geometry']))
                feats.append(p)
            except Exception:
                continue
        if geoms:
            tree = (STRtree(geoms), geoms, feats)
    except Exception:
        tree = None
    _TREE_CACHE[ine] = (time.time(), tree)
    return tree


def ambito_en_punto(lon: float, lat: float,
                    ine: str | None) -> dict | None:
    """Ámbito de planeamiento oficial que contiene el punto.

    Devuelve la entrada del índice (API o ficha) + ``origen`` de la
    evidencia espacial, o ``None`` si el punto no cae en un ámbito
    o el municipio no tiene capa/índice cacheados.
    """
    if not ine:
        return None
    data = _ambito_tree(ine)
    if not data:
        return None
    tree, geoms, feats = data
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        for i in tree.query(pt):
            if not geoms[int(i)].contains(pt):
                continue
            p = feats[int(i)]
            det = detectar_ambito_en_clasificacion({
                'observaciones_zona': p.get('obsv'),
                'denominacion_zona': p.get('denom'),
                'clasificacion_plan': p.get('cat_plan'),
                'clasificacion_ley': p.get('cat_ley')})
            if not det:
                continue
            amb = get_ambito(ine, det['codigo'])
            if amb:
                amb['origen_espacial'] = (
                    f"punto dentro do polígono 3CLAS "
                    f"{p.get('id_recinto') or ''} "
                    f"({det['origen']})".strip())
                return amb
            return {'codigo': det['codigo'], 'tipo': 'detectado',
                    'data_quality': 'unavailable',
                    'origen_espacial': det['origen'],
                    'error': 'ámbito detectado pero ficha non '
                             'indexada'}
    except Exception:
        return None
    return None


# ------------------------------------------------------------------
# Ámbitos oficiales del PXOM vía ArcGIS FeatureServer del Concello
#
# El GeoServer municipal no publica las ordenanzas del PXOM 2025
# definitivo, pero el portal ArcGIS del Concello (vigo.maps.arcgis.com)
# sí sirve como Feature Services públicos las capas de ámbitos de la
# aprobación definitiva: 5APR (ámbitos con figura: PEP/PERI/PP/PLS…)
# y 7API (ámbitos de planeamiento incorporado). Cubren los huecos de
# ``4ordsuc`` donde la zona se rige por instrumento propio.
# ------------------------------------------------------------------
_ARCGIS_AMBITOS = {
    '36057': {
        'base': ('https://services9.arcgis.com/ss3qikvq575kYKRJ'
                 '/arcgis/rest/services'),
        'capas': {
            'ambitos': ['36057_PXOM_202502_AD01_5APR',
                        '36057_PXOM_202502_AD01_7API'],
            # Ordenanzas SUC de la aprobación definitiva PXOM 2025 —
            # más autoritativa y completa que la WFS municipal 2021.
            'ord2025': ['36057_PXOM_202502_AD01_4ORDSUC_nome'],
            # Dotaciones (equipamentos, zonas verdes…) — explican los
            # huecos sin ordenanza: una parcela dotacional no lleva
            # ordenanza residencial, se rige por su ficha de sistema.
            'dotaciones': ['36057_PXOM_202502_AD01_2DOTPOL_descri'],
            # Contornos arqueolóxicos del catálogo — afección.
            'arqueoloxia': ['36057_PXOM_202502_AD01_CAT_CONTORNO_ARQLX'],
        },
    },
}
_ARCGIS_TTL_S = 30 * 24 * 3600
_ARCGIS_FEATS: dict[str, list[dict]] = {}
_ARCGIS_TREE: dict[str, tuple] = {}


def _arcgis_cache_path(ine: str, svc: str):
    from pathlib import Path
    return Path('datos/cache/arcgis_ambitos') / f'{ine}_{svc}.geojson'


def _arcgis_download(base: str, svc: str) -> dict | None:
    """Descarga paginada de una capa FeatureServer como GeoJSON —
    ``maxRecordCount`` (2000) exige ``resultOffset`` para capas
    grandes como 4ORDSUC (~5.300 polígonos)."""
    import requests
    feats: list[dict] = []
    offset = 0
    while True:
        r = requests.get(
            f"{base}/{svc}/FeatureServer/0/query",
            params={'where': '1=1', 'outFields': '*', 'f': 'geojson',
                    'outSR': '4326', 'resultRecordCount': '2000',
                    'resultOffset': str(offset)},
            timeout=90)
        page = (r.json() or {}).get('features') or []
        feats.extend(page)
        if len(page) < 2000:
            break
        offset += len(page)
        if offset > 100000:
            break
    return {'type': 'FeatureCollection', 'features': feats} if feats \
        else None


def _arcgis_features(ine: str | None,
                     grupo: str = 'ambitos') -> list[dict]:
    """Features de un grupo de capas del PXOM (ArcGIS Concello),
    cacheadas en disco 30 días. ``[]`` si el municipio no tiene el
    grupo configurado o el servicio falla."""
    cfg = _ARCGIS_AMBITOS.get(str(ine or ''))
    if not cfg:
        return []
    capas = (cfg.get('capas') or {}).get(grupo) or []
    key = f'{ine}:{grupo}'
    if key in _ARCGIS_FEATS:
        return _ARCGIS_FEATS[key]
    feats: list[dict] = []
    for svc in capas:
        path = _arcgis_cache_path(str(ine), svc)
        data = None
        if path.exists() and \
                (time.time() - path.stat().st_mtime) < _ARCGIS_TTL_S:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                data = None
        if data is None:
            try:
                data = _arcgis_download(cfg['base'], svc)
                if data and data.get('features'):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(data), encoding='utf-8')
            except Exception:
                continue
        for f in (data or {}).get('features') or []:
            if f.get('geometry'):
                (f.setdefault('properties', {}))['_svc'] = svc
                feats.append(f)
    _ARCGIS_FEATS[key] = feats
    return feats


def _arcgis_tree(ine: str, feats: list[dict],
                 grupo: str = 'ambitos'):
    key = f'{ine}:{grupo}'
    hit = _ARCGIS_TREE.get(key)
    if hit and hit[0] is feats:
        return hit[1], hit[2], hit[3]
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    geoms, kept = [], []
    for f in feats:
        try:
            geoms.append(shape(f['geometry']))
            kept.append(f)
        except Exception:
            continue
    tree = STRtree(geoms) if geoms else None
    _ARCGIS_TREE[key] = (feats, tree, geoms, kept)
    return tree, geoms, kept


def _arcgis_poligonos_en_punto(lon: float, lat: float, ine: str | None,
                             grupo: str) -> list[dict]:
    """Properties de los polígonos del grupo que contienen el punto."""
    feats = _arcgis_features(ine, grupo)
    if not feats:
        return []
    tree, geoms, kept = _arcgis_tree(str(ine), feats, grupo)
    if tree is None:
        return []
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        return [kept[int(i)].get('properties') or {}
                for i in tree.query(pt) if geoms[int(i)].contains(pt)]
    except Exception:
        return []


def ambito_oficial_en_punto(lon: float, lat: float,
                            ine: str | None) -> dict | None:
    """Ámbito oficial del PXOM (ArcGIS FeatureServer del Concello) que
    contiene el punto — cubre los huecos de la capa de ordenanzas
    generales donde la zona se rige por instrumento propio (PEP, PERI,
    PP, API…). ``None`` si no hay capa o el punto cae fuera."""
    for p in _arcgis_poligonos_en_punto(lon, lat, ine, 'ambitos'):
        figura = str(p.get('figura') or '').strip().upper()
        cod = str(p.get('cod') or '').strip()
        if not cod:
            continue
        codigo = f'{figura}-{cod}' if figura else f'API-{cod}'
        return {
            'codigo': codigo,
            'tipo': 'ambito',
            'tipo_instrumento': figura or 'API',
            'instrumento': str(p.get('nome') or '').strip(),
            'figura': figura or 'API',
            'cat': p.get('cat'),
            'edificabilidad': p.get('edif'),
            'sup_m2': p.get('sup'),
            'enl_ficha': p.get('enl_ficha'),
            'observ': p.get('observ'),
            'data_quality': 'official',
            'fuente': ('ArcGIS Concello de Vigo — PXOM 2025 '
                       'aprobación definitiva'),
            'capa': p.get('_svc'),
        }
    return None


def ordenanza_2025_en_punto(lon: float, lat: float,
                            ine: str | None) -> dict | None:
    """Ordenanza SUC del PXOM 2025 definitivo (capa ArcGIS
    ``4ORDSUC_nome``) que contiene el punto. Devuelve el código,
    nombre y parámetros declarados en la capa — ``None`` si el punto
    cae fuera de su cobertura (ámbito propio, dotación o viario)."""
    hits = [p for p in _arcgis_poligonos_en_punto(lon, lat, ine,
                                                'ord2025')
            if str(p.get('ordenanza') or '').strip()]
    if not hits:
        return None
    p = hits[0]
    return {
        'ordenanza': str(p.get('ordenanza')).strip(),
        'candidatas': sorted({str(h.get('ordenanza')).strip()
                              for h in hits}),
        'ambigua': len({str(h.get('ordenanza')).strip()
                        for h in hits}) > 1,
        'nome': str(p.get('nome') or '').strip(),
        'altura': str(p.get('altura') or '').strip(),
        'observ': str(p.get('observ') or '').strip(),
        'fondo': str(p.get('fondo') or '').strip(),
        'sup_m2': p.get('sup'),
        'data_quality': 'official',
        'fuente': ('ArcGIS Concello de Vigo — PXOM 2025 '
                   'aprobación definitiva'),
        'capa': p.get('_svc'),
    }


def ordenanzas_2025_proximas(lon: float, lat: float, ine: str | None,
                             radio_m: float = 250.0) -> list[dict]:
    """Códigos de ordenanza de la capa definitiva 2025 más cercanos al
    punto (para huecos: dotaciones, viario, ámbitos). Orientativos."""
    feats = _arcgis_features(ine, 'ord2025')
    if not feats:
        return []
    tree, geoms, kept = _arcgis_tree(str(ine), feats, 'ord2025')
    if tree is None:
        return []
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)
        idx = tree.query(pt.buffer(radio_m / 111320.0))
        cand = sorted((geoms[int(i)].distance(pt) * 111320.0,
                       str((kept[int(i)].get('properties') or {})
                           .get('ordenanza') or '').strip())
                      for i in idx)
        out: list[dict] = []
        for d, code in cand:
            if d > radio_m:
                break
            if code and all(c['ordenanza'] != code for c in out):
                out.append({'ordenanza': code, 'distancia_m': round(d)})
            if len(out) >= 6:
                break
        return out
    except Exception:
        return []


def dotacion_en_punto(lon: float, lat: float,
                      ine: str | None) -> dict | None:
    """Dotación oficial del PXOM 2025 (capa ``2DOTPOL``) que contiene
    el punto — sistemas de equipamentos, zonas verdes, etc. Una
    parcela dotacional explica por qué no lleva ordenanza residencial:
    se rige por la ficha de su sistema."""
    hits = _arcgis_poligonos_en_punto(lon, lat, ine, 'dotaciones')
    if not hits:
        return None
    # Preferir la feature más específica (tipo distinto de 'na')
    hits.sort(key=lambda p: str(p.get('tipo') or '') in ('', 'na'))
    p = hits[0]
    tipo = str(p.get('tipo_desc') or '').strip()
    sistema = str(p.get('sistema_de') or '').strip()
    pb_pv = str(p.get('pb_pv_desc') or '').strip()
    ex_ob = {'Ex': 'existente', 'Ob': 'en ordenación',
             'Pr': 'programado'}.get(str(p.get('ex_ob') or '').strip(),
                                     str(p.get('ex_ob') or '').strip())
    return {
        'sistema': sistema or None,
        'tipo': tipo if tipo.lower() != 'na' else None,
        'titularidade': pb_pv if pb_pv.lower() != 'na' else None,
        'estado': ex_ob or None,
        'sup_m2': p.get('sup'),
        'data_quality': 'official',
        'fuente': ('ArcGIS Concello de Vigo — PXOM 2025 '
                   'aprobación definitiva'),
        'capa': p.get('_svc'),
    }


def afeccion_arqueoloxica_en_punto(lon: float, lat: float,
                                   ine: str | None) -> dict | None:
    """Contorno arqueolóxico del catálogo PXOM 2025 que contiene el
    punto — devuelve los códigos OPSA afectados o ``None``."""
    codigos = sorted({
        str(p.get('cod_opsa') or '').strip()
        for p in _arcgis_poligonos_en_punto(lon, lat, ine, 'arqueoloxia')
    } - {''})
    if not codigos:
        return None
    return {
        'codigos': codigos,
        'data_quality': 'official',
        'fuente': ('ArcGIS Concello de Vigo — PXOM 2025 '
                   'aprobación definitiva'),
        'capa': '36057_PXOM_202502_AD01_CAT_CONTORNO_ARQLX',
    }
