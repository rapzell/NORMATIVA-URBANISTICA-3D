"""Tests del cliente documental SIOTUGA (sesión, documentos, descarga)."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.siotuga import document_client as dc


class FakeResp:
    def __init__(self, text='', json_data=None, content=b'', status=200):
        self.text = text
        self._json = json_data
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')

    def json(self):
        return self._json


class FakeSession:
    """Sesión requests simulada con cookies y respuestas programadas."""

    def __init__(self, pages=None, posts=None, downloads=None):
        self.pages = pages or {}
        self.posts = posts or {}
        self.downloads = downloads or {}
        self.get_calls = []
        self.post_calls = []

    def get(self, url, params=None, timeout=None):
        self.get_calls.append(url)
        if url in self.downloads:
            return FakeResp(content=self.downloads[url])
        return FakeResp(text=self.pages.get(url, ''))

    def post(self, url, data=None, headers=None, timeout=None):
        self.post_calls.append((url, data))
        return FakeResp(json_data=self.posts.get(url))


TOKEN_HTML = "<input type='hidden' id='token' name='token' value='abc123token'>"


def _factory(pages=None, posts=None, downloads=None):
    sess = FakeSession(pages, posts, downloads)
    return lambda: sess


def test_session_open_extracts_token():
    sess = FakeSession({dc.INVENTARIO_URL: TOKEN_HTML})
    s = dc.SiotugaSession(session_factory=lambda: sess)
    token = s.open('36057')
    assert token == 'abc123token'
    assert s.token == 'abc123token'


def test_session_open_fails_without_token():
    sess = FakeSession({dc.INVENTARIO_URL: '<html>sin token</html>'})
    s = dc.SiotugaSession(session_factory=lambda: sess)
    with pytest.raises(RuntimeError):
        s.open('36057')


def test_document_url_pattern():
    url = dc.document_url('documentos/urbanismo/', 'VIGO', '28719nu003.pdf')
    assert url == ('https://siotuga.xunta.gal/siotuga/documentos/'
                   'urbanismo/VIGO/documents/28719nu003.pdf')


def test_query_documents_uses_token():
    docs = [{'id': 28719, 'docnome': 'PXOM VIGO', 'fechaaddef': '2025-05-26'}]
    posts = {dc.QUERY_DOC_URL: docs}
    sess = FakeSession({dc.INVENTARIO_URL: TOKEN_HTML}, posts)
    s = dc.SiotugaSession(session_factory=lambda: sess)
    s.open('36057')
    result = s.query_documents('36057', 14)
    assert result == docs
    url, data = sess.post_calls[0]
    assert url == dc.QUERY_DOC_URL
    assert 'id=36057' in data and 'token=abc123token' in data and 'idclase=14' in data


def test_componentes_resuelve_urls():
    iotpu = {
        'datos_xerais': {'filesroot': 'documentos/urbanismo/', 'folder': 'VIGO'},
        'elementos': [
            {'id': 13509, 'description': 'NU. NORMATIVA URBANÍSTICA',
             'componentes': [
                 {'id': 1, 'pathesperado': '28719nu003.pdf',
                  'descripcion': 'NORMATIVA URBANÍSTICA'},
                 {'id': 2, 'pathesperado': '',
                  'descripcion': 'sin fichero'},
             ]},
        ],
    }
    posts = {dc.IOTPU_URL: iotpu}
    sess = FakeSession({dc.INVENTARIO_URL: TOKEN_HTML}, posts)
    s = dc.SiotugaSession(session_factory=lambda: sess)
    det = dc.componentes_documento(28719, '36057', session=s)
    sec = det['secciones'][0]
    assert sec['descripcion'] == 'NU. NORMATIVA URBANÍSTICA'
    assert len(sec['componentes']) == 1  # sin pathesperado se descarta
    comp = sec['componentes'][0]
    assert comp['url'].endswith('/VIGO/documents/28719nu003.pdf')


def test_descargar_documentos_graba_pdf_y_manifiesto(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, 'NORMATIVA_DIR', str(tmp_path))
    docs = [{'id': 28719, 'docnome': 'PXOM VIGO', 'fechaaddef': '2025-05-26'}]
    iotpu = {
        'datos_xerais': {'filesroot': 'documentos/urbanismo/', 'folder': 'VIGO'},
        'elementos': [
            {'id': 1, 'description': 'NU. NORMATIVA URBANÍSTICA',
             'componentes': [
                 {'id': 10, 'pathesperado': 'nu003.pdf',
                  'descripcion': 'NORMATIVA'},
             ]},
            {'id': 2, 'description': 'PORD. PLANOS',
             'componentes': [
                 {'id': 11, 'pathesperado': 'plano.pdf',
                  'descripcion': 'PLANO'},
             ]},
        ],
    }
    nu_url = dc.document_url('documentos/urbanismo/', 'VIGO', 'nu003.pdf')
    posts = {dc.QUERY_DOC_URL: docs, dc.IOTPU_URL: iotpu}
    downloads = {nu_url: b'%PDF-1.7 fake content'}
    sess = FakeSession({dc.INVENTARIO_URL: TOKEN_HTML}, posts, downloads)

    m = dc.descargar_documentos('36057', secciones=('NU',),
                                session_factory=lambda: sess)
    assert m['iddoc'] == 28719
    assert len(m['ficheros']) == 1  # solo sección NU
    f = m['ficheros'][0]
    assert f['status'] == 'downloaded'
    assert f['sha256']
    dest = os.path.join(str(tmp_path), '36057', 'nu003.pdf')
    assert os.path.exists(dest)
    manifest_path = os.path.join(str(tmp_path), '36057', '_manifest.json')
    with open(manifest_path, encoding='utf-8') as fh:
        saved = json.load(fh)
    assert saved['ficheros'][0]['status'] == 'downloaded'


def test_descargar_documentos_marca_no_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, 'NORMATIVA_DIR', str(tmp_path))
    docs = [{'id': 1, 'docnome': 'DOC', 'fechaaddef': '2024-01-01'}]
    iotpu = {
        'datos_xerais': {'filesroot': 'documentos/urbanismo/', 'folder': 'X'},
        'elementos': [
            {'id': 1, 'description': 'NU. NORMATIVA',
             'componentes': [{'id': 1, 'pathesperado': 'doc.pdf',
                             'descripcion': 'D'}]},
        ],
    }
    posts = {dc.QUERY_DOC_URL: docs, dc.IOTPU_URL: iotpu}
    sess = FakeSession({dc.INVENTARIO_URL: TOKEN_HTML}, posts,
                       downloads={'u': b'<html>404</html>'})
    # download() usa sess.get con la url completa; forzar 404-html
    sess.downloads = {}
    sess.pages['x'] = '<html>404</html>'

    def fake_download(url, timeout=120):
        return b'<html>404</html>'
    s = dc.SiotugaSession(session_factory=lambda: sess)
    s.download = fake_download  # type: ignore
    # inyectar sesión preparada a través de factory que devuelve s parcheado
    monkeypatch.setattr(dc, 'SiotugaSession', lambda session_factory=None: s)
    m = dc.descargar_documentos('36057', secciones=('NU',))
    assert m['ficheros'][0]['status'] == 'error'
    assert 'PDF' in m['ficheros'][0]['error']


def test_documento_vigente_prefiere_layer_iddoc():
    docs = [
        {'id': 100, 'docnome': 'VIEJO', 'fechaaddef': '2000-01-01'},
        {'id': 28719, 'docnome': 'VIGENTE', 'fechaaddef': '2025-05-26'},
    ]
    posts = {dc.QUERY_DOC_URL: docs}
    sess = FakeSession({dc.INVENTARIO_URL: TOKEN_HTML}, posts)
    d = dc.documento_vigente('36057',
                             layer_name='_36057_PXOM_202505_AD_3CLAS_28719',
                             session_factory=lambda: sess)
    assert d['id'] == 28719


def test_documento_vigente_sin_layer_usa_fecha():
    docs = [
        {'id': 100, 'docnome': 'VIEJO', 'fechaaddef': '2000-01-01'},
        {'id': 200, 'docnome': 'NUEVO', 'fechaaddef': '2025-05-26'},
    ]
    posts = {dc.QUERY_DOC_URL: docs}
    sess = FakeSession({dc.INVENTARIO_URL: TOKEN_HTML}, posts)
    d = dc.documento_vigente('36057', session_factory=lambda: sess)
    assert d['id'] == 200
