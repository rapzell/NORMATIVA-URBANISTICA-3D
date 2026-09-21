"""Clasificador de intención con LLM (few-shot) y fallback a regex.

El regex cubre los patrones habituales a coste cero; el LLM solo se
invoca cuando la intención no es obvia y hay proveedor configurado.
Se ejecuta con timeout corto y nunca bloquea la consulta: si el
proveedor tarda o falla, manda el regex.
"""
from __future__ import annotations

import os
import re

INTENT_PROMPT = """Clasifica la intención de esta pregunta de un arquitecto sobre normativa urbanística.

Opciones:
- CONTEXTO: pregunta sobre datos del edificio/parcela seleccionado (superficie, altura, uso, clasificación, año)
- NORMATIVA: pregunta sobre qué se puede hacer o si algo está permitido (piscinas, cambio de uso, retranqueos, usos)
- CALCULO: pregunta que requiere un cálculo numérico concreto (ocupación disponible, edificabilidad, número de viviendas)
- SALUDO: saludo o pregunta general no relacionada

Ejemplos:
"qué tipo de suelo tiene" → CONTEXTO
"puedo hacer una piscina" → NORMATIVA
"cuánta ocupación me queda" → CALCULO
"hola" → SALUDO

Pregunta: {pregunta}
Intención (una sola palabra):"""

_SALUDO_RE = re.compile(
    r'^\s*(hola|buenas|buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|'
    r'qu[eé]\s+tal|hey|hi)\b', re.I)

_CALCULO_RE = re.compile(
    r'(cu[aá]nta?\s+(ocupaci[oó]n|edificabilidad|superficie)\s+(me\s+queda|'
    r'tengo|disponible)|cu[aá]ntas?\s+viviendas|cu[aá]nto\s+puedo\s+edificar|'
    r'margen\s+de\s+ocupaci[oó]n|cabria\s+\d)', re.I)

_EDIFICIO_RE = re.compile(
    r'(qu[eé]\s+(tipo|clase)\s+de\s+(edificio|suelo|parcela|terreno)|'
    r'qu[eé]\s+(edificio|suelo|parcela|terreno)|'
    r'(edificio|parcela|suelo)\s+seleccionado|qu[eé]\s+he\s+seleccionado|'
    r'qu[eé]\s+es\s+esto|qu[eé]\s+es\s+este|uso\s+del?\s+(edificio|suelo|parcela)|'
    r'clasificaci[oó]n\s+(del?\s+)?(suelo|parcela|urban[ií]stica)|'
    r'categor[ií]a\s+del?\s+suelo|a\s+qu[eé]\s+se\s+dedica|'
    r'de\s+qu[eé]\s+a[ñn]o\s+es|'
    r'cu[aá]ndo\s+se\s+construy[óo]|cu[aá]nta?s?\s+plantas?\s+tiene|'
    r'cu[aá]ntos?\s+pisos|direcci[oó]n\s+del?\s+edificio|'
    r'referencia\s+catastral|superficie\s+de\s+la\s+parcela|'
    r'cu[aá]nto\s+(mide|ocupa)|qu[eé]\s+superficie|qu[eé]\s+hay\s+aqu[ií]|'
    r'qu[eé]\s+clasificaci[oó]n|en\s+qu[eé]\s+zona\s+est[aá]|'
    r'qu[eé]\s+ordenanza|qu[eé]\s+normativa\s+se\s+aplica|'
    r'qu[eé]\s+datos\s+tienes|qu[eé]\s+sabes\s+de)', re.I)

_VALIDAS = {'CONTEXTO': 'edificio', 'NORMATIVA': 'normativa',
            'CALCULO': 'calculo', 'SALUDO': 'saludo'}

# Vocabulario normativo explícito: si la pregunta ya cayó en el bucket
# 'normativa' por regex y además usa estos términos, no se consulta al
# LLM — evita reclasificaciones erróneas tipo 'qué datos normativos
# tiene este suelo' → CONTEXTO.
_NORMATIVA_FUERTE_RE = re.compile(
    r'normativ[ao]s?|ordenanzas?|par[áa]metros?|edificabilidad|'
    r'ocupaci[óo]n\s+m[áa]x|retranqueos?|recuados?|usos?\s+permitidos?|'
    r'altura\s+m[áa]xima|frente\s+m[íi]nima|parcela\s+m[íi]nima|'
    r'fondo\s+edificable|vuelos?|voos?|entreplantas?|'
    r'piscinas?|cambio\s+de\s+uso|puedo\s+(edificar|construir|hacer)|'
    r'pueden?\s+edificar|est[áa]\s+permitido|se\s+puede|se\s+pode', re.I)


def _detectar_intencion_regex(pregunta: str) -> str:
    q = pregunta or ''
    if _SALUDO_RE.match(q):
        return 'saludo'
    if _EDIFICIO_RE.search(q):
        return 'edificio'
    if _CALCULO_RE.search(q):
        return 'calculo'
    return 'normativa'


def clasificar_intencion_llm(pregunta: str, timeout: float = 5.0) -> str | None:
    """Few-shot con el proveedor activo. None si falla o no hay LLM."""
    if os.getenv('INTENT_CLASSIFIER', 'llm').lower() in ('0', 'regex', 'off'):
        return None
    try:
        from src.model_gateway import _provider_attempt, _iter_provider_attempts
        proveedores = [p for p in _iter_provider_attempts() if p != 'local']
        if not proveedores:
            return None
        resp = _provider_attempt(
            proveedores[0], INTENT_PROMPT.format(pregunta=pregunta),
            timeout)
        token = (resp or '').strip().split()[0].strip('.,:').upper()
        return _VALIDAS.get(token)
    except Exception:
        return None


def clasificar_intencion(pregunta: str, usar_llm: bool = True) -> str:
    """Regex primero (gratuito); el LLM solo refina el bucket ambiguo
    'normativa', donde están los falsos negativos históricos
    ("¿cuánto mide el edificio?" → CONTEXTO). Si el LLM no responde en
    el timeout corto, manda el regex — nunca bloquea la consulta."""
    base = _detectar_intencion_regex(pregunta)
    if base != 'normativa' or not usar_llm:
        return base
    if _NORMATIVA_FUERTE_RE.search(pregunta):
        return 'normativa'
    return clasificar_intencion_llm(pregunta) or 'normativa'
