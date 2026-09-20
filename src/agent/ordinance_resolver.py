"""Resolución automática parcela → ordenanza municipal.

La capa 3CLAS de SIOTUGA da la clase de suelo (SUC, SUNT…) pero no el
código de ordenanza (U6, R-1…). Este módulo intenta cerrar la brecha
con los datos oficiales ya disponibles, en orden de fiabilidad:

1. ``subzona`` indicada por el usuario → ``usuario``.
2. Capa vectorial oficial municipal de ordenanzas SUC consultada por
   punto (``src.muni_wfs``, p. ej. GeoServer del Concello de Vigo) →
   ``oficial`` con instrumento declarado; varios polígonos →
   ``ambigua``.
3. Código de ordenanza literal en los atributos oficiales de la zona
   (``id_recinto``, ``denominacion_zona``, ``clasificacion_plan``)
   que case con una ordenanza del PGOM → ``oficial``.
4. Coincidencia por título de la ordenanza frente a la
   ``denominacion_zona``/``uso_zona`` oficial → ``inferida`` (marca
   siempre la necesidad de verificación).
5. Varios candidatos distintos → ``ambigua`` (se listan, no se elige).
6. Nada → ``no_resuelta`` (se listan las ordenanzas disponibles).

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

    # Ámbito de planeamento singular declarado nos atributos
    # oficiais do polígono (obsv «API-106», denom numerado en
    # SUB/SUNC) — a evidencia oficial prevalece sobre unha
    # selección manual e sobre a ordenanza xeral do SUC.
    det_ambito = None
    try:
        from src.ambitos_service import (detectar_ambito_en_clasificacion,
                                         get_ambito,
                                         normalizar_codigo)
        det_ambito = detectar_ambito_en_clasificacion(clas)
        if not det_ambito and ctx.get('ambito_input'):
            code_in = normalizar_codigo(ctx['ambito_input'])
            if code_in:
                det_ambito = {'codigo': code_in,
                              'origen': 'contexto do edificio '
                                        '(atributos oficiais 3CLAS)',
                              'confianza': 'alta'}
    except Exception:
        det_ambito = None

    if ctx.get('subzona') and det_ambito:
        # A parcela está nun ámbito con réxime propio: a ordenanza
        # indicada non aplica — infórmase, non se descarta en silencio.
        ine_amb0 = ctx.get('ine')
        if not ine_amb0 and ctx.get('municipio'):
            try:
                from app.main import _get_ine_for_municipio
                ine_amb0 = _get_ine_for_municipio(ctx['municipio'])
            except Exception:
                ine_amb0 = None
        amb0 = get_ambito(ine_amb0, det_ambito['codigo'])
        nota_amb = (f"A selección «{ctx['subzona']}» non aplica: o "
                    f"punto está no ámbito {det_ambito['codigo']}"
                    + (f" ({amb0['instrumento']})"
                       if amb0 and amb0.get('instrumento') else '')
                    + ', que se rxe polo seu propio instrumento.')
        if amb0 and amb0.get('estado_ambito') != 'eliminada':
            return {'estado': 'oficial', 'ordenanza': None,
                    'confianza': det_ambito.get('confianza') or 'alta',
                    'origen': det_ambito.get('origen'),
                    'ambito': amb0,
                    'candidatas': [det_ambito['codigo']],
                    'nota': nota_amb}
        return {'estado': 'no_resuelta', 'ordenanza': None,
                'confianza': 'ninguna',
                'origen': det_ambito.get('origen'),
                'ambito_detectado': det_ambito['codigo'],
                'ambito': amb0,
                'nota': nota_amb}

    if ctx.get('subzona'):
        if ords:
            key, found = buscar_ordenanza(ords, ctx['subzona'])
            if key is not None:
                # Si la capa oficial confirma el mismo código (p. ej.
                # la subzona venía horneada del GeoServer municipal),
                # el origen real es oficial, no la selección.
                _wfs = ctx.get('ordenanza_wfs') or {}
                if _wfs.get('data_quality') == 'official' \
                        and not _wfs.get('ambigua'):
                    wkey, _wf = buscar_ordenanza(
                        ords, _wfs.get('ordenanza') or '')
                    if wkey == key:
                        return {'estado': 'oficial', 'ordenanza': key,
                                'params': found.get('params') or {},
                                'titulo': found.get('titulo'),
                                'confianza': 'alta',
                                'origen': _wfs.get('fuente'),
                                'instrumento': _wfs.get('instrumento'),
                                'nota': _wfs.get('nota'),
                                'codigo_zona': _wfs.get('ordenanza')}
                return {'estado': 'usuario', 'ordenanza': key,
                        'params': found.get('params') or {},
                        'titulo': found.get('titulo'),
                        'confianza': 'alta',
                        'origen': 'selección del usuario'}
            # Código declarado que no existe en el PGOM (p. ej. un
            # código de piloto obsoleto) → no bloquea la resolución
            # oficial; se reporta la discrepancia vía contradicciones.
        else:
            return {'estado': 'usuario', 'ordenanza': ctx['subzona'],
                    'confianza': 'alta',
                    'origen': 'selección del usuario'}

    # Nivel 1a: ámbito de planeamiento singular detectado en los
    # atributos oficiales SIOTUGA del polígono (obsv «API-106»,
    # denom «201 Guixar…» → SUNC-201). El instrumento incorporado
    # (ED/PERI/PP/PE) rige el ámbito — el Plan Xeral se remite a él —
    # por encima de la ordenanza xeral del SUC.
    try:
        from src.ambitos_service import get_ambito
        ine_amb = ctx.get('ine')
        if not ine_amb and ctx.get('municipio'):
            from app.main import _get_ine_for_municipio
            ine_amb = _get_ine_for_municipio(ctx['municipio'])
        det = det_ambito
        if det:
            amb = get_ambito(ine_amb, det['codigo'])
            wfs = ctx.get('ordenanza_wfs') or {}
            ord_wfs = (wfs.get('ordenanza')
                       if wfs.get('data_quality') == 'official'
                       and not wfs.get('ambigua') else None)
            if amb and amb.get('estado_ambito') != 'eliminada':
                res = {'estado': 'oficial',
                       'ordenanza': None,
                       'confianza': det.get('confianza') or 'alta',
                       'origen': det.get('origen'),
                       'ambito': amb,
                       'candidatas': [det['codigo']]}
                if amb.get('tipo') == 'api':
                    res['nota'] = (
                        f"Ámbito de planeamento incorporado "
                        f"{amb['codigo']}"
                        + (f" ({amb['instrumento']})"
                           if amb.get('instrumento') else '')
                        + ' — ríxese polo seu propio instrumento de '
                          'planeamento, non polas ordenanzas xerais '
                          'do SUC')
                else:
                    res['nota'] = (
                        f"Ámbito {amb['codigo']}"
                        + (f" «{amb['denominacion']}»"
                           if amb.get('denominacion') else '')
                        + ' — ficha oficial do PXOM')
                    ref = (amb.get('parametros') or {}) \
                        .get('ordenanza_referencia')
                    if ref:
                        key, found = buscar_ordenanza(ords, ref)
                        res['ordenanza'] = key or ref
                        res['ordenanza_es_referencia'] = True
                        res['params'] = (found or {}).get('params') or {}
                        res['titulo'] = (found or {}).get('titulo')
                        res['origen'] += (
                            f"; ordenanza de referencia da ficha "
                            f"{amb['codigo']}")
                if ord_wfs:
                    res['ordenanza_municipal_wfs'] = ord_wfs
                return res
            if amb and amb.get('estado_ambito') == 'eliminada':
                return {'estado': 'no_resuelta', 'ordenanza': None,
                        'confianza': 'ninguna',
                        'origen': det.get('origen'),
                        'ambito': amb,
                        'nota': f"El ámbito {amb['codigo']} figura "
                                'eliminado na normativa vixente — '
                                'verificar o instrumento aplicable.'}
            # Código en atributos oficiales pero ficha non indexada:
            # se reporta como candidato oficial sen parámetros.
            wfs_gap_pre = None
            if wfs and wfs.get('data_quality') != 'official' \
                    and wfs.get('error'):
                wfs_gap_pre = wfs.get('error')
            res = {'estado': 'no_resuelta', 'ordenanza': None,
                   'candidatas': [det['codigo']],
                   'confianza': 'ninguna',
                   'origen': det.get('origen'),
                   'ambito_detectado': det['codigo'],
                   'nota': f"Os atributos oficiais da zona indican o "
                           f"ámbito {det['codigo']}, pero a súa ficha "
                           f"non está indexada — verificar no "
                           f"planeamento municipal."}
            if wfs_gap_pre:
                res['nota'] += f" (Capa de ordenanzas: {wfs_gap_pre})"
            if ord_wfs:
                res['ordenanza_municipal_wfs'] = ord_wfs
            return res
    except Exception:
        pass

    # Nivel 1b: capa vectorial oficial municipal (WFS punto-en-
    # polígono). Es la fuente más fiable: geometría oficial del
    # planeamiento, no una heurística sobre atributos.
    wfs = ctx.get('ordenanza_wfs') or {}
    if wfs.get('data_quality') == 'official':
        if wfs.get('ambigua'):
            return {'estado': 'ambigua', 'ordenanza': None,
                    'candidatas': wfs.get('candidatas') or [],
                    'confianza': 'baja',
                    'origen': wfs.get('fuente'),
                    'instrumento': wfs.get('instrumento')}
        if wfs.get('ordenanza'):
            code = wfs['ordenanza']
            key, found = buscar_ordenanza(ords, code)
            return {'estado': 'oficial', 'ordenanza': key or code,
                    'params': (found or {}).get('params') or {},
                    'titulo': (found or {}).get('titulo'),
                    'confianza': 'alta',
                    'origen': wfs.get('fuente'),
                    'instrumento': wfs.get('instrumento'),
                    'nota': wfs.get('nota'),
                    'codigo_zona': code,
                    'candidatas': [key or code]}

    if not ords:
        return {'estado': 'no_resuelta', 'ordenanza': None,
                'candidatas': [], 'confianza': 'ninguna',
                'origen': 'sin ordenanzas extraídas del municipio'}

    # Capa oficial consultada pero sin polígono contenedor (hueco de
    # cobertura o ámbito de planeamiento singular): se conserva la
    # traza para explicar el "no resuelta" — nunca se toma el
    # polígono más cercano.
    wfs_gap = None
    if wfs and wfs.get('data_quality') != 'official' and wfs.get('error'):
        wfs_gap = {'error': wfs.get('error'),
                   'fuente': wfs.get('fuente'),
                   'instrumento': wfs.get('instrumento')}

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

    res = {'estado': 'no_resuelta', 'ordenanza': None,
           'candidatas': sorted(ords), 'confianza': 'ninguna',
           'origen': 'sin correspondencia automática',
           'ordenanzas_disponibles': sorted(ords)}
    if wfs_gap:
        res['nota'] = (
            f"La capa oficial consultada no cubre este punto "
            f"({wfs_gap['error']}). Puede tratarse de un ámbito de "
            f"planeamiento singular o de un hueco de la cartografía — "
            f"verificar en el visor municipal o el planeamiento "
            f"detallado aplicable.")
        res['fuente_capa_oficial'] = wfs_gap.get('fuente')
    return res
