"""Resolución automática parcela → ordenanza municipal.

La capa 3CLAS de SIOTUGA da la clase de suelo (SUC, SUNT…) pero no el
código de ordenanza (U6, R-1…). Este módulo intenta cerrar la brecha
con los datos oficiales ya disponibles, en orden de fiabilidad:

1. ``subzona`` indicada por el usuario → ``usuario``.
2. Código de ordenanza literal en los atributos oficiales de la zona
   (``id_recinto``, ``denominacion_zona``, ``clasificacion_plan``)
   que case con una ordenanza del PGOM → ``oficial``.
3. Coincidencia por título de la ordenanza frente a la
   ``denominacion_zona``/``uso_zona`` oficial → ``inferida`` (marca
   siempre la necesidad de verificación).
4. Varios candidatos distintos → ``ambigua`` (se listan, no se elige).
5. Nada → ``no_resuelta`` (se listan las ordenanzas disponibles).

Jamás se inventa una ordenanza ni se presenta una inferencia como
dato oficial de conformidad.
"""
from __future__ import annotations

import re
import unicodedata

_CODE_RE = re.compile(r'\b([A-Z]{1,4}\.?\d{1,2}(?:\.\d+)?)\b')


def _norm(s: str) -> str:
    t = ''.join(
        c for c in unicodedata.normalize('NFD', (s or '').upper())
        if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^A-Z0-9 ]+', ' ', t)


def _codes_en(texto: str) -> list[str]:
    return [m.group(1) for m in _CODE_RE.finditer(texto or '')]


def resolver_ordenanza(ctx: dict) -> dict:
    """Devuelve ``{estado, ordenanza, params, candidatas, confianza,
    origen, nota}`` a partir del contexto de herramientas."""
    ords = (ctx.get('ordenanzas') or {}).get('ordenanzas') or {}
    clas = ctx.get('clasificacion') or {}
    from src.normativa_params import buscar_ordenanza

    if ctx.get('subzona'):
        return {'estado': 'usuario', 'ordenanza': ctx['subzona'],
                'confianza': 'alta', 'origen': 'selección del usuario'}

    if not ords:
        return {'estado': 'no_resuelta', 'ordenanza': None,
                'candidatas': [], 'confianza': 'ninguna',
                'origen': 'sin ordenanzas extraídas del municipio'}

    # Nivel 2: código literal en atributos oficiales de la zona
    encontradas: dict[str, str] = {}  # codigo -> origen
    for campo in ('id_recinto', 'denominacion_zona', 'clasificacion_plan'):
        for tok in _codes_en(str(clas.get(campo) or '')):
            key, found = buscar_ordenanza(ords, tok)
            if found:
                encontradas.setdefault(key, f'{campo} oficial SIOTUGA')

    if len(encontradas) == 1:
        code = next(iter(encontradas))
        return {'estado': 'oficial', 'ordenanza': code,
                'params': (ords[code].get('params') or {}),
                'titulo': ords[code].get('titulo'),
                'confianza': 'alta',
                'origen': encontradas[code],
                'candidatas': [code]}
    if len(encontradas) > 1:
        return {'estado': 'ambigua', 'ordenanza': None,
                'candidatas': sorted(encontradas),
                'confianza': 'baja',
                'origen': 'varios códigos en atributos de la zona'}

    # Nivel 3: por título de la ordenanza vs denominación/uso oficial
    texto_zona = _norm(' '.join(str(clas.get(c) or '') for c in
                                ('denominacion_zona', 'uso_zona')))
    titulos: list[str] = []
    if texto_zona.strip():
        for code, datos in ords.items():
            titulo = _norm(datos.get('titulo') or '')
            if len(titulo) >= 8 and titulo in texto_zona:
                titulos.append(code)

    if len(titulos) == 1:
        code = titulos[0]
        return {'estado': 'inferida', 'ordenanza': code,
                'params': (ords[code].get('params') or {}),
                'titulo': ords[code].get('titulo'),
                'confianza': 'media',
                'origen': 'título coincidente con la denominación '
                          'oficial de la zona — verificar',
                'candidatas': titulos}
    if len(titulos) > 1:
        return {'estado': 'ambigua', 'ordenanza': None,
                'candidatas': sorted(titulos), 'confianza': 'baja',
                'origen': 'varios títulos compatibles con la zona'}

    return {'estado': 'no_resuelta', 'ordenanza': None,
            'candidatas': sorted(ords), 'confianza': 'ninguna',
            'origen': 'sin correspondencia automática',
            'ordenanzas_disponibles': sorted(ords)}
