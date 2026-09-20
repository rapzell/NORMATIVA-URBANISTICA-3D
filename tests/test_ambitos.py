"""Tests del índice de ámbitos de planeamiento (API / SUB / SUNC / PE).

Datos: ``datos/normativa/36057/ambitos.json`` (generado por
``scripts/extract_vigo_ambitos.py`` desde los PDFs oficiales del PXOM
2025 de Vigo) y la copia local 3CLAS en ``datos/cache/siotuga/``.
"""
import os

import pytest

from src.ambitos_service import (ambito_en_punto, cargar_ambitos,
                                 detectar_ambito_en_clasificacion,
                                 detectar_codigo_en_texto, get_ambito,
                                 normalizar_codigo)

INE = '36057'

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join('datos', 'normativa', INE,
                                    'ambitos.json')),
    reason='índice de ámbitos no generado '
           '(scripts/extract_vigo_ambitos.py)')


# ---------- normalización ----------

@pytest.mark.parametrize('raw,esperado', [
    ('API-106', 'API-106'),
    ('api 106', 'API-106'),
    ('api106', 'API-106'),
    ('SUNC-201', 'SUNC-201'),
    ('sunc201', 'SUNC-201'),
    ('API-201_P-8', 'API-201'),
    ('sunc 702a', 'SUNC-702A'),
])
def test_normalizar_codigo(raw, esperado):
    assert normalizar_codigo(raw) == esperado


def test_normalizar_codigo_invalido():
    assert normalizar_codigo('vivienda unifamiliar') is None
    assert normalizar_codigo('') is None
    assert normalizar_codigo(None) is None


def test_detectar_codigo_en_texto():
    assert detectar_codigo_en_texto(
        '¿qué altura permite la parcela en API-106?') == 'API-106'


# ---------- lookup ----------

def test_get_ambito_api106():
    amb = get_ambito(INE, 'API-106')
    assert amb is not None
    assert amb['tipo'] == 'api'
    assert amb['data_quality'] == 'official'
    assert 'ROSALIA' in (amb.get('instrumento') or '').upper()
    assert amb.get('pagina')


def test_get_ambito_ficha_sunc():
    amb = get_ambito(INE, 'sunc201')
    assert amb is not None
    assert amb['tipo'] == 'ficha'
    assert amb['data_quality'] == 'official'
    assert 'GUIXAR' in (amb.get('denominacion') or '').upper()
    params = amb.get('parametros') or {}
    assert params  # la ficha trae parámetros estructurados


def test_get_ambito_inexistente():
    assert get_ambito(INE, 'API-999') is None


def test_get_ambito_sin_indice():
    assert get_ambito('99999', 'API-1') is None


# ---------- detección por atributos oficiales ----------

def test_detectar_obsv_api():
    det = detectar_ambito_en_clasificacion(
        {'clasificacion_plan': 'SUC', 'observaciones_zona': 'API-106'})
    assert det and det['codigo'] == 'API-106'
    assert det['confianza'] == 'alta'


def test_detectar_obsv_api_sufijo():
    det = detectar_ambito_en_clasificacion(
        {'observaciones_zona': 'API-201_P-8'})
    assert det and det['codigo'] == 'API-201'
    assert det['confianza'] == 'media'


def test_detectar_denom_api():
    det = detectar_ambito_en_clasificacion(
        {'denominacion_zona': 'API-601 MP SUNP PAU 4 NAVIA'})
    assert det and det['codigo'] == 'API-601'


def test_detectar_denom_numerico_sunc():
    det = detectar_ambito_en_clasificacion(
        {'clasificacion_plan': 'SUNC',
         'denominacion_zona': '201 Guixar-Santa Tegra'})
    assert det and det['codigo'] == 'SUNC-201'


def test_detectar_suc_sin_ambito():
    # En SUC el número de denom es un código de zona, no de ámbito.
    det = detectar_ambito_en_clasificacion(
        {'clasificacion_plan': 'SUC',
         'denominacion_zona': '12 zona verde'})
    assert det is None


def test_detectar_vacio():
    assert detectar_ambito_en_clasificacion({}) is None
    assert detectar_ambito_en_clasificacion(None) is None


# ---------- lookup espacial (capa 3CLAS local) ----------

def _capa_local():
    from src.siotuga.vector_downloader import capa_cacheada
    return capa_cacheada(INE)


