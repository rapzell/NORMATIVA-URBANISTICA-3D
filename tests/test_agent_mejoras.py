"""Tests de los módulos de mejora del asistente (guía del experto):
intención LLM+fallback, memoria multi-turno, sinónimos, búsqueda
híbrida RRF, contradicciones, cambio de uso NHV y validación
semántica. Todo hermético: sin red, sin servicio :8003 ni LLM real.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.agent import memory, tools
from src.agent.contradictions import detectar_contradicciones
from src.agent.intent_classifier import (clasificar_intencion,
                                         _detectar_intencion_regex)
from src.agent import orchestrator
from src.rag.hybrid_search import rrf_fusion, chunk_key
from src.rag.synonyms import expandir_query, boost_por_tipo


# ---------- clasificador de intención ----------

def test_intencion_regex_etiquetas():
    assert _detectar_intencion_regex('hola buenas') == 'saludo'
    assert _detectar_intencion_regex(
        'que tipo de suelo he seleccionado') == 'edificio'
    assert _detectar_intencion_regex(
        'cuanta ocupacion me queda') == 'calculo'
    assert _detectar_intencion_regex(
        'puedo hacer una piscina') == 'normativa'


def test_intencion_llm_invalido_cae_a_regex(monkeypatch):
    monkeypatch.setattr(
        'src.agent.intent_classifier.clasificar_intencion_llm',
        lambda *a, **k: None)
    # bucket ambiguo → intenta LLM → None → regex
    assert clasificar_intencion('puedo hacer una piscina') == 'normativa'


def test_intencion_llm_refin_a_contexto(monkeypatch):
    # El regex diría 'normativa' pero el LLM corrige a contexto
    monkeypatch.setattr(
        'src.agent.intent_classifier.clasificar_intencion_llm',
        lambda *a, **k: 'edificio')
    assert clasificar_intencion('cuanto mide esto') == 'edificio'


def test_intencion_regex_fiable_no_llama_llm(monkeypatch):
    llamado = []
    monkeypatch.setattr(
        'src.agent.intent_classifier.clasificar_intencion_llm',
        lambda *a, **k: llamado.append(1) or 'normativa')
    assert clasificar_intencion('hola') == 'saludo'
    assert not llamado  # saludo es fiable → no se gasta la llamada


# ---------- memoria multi-turno ----------

def test_memoria_turnos_ventana_deslizante():
    mem = memory.SessionMemory(chat_id='t1')
    for i in range(5):
        mem.add_turn(f'pregunta {i}', f'respuesta {i}')
    assert len(mem.turns) == 3
    assert mem.turns[0]['pregunta'] == 'pregunta 2'


def test_memoria_referencias():
    mem = memory.SessionMemory(chat_id='t2')
    for ref in ('y si la piscina fuera mas pequena',
                'que hay ahi', 'y en la parcela de al lado',
                'lo mismo pero con garaje'):
        assert mem.usa_referencia(ref) is True
    assert mem.usa_referencia('puedo hacer una piscina') is False


def test_memoria_sesiones_aisladas():
    a = memory.get_session('chat-a')
    b = memory.get_session('chat-b')
    assert a is not b
    a.add_turn('p1', 'r1')
    assert len(b.turns) == 0


def test_memoria_sin_chat_id():
    assert memory.get_session(None) is None
    assert memory.get_session('') is None


def test_memoria_ttl_expira(monkeypatch):
    mem = memory.get_session('vieja')
    ts, _ = memory._SESSIONS['vieja']
    memory._SESSIONS['vieja'] = (ts - 31 * 60, mem)
    nueva = memory.get_session('vieja')
    assert nueva is not mem
    memory._SESSIONS.pop('vieja', None)


def test_memoria_historial_prompt():
    mem = memory.SessionMemory(chat_id='t3')
    mem.add_turn('que suelo tiene', 'SUC')
    hist = mem.build_history_context()
    assert 'HISTORIAL' in hist and 'que suelo tiene' in hist


# ---------- sinónimos ----------

def test_expandir_query_sinonimos():
    q = expandir_query('puedo hacer una piscina')
    assert 'piscina' in q and 'auxiliar' in q
    q2 = expandir_query('retranqueo a linderos')
    assert 'recuado' in q2


def test_expandir_query_acentos():
    q = expandir_query('ocupacion maxima')  # sin tilde
    assert 'ocupación' in q or 'huella' in q


def test_expandir_query_conserva_original():
    original = 'cuanta ocupacion me queda'
    assert expandir_query(original).startswith(original)


def test_boost_por_tipo():
    frags = [
        {'texto': 'disposiciones generales varias', 'score': 5.0},
        {'texto': 'instalación auxiliar piscina ocupación', 'score': 1.0},
    ]
    out = boost_por_tipo('puedo hacer una piscina', frags)
    assert 'piscina' in out[0]['texto']


# ---------- RRF ----------

def test_rrf_fusion_k60():
    # A aparece 1º en BM25 y 2º en semántico → debe ganar a B (1º solo
    # en semántico) por la doble presencia con k=60.
    bm25 = ['A', 'C', 'D']
    sem = ['B', 'A', 'E']
    scores = rrf_fusion([bm25, sem], k=60)
    assert scores['A'] > scores['B']
    assert scores['A'] == pytest.approx(1 / 61 + 1 / 62)
    assert scores['C'] == pytest.approx(1 / 62)


def test_chunk_key_estable():
    assert chunk_key('lsg', 12, 0) == 'lsg:12:0'


# ---------- contradicciones ----------

def _ctx_altura(altura_medida, altura_max, ordenanza='U6'):
    return {
        'building': {'altura': {'value': altura_medida}},
        'ordenanzas_params': {'ordenanza': ordenanza,
                              'altura_maxima_m': altura_max},
        'resumen': {},
        'catastro': {},
    }


def test_contradiccion_altura_vs_ordenanza():
    # Caso real: edificio de 23 m con ordenanza unifamiliar de 7 m
    adv = detectar_contradicciones(_ctx_altura(23.0, 7.0))
    assert adv and '23' in adv[0] and 'mal asignada' in adv[0]


def test_sin_contradiccion_altura_coherente():
    assert detectar_contradicciones(_ctx_altura(6.0, 7.0)) == []


def test_contradiccion_sin_ordenanza_no_avisa():
    ctx = _ctx_altura(50.0, 7.0)
    ctx['ordenanzas_params'] = {}
    assert detectar_contradicciones(ctx) == []


def test_contradiccion_parcela_minima():
    ctx = {
        'building': {}, 'catastro': {},
        'resumen': {'superficie_parcela_m2': 87},
        'ordenanzas_params': {'ordenanza': 'U6',
                              'parcela_minima_m2': 300},
    }
    adv = detectar_contradicciones(ctx)
    assert adv and 'parcela' in adv[0].lower()


# ---------- calculador cambio de uso (NHV real) ----------

def test_cambio_uso_sin_medidas_no_verificable():
    r = tools.check_cambio_uso({'municipio': 'Vigo'})
    assert r['data_quality'] == 'official'
    assert r['estado_global'] != 'cumple'
    assert r['fuentes']  # siempre cita DOG/NHV
    assert 'requisitos' in r


def test_cambio_uso_no_inventa_piezas():
    r = tools.check_cambio_uso({}, altura_libre_m=2.6)
    # Sin piezas no puede declarar cumplimiento del programa mínimo
    assert r['estado_global'] != 'cumple'


# ---------- orquestador: cambio de uso + memoria ----------

def test_orquestador_cambio_uso_invoca_checker(monkeypatch):
    llamado = {}
    monkeypatch.setattr(
        orchestrator, '_contexto_edificio',
        lambda *a, **k: ({'municipio': 'Vigo', 'resumen': {},
                          'ordenanzas_params': {}}, ['catastro']))
    monkeypatch.setattr(
        tools, 'search_normativa',
        lambda *a, **k: {'fragmentos': [], 'n_corpus': 0,
                         'n_municipal': 0, 'rerank': False})
    def _cambio(ctx):
        llamado['ok'] = True
        return {'data_quality': 'official', 'estado_global': 'no_verificable'}
    monkeypatch.setattr(tools, 'check_cambio_uso', _cambio)
    monkeypatch.setattr(
        'src.model_gateway.generate_with_fallback',
        lambda *a, **k: 'No ha sido posible generar respuesta')
    r = orchestrator.responder_consulta_edificio(
        'puedo convertir este local en vivienda', municipio='Vigo')
    assert llamado.get('ok') is True
    assert 'check_cambio_uso' in r['herramientas']
    assert r['calculo']['estado_global'] == 'no_verificable'


def test_orquestador_memoria_resuelve_referencia(monkeypatch):
    capturado = {}

    def _ctx(lon, lat, ine, municipio, subzona, refcat):
        capturado.update({'lon': lon, 'lat': lat, 'municipio': municipio})
        return ({'municipio': municipio, 'resumen': {},
                 'ordenanzas_params': {}}, ['catastro'])

    monkeypatch.setattr(orchestrator, '_contexto_edificio', _ctx)
    monkeypatch.setattr(
        tools, 'search_normativa',
        lambda *a, **k: {'fragmentos': [], 'n_corpus': 0,
                         'n_municipal': 0, 'rerank': False})
    monkeypatch.setattr(
        'src.model_gateway.generate_with_fallback',
        lambda *a, **k: 'No ha sido posible generar respuesta')

    cid = f'test-{time.time()}'
    orchestrator.responder_consulta_edificio(
        'que tipo de suelo he seleccionado', lon=-8.7, lat=42.2,
        municipio='Vigo', chat_id=cid)
    orchestrator.responder_consulta_edificio(
        'y ahi puedo hacer una piscina', municipio=None, chat_id=cid)
    assert capturado['lon'] == -8.7  # referencia resuelta al punto previo


def test_orquestador_advertencias_en_respuesta(monkeypatch):
    monkeypatch.setattr(
        orchestrator, '_contexto_edificio',
        lambda *a, **k: ({
            'municipio': 'Vigo',
            'building': {'altura': {'value': 23.0}},
            'ordenanzas_params': {'ordenanza': 'U6',
                                  'altura_maxima_m': 7.0},
            'resumen': {}, 'catastro': {},
        }, ['catastro']))
    r = orchestrator.responder_consulta_edificio(
        'que tipo de edificio he seleccionado', municipio='Vigo')
    assert 'mal asignada' in r['respuesta']
    assert r['advertencias']


# ---------- resolución parcela → ordenanza ----------

_ORDS = {
    'U4': {'titulo': 'VIVIENDA UNIFAMILIAR AISLADA',
           'params': {'altura_maxima_m': 7.0}},
    'U6': {'titulo': 'VIVIENDA UNIFAMILIAR ADOSADA',
           'params': {'altura_maxima_m': 7.0}},
    'U10': {'titulo': 'VIVIENDA COLECTIVA EN MANZANA CERRADA',
            'params': {'altura_maxima_m': 21.0}},
}


def _ctx_res(denom=None, recinto=None, uso=None, subzona=None):
    return {
        'subzona': subzona,
        'clasificacion': {'denominacion_zona': denom,
                          'id_recinto': recinto,
                          'uso_zona': uso},
        'ordenanzas': {'ordenanzas': _ORDS},
    }


def test_resolver_codigo_oficial():
    from src.agent.ordinance_resolver import resolver_ordenanza
    r = resolver_ordenanza(_ctx_res(recinto='U10', denom='MANZANA 12'))
    assert r['estado'] == 'oficial' and r['ordenanza'] == 'U10'
    assert r['params']['altura_maxima_m'] == 21.0


def test_resolver_inferida_por_titulo():
    from src.agent.ordinance_resolver import resolver_ordenanza
    r = resolver_ordenanza(
        _ctx_res(denom='VIVIENDA COLECTIVA EN MANZANA CERRADA'))
    assert r['estado'] == 'inferida' and r['ordenanza'] == 'U10'
    assert r['confianza'] == 'media'


def test_resolver_ambigua_no_elige():
    from src.agent.ordinance_resolver import resolver_ordenanza
    r = resolver_ordenanza(_ctx_res(recinto='U4 U6'))
    assert r['estado'] == 'ambigua'
    assert set(r['candidatas']) == {'U4', 'U6'}


def test_resolver_no_resuelta_lista_disponibles():
    from src.agent.ordinance_resolver import resolver_ordenanza
    r = resolver_ordenanza(_ctx_res(denom='SUC'))
    assert r['estado'] == 'no_resuelta'
    assert 'U10' in r['ordenanzas_disponibles']


def test_resolver_usuario_manda():
    from src.agent.ordinance_resolver import resolver_ordenanza
    r = resolver_ordenanza(_ctx_res(recinto='U10', subzona='U4'))
    assert r['estado'] == 'usuario' and r['ordenanza'] == 'U4'


def test_orquestador_ordenanza_citada_fuente_determinista(monkeypatch):
    """«¿edificabilidad de U6?» → los parámetros extraídos del PDF
    entran como FUENTE 1 con página trazada, sin depender del BM25."""
    monkeypatch.setattr(
        orchestrator, '_contexto_edificio',
        lambda *a, **k: ({
            'municipio': 'Vigo', 'resumen': {},
            'ordenanzas': {'ordenanzas': {
                'U6': {'titulo': 'VIVIENDA UNIFAMILIAR',
                       'params': {'edificabilidad_max_m2_m2': 0.7},
                       'trazas': {'edificabilidad_max_m2_m2':
                                  {'pagina': 179}},
                       'fuente': 'pxom.pdf pág. 179'}}},
            'ordenanzas_params': {}}, ['catastro']))
    monkeypatch.setattr(
        tools, 'search_normativa',
        lambda *a, **k: {'fragmentos': [], 'n_corpus': 0,
                         'n_municipal': 0, 'rerank': False})
    monkeypatch.setattr(
        'src.model_gateway.generate_with_fallback',
        lambda *a, **k: 'La U6 permite 0,70 m²/m² [FUENTE 1]')
    r = orchestrator.responder_consulta_edificio(
        'que edificabilidad tiene la ordenanza U6', municipio='Vigo')
    f1 = r['fuentes'][0]
    assert f1['pagina'] == 179
    assert 'U6' in (f1.get('extracto') or '')
    assert '0.7' in (f1.get('extracto') or '')


# ---------- capa vectorial municipal (muni_wfs + resolver) ----------

def _wfs_geojson(codes):
    """Un polígono cuadrado por código; el primero cubre el punto."""
    feats = []
    for i, code in enumerate(codes):
        x0, y0 = (-8.72, 42.23) if i == 0 else (-8.60, 42.30)
        feats.append({'type': 'Feature',
                      'properties': {'ordenanza': code},
                      'geometry': {'type': 'Polygon', 'coordinates': [[
                          [x0, y0], [x0 + 0.005, y0],
                          [x0 + 0.005, y0 + 0.005], [x0, y0 + 0.005],
                          [x0, y0]]]}})
    return {'type': 'FeatureCollection', 'features': feats}


def test_muni_wfs_punto_en_poligono():
    from src import muni_wfs

    class R:
        def json(self):
            return _wfs_geojson(['U8'])

    with patch('src.muni_wfs.capa_features', return_value=[]), \
         patch('src.muni_wfs.requests.get', return_value=R()):
        r = muni_wfs.consultar_ordenanza_punto(-8.718, 42.232, '36057')
    assert r['data_quality'] == 'official'
    assert r['ordenanza'] == 'U8'
    assert 'Vigo' in r['fuente']


def test_muni_wfs_punto_fuera_de_capa():
    from src import muni_wfs

    class R:
        def json(self):
            return _wfs_geojson([])

    with patch('src.muni_wfs.capa_features', return_value=[]), \
         patch('src.muni_wfs.requests.get', return_value=R()):
        r = muni_wfs.consultar_ordenanza_punto(-8.718, 42.232, '36057')
    assert r['data_quality'] == 'unavailable'


def test_muni_wfs_error_red_degrada():
    from src import muni_wfs
    with patch('src.muni_wfs.capa_features', return_value=[]), \
         patch('src.muni_wfs.requests.get',
               side_effect=RuntimeError('timeout')):
        r = muni_wfs.consultar_ordenanza_punto(-8.718, 42.232, '36057')
    assert r['data_quality'] == 'unavailable'


def test_muni_wfs_ambigua_dos_poligonos():
    from src import muni_wfs

    class R:
        def json(self):
            g = _wfs_geojson(['U6'])
            g['features'].append({
                'type': 'Feature',
                'properties': {'ordenanza': 'U8'},
                'geometry': {'type': 'Polygon', 'coordinates': [[
                    [-8.72, 42.23], [-8.71, 42.23],
                    [-8.71, 42.24], [-8.72, 42.24],
                    [-8.72, 42.23]]]}})
            return g

    with patch('src.muni_wfs.capa_features', return_value=[]), \
         patch('src.muni_wfs.requests.get', return_value=R()):
        r = muni_wfs.consultar_ordenanza_punto(-8.718, 42.232, '36057')
    assert r['ambigua'] is True
    assert set(r['candidatas']) == {'U6', 'U8'}
    assert r['ordenanza'] is None


def test_muni_wfs_capa_local_cacheada():
    """La copia local cacheada evita la red y hace pip real."""
    from src import muni_wfs
    feats = _wfs_geojson(['U6'])['features']
    with patch('src.muni_wfs.capa_features', return_value=feats), \
         patch('src.muni_wfs.requests.get',
               side_effect=AssertionError('no debe llamar a la red')):
        r = muni_wfs.consultar_ordenanza_punto(-8.718, 42.232, '36057')
        r_fuera = muni_wfs.consultar_ordenanza_punto(
            -8.5, 42.5, '36057')
    assert r['data_quality'] == 'official'
    assert r['ordenanza'] == 'U6'
    assert r_fuera['data_quality'] == 'unavailable'
    assert 'fuera de la capa' in (r_fuera.get('error') or '').lower()


def test_muni_wfs_sin_capa_municipio():
    from src import muni_wfs
    assert muni_wfs.consultar_ordenanza_punto(
        -8.7, 42.2, '99999') is None


def test_resolver_wfs_oficial():
    """La capa vectorial oficial resuelve 'oficial' con trazabilidad."""
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_res()
    ctx['ordenanza_wfs'] = {
        'data_quality': 'official', 'ordenanza': 'U10',
        'candidatas': ['U10'], 'fuente': 'GeoServer municipal',
        'instrumento': 'PXOM Vigo'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'oficial'
    assert r['ordenanza'] == 'U10'
    assert r['origen'] == 'GeoServer municipal'
    assert r['params'].get('altura_maxima_m') == 21.0


def test_resolver_wfs_oficial_codigo_no_extraido():
    """El WFS da subzona ('U6.5'); el PDF la ordenanza ('U6') — se
    resuelve por prefijo y se conserva el código de zona original."""
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_res()
    ctx['ordenanza_wfs'] = {
        'data_quality': 'official', 'ordenanza': 'U6.5',
        'candidatas': ['U6.5'], 'fuente': 'GeoServer municipal'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'oficial'
    assert r['ordenanza'] == 'U6'
    assert r['codigo_zona'] == 'U6.5'


def test_resolver_wfs_ambigua_no_elige():
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_res()
    ctx['ordenanza_wfs'] = {
        'data_quality': 'official', 'ordenanza': None,
        'ambigua': True, 'candidatas': ['U6', 'U8'],
        'fuente': 'GeoServer municipal'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'ambigua'
    assert set(r['candidatas']) == {'U6', 'U8'}


def test_resolver_wfs_unavailable_cae_a_atributos():
    """WFS caído no rompe: se sigue con atributos/títulos."""
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_res(recinto='U10', denom='MANZANA 12')
    ctx['ordenanza_wfs'] = {'data_quality': 'unavailable',
                            'error': 'WFS municipal no responde'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'oficial' and r['ordenanza'] == 'U10'
    assert r['origen'] != 'GeoServer municipal'


def test_resolver_subzona_invalida_no_bloquea_wfs():
    """Caso real: subzona 'R-1' seleccionada en el visor no existe en
    el PGOM — no debe impedir que el WFS oficial resuelva."""
    from src.agent.ordinance_resolver import resolver_ordenanza
    ctx = _ctx_res(subzona='R-1')
    ctx['ordenanza_wfs'] = {
        'data_quality': 'official', 'ordenanza': 'U2',
        'candidatas': ['U2'], 'fuente': 'GeoServer municipal'}
    r = resolver_ordenanza(ctx)
    assert r['estado'] == 'oficial' and r['ordenanza'] == 'U2'


def test_contradiccion_subzona_inexistente():
    ctx = {
        'building': {}, 'catastro': {}, 'resumen': {},
        'subzona': 'R-1',
        'ordenanzas': {'ordenanzas': {'U2': {}}},
        'ordenanza_resolucion': {'estado': 'oficial',
                                 'ordenanza': 'U2'},
        'ordenanzas_params': {'ordenanza': 'U2'},
    }
    adv = detectar_contradicciones(ctx)
    assert adv and 'R-1' in adv[0] and 'U2' in adv[0]


def test_contradiccion_subzona_difiere_de_wfs():
    ctx = {
        'building': {}, 'catastro': {}, 'resumen': {},
        'subzona': 'U6',
        'ordenanzas': {'ordenanzas': {'U6': {}}},
        'ordenanza_wfs': {'data_quality': 'official',
                          'ordenanza': 'U2'},
        'ordenanzas_params': {'ordenanza': 'U6'},
    }
    adv = detectar_contradicciones(ctx)
    assert adv and 'difiere' in adv[0]


def test_contradiccion_subzona_valida_sin_aviso():
    ctx = {
        'building': {}, 'catastro': {}, 'resumen': {},
        'subzona': 'U6',
        'ordenanzas': {'ordenanzas': {'U6': {}}},
        'ordenanza_wfs': {'data_quality': 'official',
                          'ordenanza': 'U6.5'},
        'ordenanzas_params': {'ordenanza': 'U6'},
    }
    assert detectar_contradicciones(ctx) == []


# ---------- validación semántica (env-gated) ----------

def test_semantica_desactivada_por_defecto(monkeypatch):
    monkeypatch.delenv('SEMANTIC_VALIDATION', raising=False)
    from src.agent.validator import validacion_semantica
    heur = {'valida': True, 'requiere_revision': False}
    assert validacion_semantica('resp', [], heur) is heur


def test_semantica_no_corre_si_heuristica_fallo(monkeypatch):
    monkeypatch.setenv('SEMANTIC_VALIDATION', '1')
    from src.agent.validator import validacion_semantica
    heur = {'valida': False, 'requiere_revision': True}
    assert validacion_semantica('resp', [], heur) is heur


def test_semantica_llm_invalido_degrada(monkeypatch):
    monkeypatch.setenv('SEMANTIC_VALIDATION', '1')
    monkeypatch.setattr(
        'src.model_gateway._iter_provider_attempts',
        lambda: ['openrouter'])
    monkeypatch.setattr(
        'src.model_gateway._provider_attempt',
        lambda *a, **k: 'esto no es JSON')
    from src.agent.validator import validacion_semantica
    heur = {'valida': True, 'requiere_revision': False}
    assert validacion_semantica('resp', [], heur) is heur


def test_semantica_marca_sin_respaldo(monkeypatch):
    monkeypatch.setenv('SEMANTIC_VALIDATION', '1')
    monkeypatch.setattr(
        'src.model_gateway._iter_provider_attempts',
        lambda: ['openrouter'])
    monkeypatch.setattr(
        'src.model_gateway._provider_attempt',
        lambda *a, **k:
        '{"valida": false, "afirmaciones_sin_respaldo": ["altura 12 m"]}')
    from src.agent.validator import validacion_semantica
    heur = {'valida': True, 'requiere_revision': False, 'avisos': []}
    out = validacion_semantica('La altura es 12 m', [{'id': 1}], heur)
    assert out['requiere_revision'] is True
    assert out['semantica']['valida'] is False
