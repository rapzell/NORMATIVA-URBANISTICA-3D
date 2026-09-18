"""Orquestador agéntico del asistente de normativa urbanística.

Flujo por consulta (``responder_consulta_edificio``):

1. Recupera el contexto del edificio con las herramientas de
   ``tools.py`` (Catastro, SIOTUGA, altura medida, ordenanzas,
   inventario) en paralelo.
2. Recupera fragmentos normativos (``src.rag.search``): corpus
   autonómico + PDFs del PGOM municipal, con re-ranking si hay
   cross-encoder disponible.
3. Si la pregunta es de viabilidad de elemento (piscina, …) ejecuta el
   cálculo geométrico correspondiente.
4. Construye el prompt anclado (contexto + fuentes numeradas) e invoca
   el gateway LLM multi-proveedor.
5. Valida la respuesta contra las fuentes (``validator``); si falla la
   degradación es explícita, nunca silenciosa.
6. Si todos los LLM fallan, modo heurístico: devuelve los fragmentos
   recuperados con un mensaje honesto.

La veracidad manda: preferir "la normativa consultada no especifica
este punto" a cualquier afirmación sin respaldo.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.agent import tools
from src.agent.validator import validar_respuesta, anotar_respuesta

SYSTEM_PROMPT = """Eres un asistente experto en normativa urbanística de Galicia, especializado
en la Ley 2/2016 del Suelo, el Decreto 128/2023 de habitabilidad (NHV), las
Normas Técnicas de Planeamiento Urbanístico y las ordenanzas municipales.
Trabajas para arquitectos profesionales.

REGLAS ESTRICTAS:
1. Solo puedes afirmar lo que esté respaldado por las FUENTES proporcionadas.
2. Si una fuente no cubre la pregunta, dilo explícitamente: "La normativa
   consultada no especifica este punto."
3. Cada afirmación debe ir seguida de una cita en formato [FUENTE n].
4. Distingue entre normativa autonómica y municipal.
5. Si el dato del edificio es "estimated" o "unavailable", adviértelo.
6. Nunca inventes artículos, referencias catastrales ni datos numéricos.
7. Si la pregunta requiere un cálculo (ocupación, retranqueo, edificabilidad),
   muestra el razonamiento paso a paso con los valores concretos.
8. Cierra siempre con las condiciones a verificar y la advertencia de que es
   una evaluación preliminar que requiere verificación municipal.