def test_ambito_en_punto_api106():
    if not _capa_local():
        pytest.skip('capa 3CLAS de Vigo no cacheada')
    amb = ambito_en_punto(-8.72598, 42.22719, INE)
    assert amb is not None
    assert amb['codigo'] == 'API-106'
    assert amb['data_quality'] == 'official'
    assert amb.get('origen_espacial')


def test_ambito_en_punto_ru_couto_sin_ambito():
    """RU COUTO 2 (-8.7221, 42.2304) no cae en ningún polígono de
    ámbito de la capa oficial — debe devolver None, nunca el ámbito
    más cercano."""
    if not _capa_local():
        pytest.skip('capa 3CLAS de Vigo no cacheada')
    assert ambito_en_punto(-8.7221049, 42.2303856, INE) is None


def test_ambito_en_punto_sin_ine():
    assert ambito_en_punto(-8.72598, 42.22719, None) is None


# ---------- resolutor de ordenanza ----------

def _ctx_base():
    return {
        'municipio': 'Vigo', 'ine': INE,
        'ordenanzas': {'ordenanzas': {
            'U4': {'titulo': 'ORDENANZA U4',
                   'params': {'altura_maxima_m': 7}},
            'U6': {'titulo': 'ORDENANZA U6', 'params': {}},
        }},
    }


def test_resolver_api106():
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_base()
    ctx['clasificacion'] = {'clasificacion_plan': 'SUC',
                            'observaciones_zona': 'API-106'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'oficial'
    assert r['ordenanza'] is None
    assert (r.get('ambito') or {}).get('codigo') == 'API-106'
    assert 'instrumento' in r['nota'] or 'instrumento' in str(r)


def test_resolver_seleccion_manual_no_pisa_ambito():
    """Si la parcela está en API-106 y el usuario indica «U6», el
    ámbito oficial prevalece y se informa de la discrepancia."""
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_base()
    ctx['clasificacion'] = {'clasificacion_plan': 'SUC',
                            'observaciones_zona': 'API-106'}
    ctx['subzona'] = 'U6'
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'oficial'
    assert (r.get('ambito') or {}).get('codigo') == 'API-106'
    assert 'U6' in (r.get('nota') or '')


def test_resolver_sunc201_ficha():
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_base()
    ctx['clasificacion'] = {'clasificacion_plan': 'SUNC',
                            'denominacion_zona': '201 Guixar-Santa Tegra'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'oficial'
    amb = r.get('ambito') or {}
    assert amb.get('codigo') == 'SUNC-201'
    assert amb.get('tipo') == 'ficha'


def test_resolver_ambito_eliminado():
    from src.agent.ordinance_resolver import resolver_ordenanza
    idx = cargar_ambitos(INE)
    eliminadas = [c for c, a in (idx.get('apis') or {}).items()
                  if a.get('estado_ambito') == 'eliminada']
    if not eliminadas:
        pytest.skip('sin API eliminadas en el índice')
    ctx = _ctx_base()
    ctx['clasificacion'] = {'clasificacion_plan': 'SUC',
                            'observaciones_zona': eliminadas[0]}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'no_resuelta'
    assert 'eliminad' in (r.get('nota') or '').lower()


def test_resolver_sin_ambito_ni_wfs():
    """Sin ámbito ni cobertura WFS → no_resuelta honesta, nunca el
    polígono más cercano."""
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_base()
    ctx['clasificacion'] = {'clasificacion_plan': 'SUC'}
    ctx['ordenanza_wfs'] = {'data_quality': 'unavailable',
                            'error': 'Punto fuera de la capa'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'no_resuelta'
    assert r['ordenanza'] is None


def test_resolver_ambito_input_hint():
    """El hint de contexto (ambito codificado por el edificio)
    resuelve el ámbito aunque la clasificación no lo traiga."""
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_base()
    ctx['clasificacion'] = {'clasificacion_plan': 'SUC'}
    ctx['ambito_input'] = 'API-106'
    ctx['ordenanza_wfs'] = {'data_quality': 'unavailable',
                            'error': 'Punto fuera de la capa'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'oficial'
    assert (r.get('ambito') or {}).get('codigo') == 'API-106'


# ---------- herramienta del agente ----------

def test_tool_get_ambito_ficha():
    from src.agent.tools import get_ambito_ficha
    r = get_ambito_ficha('API-106', ine=INE)
    assert r.get('data_quality') == 'official'
    assert r.get('codigo') == 'API-106'


def test_tool_get_ambito_ficha_inexistente():
    from src.agent.tools import get_ambito_ficha
    r = get_ambito_ficha('API-999', ine=INE)
    assert r.get('data_quality') == 'unavailable' or r.get('error')
