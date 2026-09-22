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

_U6_ABS_TEXT = """ART. 80. ORDENANZA U6. VIVENDA UNIFAMILIAR
• A altura máxima fíxase en baixo e unha planta, equivalente a 7,00
metros medidos conforme ao establecido no artigo 62.5 desta Normativa,
sen superar os 8,50 metros medidos desde calquera punto do terreo.
• Non se autorizan voos sobre as aliñacións oficiais. Autorízase o
aproveitamento baixocuberta por riba da altura máxima segundo o
establecido no art. 62.6 da presente Normativa.
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


def test_u6_tope_absoluto_desde_calquera_punto():
    """U6 fija 7 m a cornisa (art. 62.5) + tope absoluto de 8,5 m desde
    cualquier punto del terreno: ambos valores deben extraerse."""
    params, trazas = np._extract_params(_block(_U6_ABS_TEXT, pag=180))
    assert params['altura_maxima_m'] == 7.0
    assert params['altura_absoluta_m'] == 8.5
    assert 'calquera punto' in trazas['altura_absoluta_m']['texto']


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


_U2_TEXT = """ART . 77. ORDENANZA U2. CUARTEIRÓN PECHADO.
1.  Delimitación e ámbito.
Comprende esta ordenanza as áreas de solo urbano consolidadas en
formación de cuarteirón pechado, tal e como se delimita en planos.
3.  Parámetros e condicións da edificación.
Cando en cuarteiróns compactos non se estableza indicación algunha en
planos de ordenación autorízase a ocupación da totalidade da parcela
edificable, sen prexuízo do cumprimento da lexislación aplicable.
A altura máxima da edificación estará en función do ancho do espazo
público ao que dea fronte, e quedará definida segundo o seguinte cadro:
Ancho de Rúa Nº de plantas Altura en metros
Menor de 6 m. 3 10,50 m.
Desde 6 m. e menor de 12 m. 4 13,00 m.
Desde 12 m. e menor de 18 m. 5 16,50 m.
Desde 18 m. e menor de 24 m. 6 19,00 m.
Desde 24 m. 7 22,50 m.
Non se establece parcela mínima. A efectos de parcelación establécese
unha fronte mínima de parcela de 8 metros.
Autorízanse voos nas condicións establecidas no artigo 62.13 e 14 das
presentes Normas e sen ocupar máis do 25% da superficie de fachada.
Autorízase a construción de entreplantas, que en ningún caso poderán
ocupar máis do cincuenta (50) por cento dos locais de planta baixa.
5.  Usos.
Permítense os seguintes usos:
•  Residencial.
•  Terciario: Hoteleiro.
•  Terciario: Comercial. Categoría 1ª, 2ª.
6.  Condicións especiais.
Naquelas parcelas en contacto con outras destinadas a dotacións.
"""


def test_u2_tabla_altura_por_ancho_rua():
    """U2 expresa la altura como tabla ancho de rúa → plantas/metros."""
    params, trazas = np._extract_params(_block(_U2_TEXT, pag=168, ord_code='U2'))
    tabla = params['altura_por_ancho_rua']
    assert '<6 m' in tabla and '22,5' in tabla
    assert 'altura_maxima_m' not in params  # no es un valor único
    rows = trazas['altura_por_ancho_rua']['tabla']
    assert len(rows) == 5
    assert rows[0] == {'ancho_min_m': None, 'ancho_max_m': 6.0,
                       'plantas': 3, 'altura_m': 10.5}
    assert rows[-1] == {'ancho_min_m': 24.0, 'ancho_max_m': None,
                        'plantas': 7, 'altura_m': 22.5}


def test_u2_parametros_en_prosa():
    """Frente mínima, voos %, entreplantas %, ocupación condicional."""
    params, _ = np._extract_params(_block(_U2_TEXT, ord_code='U2'))
    assert params['frente_minima_m'] == 8.0
    assert params['voos_max_pct_fachada'] == 25.0
    assert params['entreplantas_max_pct'] == 50.0
    assert '100%' in params['ocupacion_condicional']
    # 'Non se establece parcela mínima' → no debe extraer número
    assert 'parcela_minima_m2' not in params


def test_u2_usos_permitidos():
    params, _ = np._extract_params(_block(_U2_TEXT, ord_code='U2'))
    usos = params['usos_permitidos']
    assert 'Residencial' in usos
    assert 'Hoteleiro' in usos and 'Comercial' in usos
    # se detiene en la siguiente sección numerada
    assert 'Condicións especiais' not in usos


def test_mencion_en_tabla_no_abre_bloque():
    """'ORDENANZA U9 UNIDADES Edificio Non Exclusivo' (fila de tabla
    resumen de instalacións industriais) no debe abrir un bloque."""
    pages = [
        "ART . 77. ORDENANZA U2. CUARTEIRÓN PECHADO.\ntexto " + "a" * 50,
        "LÍMITES DAS INSTALACIÓNS INDUSTRIAIS.\nCATEGORÍA\n"
        "ORDENANZA U9 UNIDADESEdificio Non Exclusivo\n"
        "Edificio ExclusivoCalquera planta\nmás texto",
    ]
    blocks = np._segment_ordenanzas(pages)
    codes = [b['ordenanza'] for b in blocks]
    assert 'U2' in codes and 'U9' not in codes
    # el texto de la tabla queda dentro del bloque U2, no abre otro
    u2 = next(b for b in blocks if b['ordenanza'] == 'U2')
    assert 'INSTALACIÓNS' in u2['texto']


def test_boilerplate_boppo_no_rompe_extraccion():
    """Cabeceras/pies del BOPPO intercalados no impiden extraer."""
    texto = _U2_TEXT.replace(
        'Menor de 6 m. 3 10,50 m.',
        'Edita: Deputación de Pontevedra • Depósito legal: PO 1-1958\n'
        'Núm.\nLuns, 4 de agosto de 2025\n146\nBOPPO\n'
        'Menor de 6 m. 3 10,50 m.')
    params, _ = np._extract_params(_block(texto, ord_code='U2'))
    assert 'altura_por_ancho_rua' in params


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
