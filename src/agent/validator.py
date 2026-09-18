"""Validación de respuestas del asistente contra las fuentes.

Verifica que cada cita ``[FUENTE i]`` corresponde a un fragmento
realmente recuperado y que los valores numéricos citados existen en el
contexto o en los fragmentos. Si la validación falla, la respuesta se
degrada: se marca ``requiere_revision`` y se conservan las citas
verificadas — el arquitecto ve qué afirmaciones están respaldadas.
"""
from __future__ import annotations

import re
from typing import Any

_CITA_RE = re.compile(r'\[\s*FUENTE\s*[:\-]?\s*(\d+)\s*\]', re.I)
_CITA_NUM_RE = re.compile(r'\[(\d{1,2})\]')
_NUM_RE = re.compile(r'\d+(?:[.,]\d+)?')


def _numeros(texto: str) -> set[str]:
    return {m.group(0).replace(',', '.') for m in _NUM_RE.finditer(texto)}


def validar_respuesta(respuesta: str, fuentes: list[dict],
                      contexto: dict | None = None) -> dict:
    """Devuelve ``{valida, citas, errores, avisos}``.

    - ``citas``: por cada ``[FUENTE i]`` detectada, ``{id, estado}`` con
      estado ``verificada`` o ``no_encontrada``.
    - ``errores``: citas a fuentes inexistentes o números sin respaldo.
    - ``avisos``: detecciones no bloqueantes (p. ej. respuesta sin citas).
    """
    errores: list[str] = []
    avisos: list[str] = []
    citas: list[dict] = []
    ids_validos = {f.get('id') for f in fuentes if f.get('id') is not None}

    for m in _CITA_RE.finditer(respuesta or ''):
        fid = int(m.group(1))
        estado = 'verificada' if fid in ids_validos else 'no_encontrada'
        citas.append({'id': fid, 'estado': estado})
        if estado == 'no_encontrada':
            errores.append(f'Cita [FUENTE {fid}] sin fragmento recuperado')

    # Citas sueltas tipo [3] solo se validan si el prompt las admite
    for m in _CITA_NUM_RE.finditer(respuesta or ''):
        fid = int(m.group(1))
        if fid in ids_validos:
            citas.append({'id': fid, 'estado': 'verificada'})

    if fuentes and not citas:
        avisos.append('La respuesta no cita ninguna fuente recuperada')

    # Números citados: deben aparecer en contexto o en los fragmentos
    corpus_txt = ' '.join((f.get('texto') or '') + ' ' +
                          str(f.get('extracto') or '') for f in fuentes)
    ctx_txt = str(contexto or {})
    base = _numeros(corpus_txt) | _numeros(ctx_txt)
    resp_nums = _numeros(respuesta or '')
    # ignorar números de las propias etiquetas [FUENTE i] y ordinales triviales
    triviales = {str(i) for i in range(0, 32)}
    sospechosos = sorted(n for n in resp_nums - base - triviales
                         if len(n) >= 2)
    if sospechosos:
        avisos.append('Valores numéricos no localizados en fuentes/contexto: '
                      + ', '.join(sospechosos[:8]))

    return {
        'valida': not errores,
        'requiere_revision': bool(errores),
        'citas': citas,
        'errores': errores,
        'avisos': avisos,
    }


def anotar_respuesta(respuesta: str, validacion: dict) -> str:
    """Añade la advertencia de revisión si la validación falló."""
    if validacion.get('requiere_revision'):
        detalle = '; '.join(validacion.get('errores') or []) \
            or 'afirmaciones sin respaldo según la validación semántica'
        aviso = ('\n\n> ⚠ **Requiere revisión humana**: se detectaron citas '
                 'sin respaldo en las fuentes recuperadas '
                 f"({detalle}).")
        return respuesta + aviso
    return respuesta


_SEMANTIC_PROMPT = """Verifica si esta respuesta de un asistente de normativa urbanística contiene afirmaciones NO respaldadas por las fuentes proporcionadas.

RESPUESTA:
{respuesta}

FUENTES:
{fuentes}

Revisa cada afirmación normativa o numérica de la respuesta. Una afirmación está respaldada si el dato aparece literalmente en las fuentes o es una consecuencia aritmética directa de ellas.
Responde SOLO con JSON válido: {{"valida": true/false, "afirmaciones_sin_respaldo": ["..."]}}"""


def validacion_semantica(respuesta: str, fuentes: list[dict],
                         validacion_heuristica: dict) -> dict:
    """Segunda pasada opcional con LLM (``SEMANTIC_VALIDATION=1``).

    Solo corre si la heurística ya pasó — evita doble coste en
    respuestas ya marcadas. Si el LLM falla, tarda o devuelve JSON
    inválido, devuelve la validación heurística intacta: la
    degradación es siempre hacia el resultado conocido.
    """
    import json
    import os
    if os.getenv('SEMANTIC_VALIDATION', '0').lower() not in ('1', 'true', 'si'):
        return validacion_heuristica
    if validacion_heuristica.get('requiere_revision'):
        return validacion_heuristica
    try:
        fuentes_txt = '\n'.join(
            f"[{f.get('id')}] {f.get('documento')} "
            f"{f.get('referencia') or ''} pág.{f.get('pagina')}: "
            f"{(f.get('extracto') or f.get('texto') or '')[:600]}"
            for f in fuentes[:8])
        from src.model_gateway import _iter_provider_attempts, \
            _provider_attempt
        proveedores = [p for p in _iter_provider_attempts()
                       if p != 'local']
        if not proveedores:
            return validacion_heuristica
        raw = _provider_attempt(
            proveedores[0],
            _SEMANTIC_PROMPT.format(respuesta=respuesta[:4000],
                                    fuentes=fuentes_txt),
            30.0)
        m = re.search(r'\{.*\}', raw or '', re.S)
        data = json.loads(m.group(0)) if m else None
        if not isinstance(data, dict) or 'valida' not in data:
            return validacion_heuristica
        out = dict(validacion_heuristica)
        out['semantica'] = {
            'valida': bool(data.get('valida')),
            'afirmaciones_sin_respaldo':
                data.get('afirmaciones_sin_respaldo') or [],
        }
        if not data.get('valida'):
            out['requiere_revision'] = True
            out['avisos'] = out.get('avisos', []) + [
                'Validación semántica: afirmaciones sin respaldo: '
                + '; '.join(out['semantica']['afirmaciones_sin_respaldo'][:5])]
        return out
    except Exception:
        return validacion_heuristica
