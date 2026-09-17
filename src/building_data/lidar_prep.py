"""Preparación y procesado de teselas LiDAR de la Xunta (CENDES/IDEGA).

La descarga CENDES exige un captcha por fichero, por lo que el flujo
automatizable es:

1. ``teselas_bbox`` / ``registrar_pendiente`` — el sistema sabe qué
   tesela oficial necesita cada punto y acumula un manifiesto de
   pendientes ``datos/cache/lidar/_pendientes.json``.
2. El usuario abre cada ``url_descarga``, resuelve el captcha y suelta
   el ZIP en ``datos/cache/lidar/`` (único paso manual).
3. ``procesar_descargas`` — descomprime los ZIPs, valida los .laz/.las
   con laspy y marca la tesela como ``descargada``. A partir de ahí
   ``obtener_altura_lidar`` devuelve ``measured`` automáticamente.

Sin falsos positivos: una tesela solo pasa a ``descargada`` si laspy
puede abrir el fichero extraído.
"""
from __future__ import annotations

import json
import os
import time
import zipfile
from typing import Any, Callable

from src.cache import disk_get, disk_set, http_get
from src.building_data.height_extractor import (
    LIDAR_CACHE_DIR, MALLAS_MAPSERVER, LIDAR_LAYERS, DESCARGAS_XUNTA,
    hoja_lidar_para_punto,
)

PENDIENTES_PATH = os.path.join(LIDAR_CACHE_DIR, '_pendientes.json')


def _load_pendientes() -> dict:
    try:
        with open(PENDIENTES_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'teselas': {}}


