"""Expansión de consulta con sinónimos urbanísticos ES/GL.

BM25 falla con variantes léxicas ("azotea"/"cubierta",
"recuado"/"retranqueo", "edificabilidade"/"edificabilidad").
Expandir la consulta antes del BM25 mejora el recall sin
dependencias externas. También ofrece un boost por tipo de
pregunta sobre los fragmentos recuperados.
"""
from __future__ import annotations

import re
import unicodedata

SINONIMOS_URBANISTICOS = {
    'retranqueo': ['recuado', 'retiro', 'separación a linderos',
                   'lindero', 'setback'],
    'ocupación': ['ocupación máxima', 'superficie ocupada', 'huella',
                  'ocupacion'],
    'edificabilidad': ['edificabilidade', 'aprovechamiento',
                       'aproveitamento', 'coeficiente'],
    'altura': ['altura máxima', 'altura de cornisa', 'altura total',
               'altitude máxima'],
    'piscina': ['piscina', 'vaso', 'instalación auxiliar',
                'acumulación de agua'],
    'azotea': ['cubierta', 'terraza', 'cuberta'],
    'vivienda': ['vivenda', 'unidad residencial', 'apartamento',
                 'domicilio'],
    'local': ['local comercial', 'bajo comercial', 'oficina',
              'uso terciario'],
    'cambio de uso': ['cambio de uso', 'rehabilitación', 'conversión',
                      'transformación'],
    'suelo': ['solo', 'clasificación', 'clase de suelo'],
    'parcela': ['parcela', 'finca', 'solar', 'predio'],
    'normativa': ['ordenanza', 'normas', 'planeamiento', 'PGOM',
                  'plan xeral'],
    'anexo': ['anexo', 'auxiliar', 'complementario', 'caseta'],
}

_TIPO_KEYWORDS = {
    'piscina': ['piscina', 'instalación', 'auxiliar', 'ocupación',
                'acumulación de auga', 'depuración'],
    'cambio de uso': ['habitabilidad', 'nhv', '128/2023', 'vivenda',
                      'vivienda', 'cambio de uso', 'acondicionamiento'],
    'retranqueo': ['retranqueo', 'recuado', 'lindero', 'retiro'],
    'ocupación': ['ocupación', 'ocupación máxima', 'huella'],
    'edificabilidad': ['edificabilidad', 'edificabilidade',
                       'aprovechamiento'],
    'altura': ['altura', 'cornisa', 'plantas'],
}


def _norm(s: str) -> str:
    """Minúsculas sin acentos — para casar 'ocupacion'/'ocupación'."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', (s or '').lower())
        if unicodedata.category(c) != 'Mn')


def expandir_query(query: str) -> str:
    """Añade sinónimos conocidos a la consulta para el BM25.
    Conserva la query original intacta al principio."""
    q = _norm(query)
    terminos = [query or '']
    for clave, syns in SINONIMOS_URBANISTICOS.items():
        variantes = [clave] + syns
        if any(_norm(v) in q for v in variantes):
            terminos.extend(variantes)
    return ' '.join(dict.fromkeys(t for t in terminos if t))


def boost_por_tipo(pregunta: str, fragmentos: list[dict]) -> list[dict]:
    """Reordena fragmentos: +boost a los que contienen keywords del
    tipo de pregunta detectado. Conserva el score original."""
    q = (pregunta or '').lower()
    keywords = []
    for tema, kws in _TIPO_KEYWORDS.items():
        if tema in q:
            keywords = kws
            break
    if not keywords:
        return fragmentos
    for f in fragmentos:
        txt = ((f.get('texto') or '') + ' ' +
               (f.get('extracto') or '')).lower()
        hits = sum(1 for k in keywords if _norm(k) in _norm(txt))
        f['score'] = f.get('score', 0) + hits * 1.5
    return sorted(fragmentos, key=lambda x: x.get('score', 0),
                  reverse=True)