Responde en español, de forma estructurada y profesional.
"""

_PISCINA_RE = re.compile(
    r'piscina|pajar|barbacoa|p[eé]rgola|cenador|caseta|cobertizo', re.I)


def _contexto_edificio(lon: float | None, lat: float | None,
                       ine: str | None, municipio: str | None,
                       subzona: str | None,
                       ref_catastral: str | None) -> tuple[dict, list[str]]:
    """Ejecuta las herramientas de contexto en paralelo."""
    ctx: dict = {'municipio': municipio, 'subzona': subzona,
                 'ref_catastral_input': ref_catastral}
    usadas: list[str] = []

    def _safe(name, fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            return {'data_quality': 'unavailable', 'error': str(e)}

    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {}
        if lon is not None and lat is not None:
            futs['catastro'] = ex.submit(
                _safe, 'catastro', tools.get_catastro_data, lon, lat)
            futs['clasificacion'] = ex.submit(
                _safe, 'clasificacion', tools.get_siotuga_clasificacion,
                lon, lat, ine)
            futs['building'] = ex.submit(
                _safe, 'building', tools.get_building_data, lon, lat)
        futs['ordenanzas'] = ex.submit(
            _safe, 'ordenanzas', tools.get_ordenanzas_params, ine, subzona)
        futs['inventario'] = ex.submit(
            _safe, 'inventario', tools.get_inventario_planeamiento,
            municipio)
        results = {k: f.result() for k, f in futs.items()}
    for k, v in results.items():
        ctx[k] = v
        usadas.append(k)
    # Resumen plano útil para el prompt
    cat = ctx.get('catastro') or {}
    ctx['resumen'] = {
        'ref_catastral': cat.get('refcat') or ref_catastral,
        'direccion': cat.get('direccion') or cat.get('lourl') ,
        'superficie_parcela_m2': cat.get('superficie_parcela_m2')
            or cat.get('area_parcela_m2')
            or (cat.get('parcela') or {}).get('superficie_m2'),
    }
    ords = ctx.get('ordenanzas') or {}
    params = ords.get('params') or {}
    resultado = ords.get('resultado') or {}
    ctx['ordenanzas_params'] = {
        'ordenanza': ords.get('ordenanza'),
        'titulo': resultado.get('titulo'),
        'ocupacion_max_pct': params.get('ocupacion_max_pct'),
        'edificabilidad_max_m2_m2': params.get('edificabilidad_max_m2_m2'),
        'altura_maxima_m': params.get('altura_maxima_m'),
        'parcela_minima_m2': params.get('parcela_minima_m2'),
        'retranqueo_frontal_m': params.get('retranqueo_frontal_m'),
        'retranqueo_lateral_m': params.get('retranqueo_lateral_m'),
        'retranqueo_posterior_m': params.get('retranqueo_posterior_m'),
        'fuente': resultado.get('fuente'),
        'trazas': resultado.get('trazas'),
        'data_quality': ords.get('data_quality'),
    }
    return ctx, usadas


def _fmt_dq(d: dict | None, key: str | None = None) -> str:
    d = d or {}
    if key:
        d = d.get(key) or {}
    dq = d.get('data_quality') if isinstance(d, dict) else None
    return dq or 'unavailable'


def _prompt(pregunta: str, ctx: dict, fragmentos: list[dict],
            calculo: dict | None) -> str:
    res = ctx.get('resumen') or {}
    clas = ctx.get('clasificacion') or {}
    ord_p = ctx.get('ordenanzas_params') or {}
    bld = ctx.get('building') or {}
    alt = bld.get('altura') or {}
    alt_v = alt.get('value') if isinstance(alt, dict) else None
    lineas = [
        SYSTEM_PROMPT,
        'CONTEXTO DEL EDIFICIO:',
        f"- Municipio: {ctx.get('municipio') or 'desconocido'}",
        f"- Referencia catastral: {res.get('ref_catastral') or 'no disponible'}"
        f" ({_fmt_dq(ctx.get('catastro'))})",
        f"- Superficie parcela: {res.get('superficie_parcela_m2') or 'no disponible'} m²"
        f" ({_fmt_dq(ctx.get('catastro'))})",
        f"- Altura medida: {alt_v if alt_v is not None else 'no disponible'} m"
        f" ({alt.get('data_quality', 'unavailable') if isinstance(alt, dict) else 'unavailable'})",
        f"- Clasificación SIOTUGA: {clas.get('clase_ley') or clas.get('clasificacion_ley') or 'no disponible'}"
        f" / {clas.get('categoria_wiug') or clas.get('clasificacion_plan') or ''}"
        f" ({_fmt_dq(clas)})",
    ]
    inv = ctx.get('inventario') or {}
    rows = inv.get('rows') or []
    if rows:
        r0 = rows[0]
        lineas.append(
            f"- Planeamiento vigente: {r0.get('instrumento') or r0.get('plan')}"
            f" (aprobado {r0.get('fecha_aprobacion') or r0.get('aprobacion') or 's/f'},"
            f" {r0.get('estado') or ''})")
    if ord_p.get('ordenanza'):
        lineas += [
            f"- Ordenanza aplicable: {ord_p['ordenanza']}"
            f" {ord_p.get('titulo') or ''} (oficial PGOM,"
            f" {ord_p.get('fuente')})",
            f"  · Ocupación máx: {ord_p.get('ocupacion_max_pct')}%",
            f"  · Edificabilidad máx: {ord_p.get('edificabilidad_max_m2_m2')} m²/m²",
            f"  · Altura máx: {ord_p.get('altura_maxima_m')} m",
            f"  · Parcela mínima: {ord_p.get('parcela_minima_m2')} m²",
            f"  · Retranqueos frontal/lateral/posterior:"
            f" {ord_p.get('retranqueo_frontal_m')}/"
            f"{ord_p.get('retranqueo_lateral_m')}/"
            f"{ord_p.get('retranqueo_posterior_m')} m",
        ]
    elif ctx.get('subzona'):
        lineas.append(f"- Subzona declarada: {ctx['subzona']} "
                      '(sin parámetros oficiales extraídos — indicarlo)')
    if calculo:
        lineas += ['', 'CÁLCULO PREVIO DISPONIBLE (verificado por el sistema):',
                   str(calculo)]
    lineas += ['', 'FUENTES NORMATIVAS RECUPERADAS:']
    for f in fragmentos:
        lineas.append(
            f"--- [FUENTE {f['id']}] {f.get('documento')},"
            f" {f.get('referencia') or 's/ref'}, pág. {f.get('pagina') or '?'} ---")
        lineas.append((f.get('texto') or f.get('extracto') or '')[:1500])
    if not fragmentos:
        lineas.append('(sin fragmentos recuperados — responde indicando '
                      'que la normativa consultada no cubre la pregunta)')
    lineas += ['', f'PREGUNTA DEL ARQUITECTO: {pregunta}', '', 'RESPUESTA:']
    return '\n'.join(lineas)


def _respuesta_heuristica(fragmentos: list[dict], calculo: dict | None,
                          motivo: str) -> str:
    partes = ['No se pudo generar una respuesta elaborada '
              f'({motivo}), pero estos son los artículos aplicables '
              'recuperados de las fuentes oficiales:']
    if calculo and calculo.get('data_quality') != 'unavailable':
        partes.append('\n**Cálculo previo disponible**:')
        for k, v in calculo.items():
            if k not in ('data_quality', 'fuente'):
                partes.append(f'- {k}: {v}')
    for f in fragmentos:
        partes.append(
            f"\n**[FUENTE {f['id']}]** {f.get('documento')},"
            f" {f.get('referencia') or 's/ref'}, pág. {f.get('pagina') or '?'}:")
        partes.append(f"> {(f.get('extracto') or f.get('texto') or '')[:400]}")
    partes.append('\n*Evaluación preliminar; verificar en la ficha '
                  'urbanística y los servicios técnicos municipales.*')
    return '\n'.join(partes)


def preparar_consulta(pregunta: str, lon: float | None = None,
                      lat: float | None = None,
                      municipio: str | None = None,
                      ref_catastral: str | None = None,
                      subzona: str | None = None,
                      top_k: int = 10) -> dict:
    """Fase 1-4: contexto + RAG + cálculo + prompt (sin invocar el LLM).

    Devuelve todo lo necesario para generar la respuesta — lo usa tanto
    ``responder_consulta_edificio`` como el endpoint SSE, que necesita
    emitir el contexto y las fuentes antes de los tokens.
    """
    from app.main import _get_ine_for_municipio
    ine = _get_ine_for_municipio(municipio) if municipio else None

    ctx, herramientas = _contexto_edificio(
        lon, lat, ine, municipio, subzona, ref_catastral)

    rag = tools.search_normativa(pregunta, ine=ine, municipio=municipio,
                                 top_k=top_k)
    fragmentos = rag.get('fragmentos') or []
    herramientas.append('search_normativa')

    calculo = None
    if _PISCINA_RE.search(pregunta or ''):
        calculo = tools.check_piscina_viability(ctx)
        herramientas.append('check_piscina_viability')

    prompt = _prompt(pregunta, ctx, fragmentos, calculo)
    return {'ctx': ctx, 'fragmentos': fragmentos, 'calculo': calculo,
            'prompt': prompt, 'herramientas': herramientas, 'rag': rag,
            'pregunta': pregunta}


def finalizar_respuesta(prep: dict, respuesta: str | None,
                        llm_ok: bool, motivo: str) -> dict:
    """Fase 5-6: validación, degradación y empaquetado de la respuesta."""
    ctx = prep['ctx']
    fragmentos = prep['fragmentos']
    calculo = prep['calculo']
    rag = prep['rag']

    validacion = None
    if llm_ok and respuesta:
        validacion = validar_respuesta(respuesta, fragmentos, ctx)
        respuesta = anotar_respuesta(respuesta, validacion)
    else:
        respuesta = _respuesta_heuristica(fragmentos, calculo, motivo)

    fuentes_pub = [{
        'id': f['id'],
        'documento': f.get('documento'),
        'referencia': f.get('referencia'),
        'pagina': f.get('pagina'),
        'extracto': f.get('extracto'),
        'fuente': f.get('fuente'),
        'url': f.get('url'),
        'ambito': f.get('ambito'),
    } for f in fragmentos]

    return {
        'pregunta': prep['pregunta'],
        'respuesta': respuesta,
        'llm': llm_ok,
        'modo': 'llm' if llm_ok else 'heuristico',
        'fuentes': fuentes_pub,
        'contexto': {
            'municipio': ctx.get('municipio'),
            'subzona': ctx.get('subzona'),
            'resumen': ctx.get('resumen'),
            'clasificacion': {k: (ctx.get('clasificacion') or {}).get(k)
                              for k in ('clase_ley', 'clasificacion_ley',
                                        'categoria_wiug', 'data_quality')},
            'ordenanzas': ctx.get('ordenanzas_params'),
        },
        'calculo': calculo,
        'validacion': validacion,
        'herramientas': prep['herramientas'],
        'rag': {'n_corpus': rag.get('n_corpus'),
                'n_municipal': rag.get('n_municipal'),
                'rerank': rag.get('rerank')},
        'data_quality': 'official' if fragmentos else 'unavailable',
        'aviso': ('Evaluación preliminar basada en fuentes oficiales; '
                  'la viabilidad final requiere verificación en los '
                  'servicios técnicos municipales.'),
    }


def responder_consulta_edificio(pregunta: str, lon: float | None = None,
                                lat: float | None = None,
                                municipio: str | None = None,
                                ref_catastral: str | None = None,
                                subzona: str | None = None,
                                top_k: int = 10) -> dict:
    """Consulta normativa con contexto de edificio — flujo completo."""
    prep = preparar_consulta(pregunta, lon, lat, municipio,
                             ref_catastral, subzona, top_k)

    respuesta = None
    llm_ok = False
    motivo = 'sin proveedor LLM configurado'
    try:
        from src.model_gateway import generate_with_fallback
        ans = generate_with_fallback(prep['prompt'], None)
        if ans and 'No ha sido posible' not in ans and 'fallo' not in ans[:60]:
            respuesta = ans.strip()
            llm_ok = True
        else:
            motivo = 'todos los proveedores LLM fallaron'
    except Exception as e:
        motivo = f'error LLM: {e}'

    return finalizar_respuesta(prep, respuesta, llm_ok, motivo)
