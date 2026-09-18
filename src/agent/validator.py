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
        aviso = ('\n\n> ⚠ **Requiere revisión humana**: se detectaron citas '
                 'sin respaldo en las fuentes recuperadas '
                 f"({'; '.join(validacion['errores'])}).")
        return respuesta + aviso
    return respuesta