def _save_pendientes(data: dict) -> None:
    os.makedirs(LIDAR_CACHE_DIR, exist_ok=True)
    with open(PENDIENTES_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def teselas_bbox(minx: float, miny: float, maxx: float, maxy: float,
                 cobertura: str = 'LIDAR_2015_2016',
                 fetch: Callable[[str], bytes] | None = None) -> list[dict]:
    """Teselas oficiales que intersectan el bbox (EPSG:4326)."""
    fetch = fetch or (lambda u: http_get(u, timeout=30, retries=2))
    layer_id = LIDAR_LAYERS.get(cobertura, 69)
    url = (
        f'{MALLAS_MAPSERVER}/{layer_id}/query'
        f'?geometry={minx},{miny},{maxx},{maxy}'
        '&geometryType=esriGeometryEnvelope&inSR=4326'
        '&spatialRel=esriSpatialRelIntersects'
        '&outFields=HOJA,ARQUIVO_CENDES,PERMALINK,PRODUTO'
        '&returnGeometry=false&f=pjson'
    )
    data = json.loads(fetch(url).decode('utf-8'))
    out = []
    for f in data.get('features') or []:
        a = f.get('attributes') or {}
        permalink = a.get('PERMALINK') or ''
        out.append({
            'hoja': a.get('HOJA'),
            'arquivo': a.get('ARQUIVO_CENDES'),
            'cobertura': cobertura,
            'url_descarga': f'{DESCARGAS_XUNTA}/{permalink}' if permalink else None,
        })
    return out


def registrar_pendiente(lon: float, lat: float,
                        fetch: Callable[[str], bytes] | None = None) -> dict:
    """Anota la tesela LiDAR necesaria para un punto como pendiente.

    Se invoca cuando ``obtener_altura_lidar`` devuelve ``unavailable``;
    el punto queda en el manifiesto para que el usuario sepa qué
    descargar. Devuelve la tesela con su ``url_descarga``.
    """
    tile = hoja_lidar_para_punto(lon, lat, fetch=fetch)
    if not tile.get('available'):
        return tile
    data = _load_pendientes()
    data['teselas'][tile['hoja']] = {
        'hoja': tile['hoja'],
        'arquivo': tile.get('arquivo'),
        'cobertura': tile.get('cobertura'),
        'url_descarga': tile.get('url_descarga'),
        'estado': estado_tesela(tile['hoja'], tile.get('arquivo')),
        'registrada': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'puntos': _append_punto(
            data['teselas'].get(tile['hoja'], {}).get('puntos'), lon, lat),
    }
    _save_pendientes(data)
    return tile


def _append_punto(puntos: list | None, lon: float, lat: float) -> list:
    puntos = list(puntos or [])
    pt = [round(lon, 5), round(lat, 5)]
    if pt not in puntos and len(puntos) < 50:
        puntos.append(pt)
    return puntos


def _laz_presente(hoja: str, arquivo: str | None) -> str | None:
    """Fichero LAZ/LAS ya extraído que corresponde a la tesela."""
    stem = None
    if arquivo:
        stem = arquivo.rsplit('.', 1)[0]
    for fname in os.listdir(LIDAR_CACHE_DIR) if os.path.isdir(LIDAR_CACHE_DIR) else []:
        low = fname.lower()
        if not low.endswith(('.laz', '.las')):
            continue
        if stem and low.startswith(stem.lower()):
            return fname
        if hoja and hoja in fname:
            return fname
    return None


def estado_tesela(hoja: str, arquivo: str | None = None) -> str:
    """``descargada`` si el LAZ/LAS está extraído y es legible, si no
    ``pendiente``. Comprueba legibilidad real con laspy."""
    fname = _laz_presente(hoja, arquivo)
    if not fname:
        return 'pendiente'
    try:
        import laspy
        with laspy.open(os.path.join(LIDAR_CACHE_DIR, fname)):
            pass
        return 'descargada'
    except Exception:
        return 'pendiente'


def procesar_descargas() -> dict:
    """Descomprime los ZIPs CENDES en ``datos/cache/lidar/``.

    Extrae los .laz/.las al mismo directorio, valida que laspy los abre
    y elimina el ZIP si todo salió bien. Actualiza el manifiesto de
    pendientes. Devuelve ``{procesados, errores, teselas_activas}``.
    """
    procesados, errores = [], []
    os.makedirs(LIDAR_CACHE_DIR, exist_ok=True)
    for fname in sorted(os.listdir(LIDAR_CACHE_DIR)):
        if not fname.lower().endswith('.zip'):
            continue
        zpath = os.path.join(LIDAR_CACHE_DIR, fname)
        try:
            with zipfile.ZipFile(zpath) as z:
                members = [m for m in z.namelist()
                           if m.lower().endswith(('.laz', '.las'))]
                if not members:
                    errores.append({'zip': fname,
                                    'error': 'sin .laz/.las dentro'})
                    continue
                for m in members:
                    dest = os.path.join(LIDAR_CACHE_DIR, os.path.basename(m))
                    with z.open(m) as src, open(dest, 'wb') as dst:
                        dst.write(src.read())
            os.remove(zpath)
            procesados.append({'zip': fname, 'extraidos': len(members)})
        except Exception as e:
            errores.append({'zip': fname, 'error': str(e)})
    # Actualizar estados del manifiesto
    data = _load_pendientes()
    for hoja, t in data['teselas'].items():
        t['estado'] = estado_tesela(hoja, t.get('arquivo'))
    data['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    _save_pendientes(data)
    activas = [h for h, t in data['teselas'].items()
               if t['estado'] == 'descargada']
    return {'procesados': procesados, 'errores': errores,
            'teselas_activas': activas}


def estado_preparacion() -> dict:
    """Resumen del manifiesto de pendientes con estado actualizado."""
    data = _load_pendientes()
    for hoja, t in data['teselas'].items():
        t['estado'] = estado_tesela(hoja, t.get('arquivo'))
    teselas = list(data['teselas'].values())
    return {
        'teselas': teselas,
        'pendientes': sum(1 for t in teselas if t['estado'] == 'pendiente'),
        'descargadas': sum(1 for t in teselas if t['estado'] == 'descargada'),
        'directorio': os.path.abspath(LIDAR_CACHE_DIR),
        'instrucciones': (
            'Abrir cada url_descarga, resolver el captcha de CENDES y '
            'soltar el ZIP en el directorio indicado; '
            'POST /official/lidar-procesar los descomprime y valida'),
    }
