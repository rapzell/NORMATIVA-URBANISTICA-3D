"""Cliente del inventario documental SIOTUGA (PDFs oficiales del planeamiento).

SIOTUGA publica los documentos originales de cada instrumento de
planeamiento (normativa urbanística, planos de ordenación, catálogo,
etc.) en el inventario web ``/siotuga/inventario``. Este módulo:

1. Abre sesión contra el inventario (PHPSESSID + token CSRF del HTML).
2. Lista los documentos del municipio vía ``query_document.php``
   (idclase 14 = planes xerais, 13 = planes de desarrollo,
   16 = planes especiales/HCO, 18 = delimitación de núcleos rurales).
3. Obtiene el detalle de cada instrumento vía ``getIOTPU.php``
   (``datos_xerais`` + ``elementos[].componentes[]`` con ``pathesperado``).
4. Descarga los PDFs a ``datos/normativa/{ine}/`` y mantiene un
   manifiesto JSON por municipio con sha256, URL fuente y fecha.

URL de descarga real (verificada)::

    https://siotuga.xunta.gal/siotuga/{filesroot}{folder}/documents/{pathesperado}

Trazabilidad: cada PDF descargado queda registrado en el manifiesto con
``source_url``, ``sha256``, ``component_id``, sección (NU, PORD, CAT...)
y fecha de descarga. Los documentos son los originales aprobados: a
diferencia de la capa vectorial WFS, tienen validez oficial.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Callable

BASE = "https://siotuga.xunta.gal/siotuga"
INVENTARIO_URL = f"{BASE}/inventario"
QUERY_DOC_URL = f"{BASE}/assets/inventario/query_document.php"
IOTPU_URL = f"{BASE}/assets/inventario/getIOTPU.php"

# Clases documentales del inventario SIOTUGA
IDCLASE_XERAL = 14       # planes xerais (PXOM / PXOU)
IDCLASE_DESENVOLVEMENTO = 13  # planes parciales, estudios detalle
IDCLASE_HCO = 16         # planeamiento especial / HCO
IDCLASE_NUCLEOS = 18     # delimitación de núcleos rurales
CLASES = (IDCLASE_XERAL, IDCLASE_DESENVOLVEMENTO, IDCLASE_HCO, IDCLASE_NUCLEOS)

NORMATIVA_DIR = os.path.join('datos', 'normativa')
MANIFEST_TTL_S = 24 * 3600  # la sesión/documentos se refrescan a diario

_TOKEN_RE = re.compile(r"id=['\"]token['\"][^>]*value=['\"]([^'\"]+)['\"]")


class SiotugaSession:
    """Sesión autenticada contra el inventario SIOTUGA.

    El portal exige el par (PHPSESSID, token) que emite la página del
    inventario; las llamadas a los PHP sin la cookie de sesión
    correspondiente devuelven ``tokenIncorrecto``.
    """

    def __init__(self, session_factory: Callable[[], Any] | None = None):
        if session_factory is not None:
            self._s = session_factory()
        else:
            import requests
            self._s = requests.Session()
        self.token: str | None = None

    def open(self, ine_code: str, lang: str = 'es_ES') -> str:
        """Carga la página del inventario y extrae el token CSRF."""
        r = self._s.get(
            INVENTARIO_URL,
            params={'concello': ine_code, 'lang': lang},
            timeout=30,
        )
        r.raise_for_status()
        m = _TOKEN_RE.search(r.text)
        if not m:
            raise RuntimeError('SIOTUGA no devolvió token de sesión')
        self.token = m.group(1)
        return self.token

    def _post(self, url: str, data: str, timeout: int = 30) -> Any:
        if not self.token:
            raise RuntimeError('Sesión SIOTUGA no abierta (llama a open)')
        r = self._s.post(
            url, data=data, timeout=timeout,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict) and 'tokenIncorrecto' in str(payload):
            raise RuntimeError('SIOTUGA rechazó el token de sesión')
        return payload

    def query_documents(self, ine_code: str, idclase: int = IDCLASE_XERAL) -> list:
        """Lista documentos del municipio para una clase documental."""
        payload = self._post(
            QUERY_DOC_URL,
            f'id={ine_code}&token={self.token}&idclase={idclase}',
        )
        if isinstance(payload, list):
            return payload
        return [payload] if payload else []

    def get_iotpu(self, iddoc: int, idp: int = 0, lang: str = 'es_ES') -> dict:
        """Detalle completo del instrumento (metadatos + componentes)."""
        return self._post(
            IOTPU_URL,
            f'iddoc={iddoc}&idp={idp}&lang={lang}&token={self.token}',
        )

    def download(self, url: str, timeout: int = 120) -> bytes:
        r = self._s.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content


def document_url(filesroot: str, folder: str, pathesperado: str) -> str:
    """Construye la URL pública del PDF a partir de los campos IOTPU."""
    root = filesroot.lstrip('/')
    return f'{BASE}/{root}{folder}/documents/{pathesperado}'


def _fecha(doc: dict) -> str:
    return doc.get('fechaaddef') or doc.get('fechadog') or doc.get('fechabop') or ''


def listar_documentos(ine_code: str,
                      session_factory: Callable[[], Any] | None = None,
                      clases: tuple = CLASES) -> dict:
    """Documentos de planeamiento del municipio, agrupados por clase.

    Devuelve ``{ine, documentos: [...], por_clase: {idclase: n}}``; cada
    documento lleva ``id``, ``docnome``, ``figura``, ``fechaaddef``,
    ``fechabop``, ``fechadog``, ``fechanormativabop`` e ``idclase``.
    """
    sess = SiotugaSession(session_factory)
    sess.open(ine_code)
    docs: list[dict] = []
    por_clase: dict[int, int] = {}
    for idclase in clases:
        try:
            items = sess.query_documents(ine_code, idclase)
        except Exception:
            items = []
        por_clase[idclase] = len(items)
        for d in items:
            if isinstance(d, dict):
                d['idclase'] = idclase
                docs.append(d)
    docs.sort(key=_fecha, reverse=True)
    return {'ine': ine_code, 'documentos': docs, 'por_clase': por_clase}


def documento_vigente(ine_code: str, layer_name: str | None = None,
                      session_factory: Callable[[], Any] | None = None) -> dict | None:
    """Instrumento xeral vigente del municipio.

    Si se pasa ``layer_name`` (p.ej. ``_36057_PXOM_202505_AD_3CLAS_28719``)
    prefiere el documento cuyo ``id`` coincide con el sufijo iddoc de la
    capa activa; si no, el de ``fechaaddef`` más reciente entre los
    documentos de clase xeral.
    """
    sess = SiotugaSession(session_factory)
    sess.open(ine_code)
    try:
        docs = sess.query_documents(ine_code, IDCLASE_XERAL)
    except Exception:
        return None
    if not docs:
        return None
    if layer_name:
        m = re.search(r'_(\d+)$', layer_name)
        if m:
            want = int(m.group(1))
            for d in docs:
                if d.get('id') == want:
                    return d
    docs.sort(key=_fecha, reverse=True)
    return docs[0]


def componentes_documento(iddoc: int, ine_code: str,
                          session: SiotugaSession | None = None,
                          session_factory: Callable[[], Any] | None = None) -> dict:
    """Metadatos y componentes (ficheros) de un instrumento.

    Devuelve ``{iddoc, datos_xerais, secciones: [{id, descripcion,
    componentes: [{id, pathesperado, descripcion, url}]}]}`` con la URL
    de descarga ya resuelta en cada componente.
    """
    sess = session or SiotugaSession(session_factory)
    if not sess.token:
        sess.open(ine_code)
    iotpu = sess.get_iotpu(iddoc)
    if not isinstance(iotpu, dict):
        return {'iddoc': iddoc, 'error': 'respuesta IOTPU vacía', 'secciones': []}
    dx = iotpu.get('datos_xerais') or {}
    filesroot = dx.get('filesroot') or 'documentos/urbanismo/'
    folder = dx.get('folder') or ''
    secciones = []
    for el in iotpu.get('elementos') or []:
        comps = []
        for c in el.get('componentes') or []:
            path = c.get('pathesperado')
            if not path:
                continue
            comps.append({
                'id': c.get('id'),
                'pathesperado': path,
                'descripcion': c.get('descripcion'),
                'url': document_url(filesroot, folder, path),
            })
        secciones.append({
            'id': el.get('id'),
            'descripcion': el.get('description') or el.get('descripcion'),
            'componentes': comps,
        })
    return {
        'iddoc': iddoc,
        'denominacion': iotpu.get('denominacion') or dx.get('denominacion'),
        'figura': iotpu.get('figura') or dx.get('figura'),
        'datos_xerais': dx,
        'secciones': secciones,
    }


def _manifest_path(ine_code: str) -> str:
    return os.path.join(NORMATIVA_DIR, ine_code, '_manifest.json')


def _load_manifest(ine_code: str) -> dict:
    path = _manifest_path(ine_code)
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'ine': ine_code, 'ficheros': []}


def _save_manifest(ine_code: str, manifest: dict) -> None:
    path = _manifest_path(ine_code)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def manifiesto_municipio(ine_code: str) -> dict:
    """Manifiesto local de PDFs descargados del municipio."""
    return _load_manifest(ine_code)


def registrar_pdf_externo(ine_code: str, fichero: str, url: str,
                          seccion: str = 'NU',
                          descripcion: str | None = None) -> dict:
    """Registra en el manifiesto un PDF descargado fuera de SIOTUGA
    (p. ej. la NU del PXOM desde la web municipal). Así
    ``indexar_municipio`` lo incluye en el RAG y ``normativa_params``
    lo procesa, conservando la URL oficial para las citas.
    """
    import hashlib
    dest = os.path.join(NORMATIVA_DIR, str(ine_code), fichero)
    manifest = _load_manifest(ine_code)
    ficheros = [f for f in manifest.get('ficheros', [])
                if f.get('pathesperado') != fichero]
    entry = {
        'pathesperado': fichero,
        'seccion': seccion,
        'seccion_desc': descripcion or
                        'Normativa urbanística (web municipal)',
        'component_id': None,
        'descripcion': descripcion or fichero,
        'url': url,
        'local_path': dest,
    }
    if os.path.exists(dest):
        with open(dest, 'rb') as fh:
            content = fh.read()
        entry.update({
            'status': 'downloaded',
            'sha256': hashlib.sha256(content).hexdigest(),
            'size': len(content),
            'downloaded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                           time.gmtime()),
        })
    else:
        entry['status'] = 'error'
        entry['error'] = 'fichero no encontrado en disco'
    ficheros.append(entry)
    manifest['ficheros'] = ficheros
    manifest['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                         time.gmtime())
    _save_manifest(ine_code, manifest)
    return entry


def descargar_documentos(
    ine_code: str,
    iddoc: int | None = None,
    secciones: tuple[str, ...] | None = None,
    layer_name: str | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> dict:
    """Descarga los PDFs oficiales del instrumento del municipio.

    - ``iddoc``: documento concreto; si es ``None`` se usa el vigente.
    - ``secciones``: prefijos de sección a descargar (p.ej. ``('NU',)``);
      ``None`` descarga todas las secciones del instrumento.
    - Devuelve el manifiesto actualizado ``{ine, iddoc, ficheros: [...]}``
      donde cada fichero tiene ``pathesperado``, ``seccion``, ``url``,
      ``sha256``, ``size``, ``downloaded_at`` y ``status``
      (``downloaded`` | ``cached`` | ``error``).
    """
    sess = SiotugaSession(session_factory)
    sess.open(ine_code)

    es_vigente = iddoc is None
    doc = None
    if iddoc is None:
        try:
            xeral = sess.query_documents(ine_code, IDCLASE_XERAL)
        except Exception:
            xeral = []
        if layer_name:
            m = re.search(r'_(\d+)$', layer_name)
            if m:
                want = int(m.group(1))
                doc = next((d for d in xeral if d.get('id') == want), None)
        if doc is None and xeral:
            xeral.sort(key=_fecha, reverse=True)
            doc = xeral[0]
        if doc is None:
            return {'ine': ine_code, 'error': 'sin documentos xerais',
                    'ficheros': []}
        iddoc = doc.get('id')

    iddoc = int(iddoc)
    det = componentes_documento(iddoc, ine_code, session=sess)
    manifest = _load_manifest(ine_code)
    if es_vigente:
        manifest['iddoc'] = iddoc
        manifest['denominacion'] = det.get('denominacion')
        manifest['figura'] = det.get('figura')
        manifest['datos_xerais'] = det.get('datos_xerais')
    else:
        instrumentos = manifest.setdefault('instrumentos', {})
        instrumentos[str(iddoc)] = {
            'denominacion': det.get('denominacion'),
            'figura': det.get('figura')}
    manifest['source'] = 'SIOTUGA inventario documental'
    manifest['data_quality'] = 'official'

    out_dir = os.path.join(NORMATIVA_DIR, ine_code)
    os.makedirs(out_dir, exist_ok=True)
    known = {f.get('pathesperado'): f for f in manifest.get('ficheros', [])}
    ficheros: list[dict] = []
    prefixes = tuple(s.upper() for s in secciones) if secciones else None

    for sec in det.get('secciones') or []:
        sec_desc = sec.get('descripcion') or ''
        sec_code = sec_desc.split('.')[0].strip().upper()
        if prefixes and not any(sec_code.startswith(p) for p in prefixes):
            continue
        for comp in sec.get('componentes') or []:
            path = comp['pathesperado']
            dest = os.path.join(out_dir, path)
            prev = known.get(path)
            entry = {
                'pathesperado': path,
                'seccion': sec_code,
                'seccion_desc': sec_desc,
                'component_id': comp.get('id'),
                'iddoc': iddoc,
                'descripcion': comp.get('descripcion'),
                'url': comp['url'],
                'local_path': dest,
            }
            try:
                if prev and os.path.exists(dest):
                    entry.update({
                        'status': 'cached',
                        'sha256': prev.get('sha256'),
                        'size': os.path.getsize(dest),
                        'downloaded_at': prev.get('downloaded_at'),
                    })
                else:
                    content = sess.download(comp['url'])
                    if not content.startswith(b'%PDF'):
                        entry['status'] = 'error'
                        entry['error'] = 'respuesta no es PDF'
                    else:
                        with open(dest, 'wb') as f:
                            f.write(content)
                        entry.update({
                            'status': 'downloaded',
                            'sha256': hashlib.sha256(content).hexdigest(),
                            'size': len(content),
                            'downloaded_at': time.strftime(
                                '%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        })
            except Exception as e:
                entry['status'] = 'error'
                entry['error'] = str(e)
            ficheros.append(entry)

    # Merge: los ficheros de otros instrumentos ya descargados (p.ej.
    # el PXOM vigente al bajar el documento de un API) se conservan.
    new_paths = {e['pathesperado'] for e in ficheros}
    otros = [f for f in manifest.get('ficheros', [])
             if f.get('pathesperado') not in new_paths
             and f.get('iddoc') != iddoc]
    manifest['ficheros'] = otros + ficheros
    manifest['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    _save_manifest(ine_code, manifest)
    return manifest
