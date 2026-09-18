"""Tests del asistente agéntico de normativa (orquestador, validador,
herramientas y endpoints /qa/edificio*)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as _m
from src.agent import orchestrator, tools
from src.agent.validator import validar_respuesta, anotar_respuesta
from src.rag.corpus import _segment_by_articles


# ---------- corpus: segmentación por artículo ----------

def test_segment_by_articles():
    texto = (
        "EXPOSICIÓN DE MOTIVOS\nTexto previo.\n\n"
        "Artículo 45. Régimen.\n1. Primera parte del artículo 45.\n"
        "2. Segunda parte.\n\n"
        "Artigo 46. Clasificación.\nTexto del artigo 46 en gallego.\n\n"
        "Disposición adicional segunda. Más texto.\n"
    )
    blocks = _segment_by_articles(texto)
    refs = [b['ref'] for b in blocks]
    assert 'Art. 45' in refs
    assert 'Art. 46' in refs
    assert any('disposición adicional segunda' in r.lower() for r in refs)


# ---------- validador ----------

def _fuentes(n=3):
    return [{'id': i + 1, 'texto': f'texto de la fuente {i + 1} con 40 por ciento',
             'extracto': 'extracto'} for i in range(n)]


def test_validador_citas_correctas():
    resp = "La ocupación máxima es del 40% [FUENTE 1] según el artículo [FUENTE 2]."
    v = validar_respuesta(resp, _fuentes(), {})
    assert v['valida'] is True
    assert v['requiere_revision'] is False
    assert {c['id'] for c in v['citas']} >= {1, 2}


def test_validador_cita_inventada():
    resp = "Según la norma [FUENTE 9] el límite es otro."
    v = validar_respuesta(resp, _fuentes(), {})
    assert v['valida'] is False
    assert v['requiere_revision'] is True
    assert any('FUENTE 9' in e for e in v['errores'])
    assert 'Requiere revisión humana' in anotar_respuesta(resp, v)


def test_validador_numero_sin_respaldo():
    resp = "El retranqueo mínimo es 45.7 metros [FUENTE 1]."
    v = validar_respuesta(resp, _fuentes(), {})
    assert any('45.7' in a for a in v['avisos'])


# ---------- herramienta: viabilidad de piscina ----------

def test_piscina_viability_math():
    ctx = {
        'resumen': {'superficie_parcela_m2': 450.0},
        'building': {'huella_m2': {'value': 285.0}},
        'ordenanzas_params': {'ocupacion_max_pct': 70.0},
    }
    calc = tools.check_piscina_viability(ctx, sup_piscina_m2=24.0, computo=0.5)
    assert calc['limite_m2'] == pytest.approx(315.0)
    assert calc['margen_m2'] == pytest.approx(30.0)
    assert calc['piscina_computa_m2'] == 12.0
    assert calc['viable_ocupacion'] is True
    assert calc['ocupacion_resultante_pct'] == pytest.approx(66.0, abs=0.1)


def test_piscina_viability_sin_datos():
    calc = tools.check_piscina_viability({})
    assert calc['data_quality'] == 'unavailable'


# ---------- orquestador (mockeado) ----------

@pytest.fixture
def prep_mocks(monkeypatch):
    frag = [{'id': 1, 'documento': 'Ley 2/2016', 'referencia': 'Art. 39',
             'pagina': 48, 'texto': 'ocupación máxima del suelo',
             'extracto': 'ocupación', 'fuente': 'Xunta', 'url': None,
             'ambito': 'autonomico', 'score': 5.0}]
    monkeypatch.setattr(
        orchestrator, '_contexto_edificio',
        lambda *a, **k: ({'municipio': 'Vigo', 'resumen': {},
                          'ordenanzas_params': {}}, ['catastro']))
    monkeypatch.setattr(
        tools, 'search_normativa',
        lambda *a, **k: {'fragmentos': frag, 'n_corpus': 1,
                         'n_municipal': 0, 'rerank': False})
    return frag


def test_orquestador_modo_heuristico(prep_mocks, monkeypatch):
    monkeypatch.setattr(
        'src.model_gateway.generate_with_fallback',
        lambda *a, **k: 'No ha sido posible generar respuesta (local fallo)')
    r = orchestrator.responder_consulta_edificio(
        'ocupación máxima', municipio='Vigo')
    assert r['modo'] == 'heuristico'
    assert r['llm'] is False
    assert 'artículos aplicables' in r['respuesta']
    assert r['fuentes'][0]['referencia'] == 'Art. 39'


def test_orquestador_llm_valida_citas(prep_mocks, monkeypatch):
    monkeypatch.setattr(
        'src.model_gateway.generate_with_fallback',
        lambda *a, **k: 'La ocupación máxima es del 40% [FUENTE 1].')
    r = orchestrator.responder_consulta_edificio(
        'ocupación máxima', municipio='Vigo')
    assert r['modo'] == 'llm'
    assert r['validacion']['valida'] is True


def test_orquestador_llm_cita_falsa_degrada(prep_mocks, monkeypatch):
    monkeypatch.setattr(
        'src.model_gateway.generate_with_fallback',
        lambda *a, **k: 'El límite es 99 m según [FUENTE 7].')
    r = orchestrator.responder_consulta_edificio(
        'altura máxima', municipio='Vigo')
    assert r['validacion']['requiere_revision'] is True
    assert 'Requiere revisión humana' in r['respuesta']


# ---------- endpoints ----------

def test_qa_edificio_endpoint(prep_mocks, monkeypatch):
    monkeypatch.setattr(
        'src.model_gateway.generate_with_fallback',
        lambda *a, **k: 'Respuesta con cita [FUENTE 1].')
    client = TestClient(_m.app)
    r = client.post('/qa/edificio', json={
        'pregunta': 'ocupación máxima', 'municipio': 'Vigo',
        'lon': -8.71, 'lat': 42.23})
    assert r.status_code == 200
    data = r.json()
    assert data['modo'] == 'llm'
    assert data['fuentes']


def test_qa_edificio_stream_sse(prep_mocks, monkeypatch):
    monkeypatch.setattr(
        'src.model_gateway.generate_with_fallback',
        lambda *a, **k: 'No ha sido posible generar respuesta')
    client = TestClient(_m.app)
    r = client.post('/qa/edificio/stream', json={
        'pregunta': 'ocupación máxima', 'municipio': 'Vigo'})
    assert r.status_code == 200
    assert 'text/event-stream' in r.headers['content-type']
    assert '"tipo": "fuentes"' in r.text
    assert '"tipo": "final"' in r.text


def test_qa_health_endpoint():
    client = TestClient(_m.app)
    r = client.get('/qa/health')
    assert r.status_code == 200
    data = r.json()
    assert 'llm' in data and 'corpus' in data
    assert 'rerank_semantico' in data
