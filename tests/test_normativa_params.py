"""Tests del extractor de parámetros normativos (src/normativa_params.py)."""
from src import normativa_params as np


_U6_TEXT = """ART. 80. ORDENANZA U6. VIVENDA UNIFAMILIAR
a) Establécense uns recuados laterais mínimos de 2,00 metros aos lindes
laterais e de 3,00 metros ao linde posterior.
• A edificación principal poderase situar na aliñación ou recuarse con
respecto a ela un máximo de 3,00 metros.
Para efectos de nova parcelación establécense unha parcela mínima de
250 m2. Para efectos de parcelación unha parcela mínima de 500 m2 e
unha edificabilidade de 0,50 m2/m2.
A edificabilidade máxima establécese en 0,70 m2/m2 cunha ocupación
máxima do 40% a aplicar para a totalidade das plantas.
• A altura máxima fíxase en baixo e unha planta, equivalente a 7,00
metros medidos conforme ao establecido no artigo 62.5 desta Norma.
"""

_SRPP_TEXT = """ORDENANZA SRPP. SOLO RÚSTICO DE ESPECIAL PROTECCIÓN PATRIMONIAL
autorizándose o peto cego perimetral de protección e altura máxima
1,10 metros. O aproveitamento así definido poderá destinarse a uso de vivenda.
"""


def _block(texto, pag=1, ord_code='U6'):
    return {'ordenanza': ord_code, 'titulo': 'X', 'pag_ini': pag, 'texto': texto}


def test_u6_edificabilidad_maxima_no_confunde_parcelacion():
    """La edificabilidad de parcelación (0,50) no debe ganar a la máxima (0,70)."""
    params, trazas = np._extract_params(_block(_U6_TEXT, pag=179))
    assert params['edificabilidad_max_m2_m2'] == 0.7
    assert params['ocupacion_max_pct'] == 40.0
    assert params['retranqueo_lateral_m'] == 2.0
    assert params['retranqueo_posterior_m'] == 3.0
    assert params['retranqueo_frontal_m'] == 3.0
    assert params['altura_maxima_m'] == 7.0
    assert params['parcela_minima_m2'] == 250.0


def test_trazas_incluyen_pagina_y_texto():
    params, trazas = np._extract_params(_block(_U6_TEXT, pag=179))
    tr = trazas['edificabilidad_max_m2_m2']
    assert tr['pagina'] == 179
    assert '0,70' in tr['texto']


def test_altura_de_peto_no_es_altura_de_edificio():
    """'peto cego perimetral de protección e altura máxima 1,10 metros' no es
    la altura máxima de la ordenanza."""
    params, _ = np._extract_params(_block(_SRPP_TEXT, ord_code='SRPP'))
    assert 'altura_maxima_m' not in params


def test_segment_ordenanzas_corta_por_cabeceras():
    pages = [
        "intro\nART. 76. ORDENANZA U1. MANTEMENTO\ntexto u1 " + "a" * 50,
        "más u1\nORDENANZA U2. CUARTEIRÓN\ntexto u2 " + "b" * 50,
    ]
    blocks = np._segment_ordenanzas(pages)
    codes = [b['ordenanza'] for b in blocks]
    assert 'U1' in codes and 'U2' in codes
    u1 = next(b for b in blocks if b['ordenanza'] == 'U1')
    assert u1['pag_ini'] == 1
    assert 'texto u1' in u1['texto'] and 'más u1' in u1['texto']


def test_buscar_ordenanza_normaliza_codigos():
    ords = {'U6': {'ordenanza': 'U6', 'params': {'x': 1}},
            'U10': {'ordenanza': 'U10', 'params': {}}}
    key, found = np.buscar_ordenanza(ords, 'u.6')
    assert key == 'U6' and found['params'] == {'x': 1}
    key, found = np.buscar_ordenanza(ords, 'U10')
    assert key == 'U10'
    key, found = np.buscar_ordenanza(ords, 'RZ-9')
    assert key is None and found is None


def test_parametros_subzona_estructura(monkeypatch, tmp_path):
    fake = {'U6': {'ordenanza': 'U6', 'titulo': 'VIVENDA UNIFAMILIAR',
                   'params': {'ocupacion_max_pct': 40.0}, 'trazas': {},
                   'fuente': 'x.pdf pág. 179'}}
    monkeypatch.setattr(np, 'extraer_ordenanzas_municipio', lambda ine: fake)
    res = np.parametros_subzona('36057', 'U6')
    assert res['data_quality'] == 'official'
    assert res['params']['ocupacion_max_pct'] == 40.0
    res2 = np.parametros_subzona('36057')
    assert 'U6' in res2['ordenanzas']


def test_parametros_subzona_sin_datos(monkeypatch):
    monkeypatch.setattr(np, 'extraer_ordenanzas_municipio', lambda ine: {})
    res = np.parametros_subzona('99999')
    assert res['available'] is False
    assert res['data_quality'] == 'unavailable'
    assert 'nota' in res
