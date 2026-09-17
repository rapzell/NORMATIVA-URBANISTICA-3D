"""Tests del RAG normativo sobre PDFs oficiales."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import normativa_rag as rag


def _make_pdf(path, pages):
    """PDF mínimo con texto por página usando pypdf + reportlab-free."""
    from pypdf import PdfWriter, PdfReader
    from pypdf.generic import (
        DecodedStreamObject, DictionaryObject, NameObject, ArrayObject,
        TextStringObject, NumberObject,
    )
    writer = PdfWriter()
    for text in pages:
        writer.add_blank_page(width=612, height=792)
    # pypdf no puede escribir texto fácilmente; usamos un enfoque con
    # contenido PDF crudo por página.
    import io
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        content = DecodedStreamObject()
        safe = text.replace('(', r'\(').replace(')', r'\)')
        content.set_data(
            f"BT /F1 12 Tf 50 700 Td ({safe}) Tj ET".encode('latin-1', 'replace'))
        page[NameObject('/Contents')] = content
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({
                NameObject('/F1'): DictionaryObject({
                    NameObject('/Type'): NameObject('/Font'),
                    NameObject('/Subtype'): NameObject('/Type1'),
                    NameObject('/BaseFont'): NameObject('/Helvetica'),
                })
            })
        })
    with open(path, 'wb') as f:
        writer.write(f)


def _setup_municipio(tmp_path, monkeypatch, ficheros_manifest):
    muni_dir = tmp_path / '36057'
    muni_dir.mkdir(parents=True)
    manifest = {
        'ine': '36057', 'iddoc': 28719,
        'denominacion': 'PXOM VIGO',
        'ficheros': ficheros_manifest,
    }
    (muni_dir / '_manifest.json').write_text(
        json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(rag, 'NORMATIVA_DIR', str(tmp_path))
    import src.siotuga.document_client as dc
    monkeypatch.setattr(dc, 'NORMATIVA_DIR', str(tmp_path))
    return muni_dir


def test_indexar_y_consultar_devuelve_citas(tmp_path, monkeypatch):
    muni = _setup_municipio(tmp_path, monkeypatch, [])
    # crear PDF y manifest coherente
    pdf_path = muni / 'nu003.pdf'
    _make_pdf(str(pdf_path), [
        'La altura maxima de edificacion sera de 12 metros en zona residencial.',
        'El retranqueo minimo a lindero sera de 3 metros.',
    ])
    manifest = {
        'ine': '36057', 'iddoc': 28719, 'denominacion': 'PXOM VIGO',
        'ficheros': [{
            'pathesperado': 'nu003.pdf', 'seccion': 'NU',
            'seccion_desc': 'NU. NORMATIVA', 'status': 'downloaded',
            'local_path': str(pdf_path), 'sha256': 'x',
            'url': 'http://example/nu003.pdf',
        }],
    }
    (muni / '_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    idx = rag.indexar_municipio('36057')
    assert len(idx['chunks']) >= 2

    r = rag.consultar('36057', 'altura maxima edificacion', use_llm=False)
    assert r['data_quality'] == 'official'
    assert r['citas'], 'debe devolver citas'
    c = r['citas'][0]
    assert c['fichero'] == 'nu003.pdf'
    assert c['pagina'] == 1
    assert 'altura' in c['extracto'].lower()


def test_consulta_sin_pdfs_unavailable(tmp_path, monkeypatch):
    _setup_municipio(tmp_path, monkeypatch, [])
    r = rag.consultar('36057', 'altura maxima', use_llm=False)
    assert r['data_quality'] == 'unavailable'
    assert 'normativa-docs' in r['instrucciones']


def test_index_se_reusa_si_manifest_igual(tmp_path, monkeypatch):
    muni = _setup_municipio(tmp_path, monkeypatch, [])
    pdf_path = muni / 'nu.pdf'
    _make_pdf(str(pdf_path), ['Texto de prueba con retranqueo de 3 metros.'])
    manifest = {
        'ine': '36057', 'iddoc': 1,
        'ficheros': [{'pathesperado': 'nu.pdf', 'seccion': 'NU',
                      'status': 'downloaded', 'local_path': str(pdf_path),
                      'sha256': 'abc'}],
    }
    (muni / '_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    idx1 = rag.indexar_municipio('36057')
    n1 = len(idx1['chunks'])
    # segunda llamada: carga desde disco, no re-extrae
    idx2 = rag.indexar_municipio('36057')
    assert idx2['manifest_key'] == idx1['manifest_key']
    assert len(idx2['chunks']) == n1


def test_split_chunks_respeta_longitud():
    texto = 'Frase uno. ' * 300  # ~3300 chars
    chunks = rag._split_chunks(texto)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= rag.MAX_CHUNK_CHARS + 50


def test_norm_elimina_stopwords_y_acentos():
    toks = rag._norm('¿Cuál es la altura máxima permitida en Vigo?')
    assert 'altura' in toks
    assert 'maxima' in toks
    assert 'vigo' in toks
    assert 'la' not in toks and 'es' not in toks


def test_extracto_centra_termino():
    texto = 'A' * 200 + ' retranqueo ' + 'B' * 200
    frag = rag._extracto(texto, ['retranqueo'], width=100)
    assert 'retranqueo' in frag
