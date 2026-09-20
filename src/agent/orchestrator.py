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
from src.agent.validator import (validar_respuesta, anotar_respuesta,
                                 validacion_semantica)
from src.agent.contradictions import detectar_contradicciones
from src.agent.intent_classifier import (
    clasificar_intencion, _detectar_intencion_regex)
from src.agent.memory import get_session

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

# Preguntas sobre el propio edificio/contexto seleccionado: se responden
# con los datos de las herramientas (Catastro, SIOTUGA, altura), no con
# fragmentos normativos.
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

_SALUDO_RE = re.compile(
    r'^\s*(hola|buenas|buenos\s+d[ií]as|buenas\s+tardes|buenas\s+noches|'
    r'qu[eé]\s+tal|hey|hi)\b', re.I)


_CAMBIO_USO_RE = re.compile(
    r'cambio\s+de\s+uso|vivienda|habitab|local\s+a\s+vivienda|'
    r'convertir.*(vivienda|local)|vivenda|rehabilitar', re.I)


def _detectar_intencion(pregunta: str) -> str:
    """'edificio' | 'saludo' | 'calculo' | 'normativa' (regex)."""
    return _detectar_intencion_regex(pregunta)


def _respuesta_contexto(pregunta: str, ctx: dict) -> str:
    """Respuesta determinista sobre el edificio desde las herramientas."""
    cat = ctx.get('catastro') or {}
    res = ctx.get('resumen') or {}
    clas = ctx.get('clasificacion') or {}
    ord_p = ctx.get('ordenanzas_params') or {}
    bld = ctx.get('building') or {}
    alt = bld.get('altura') or {}
    alt_v = alt.get('value') if isinstance(alt, dict) else None
    alt_dq = alt.get('data_quality') if isinstance(alt, dict) else None

    if not cat.get('refcat') and not res.get('ref_catastral'):
        return ('No hay un edificio con datos catastrales en el punto '
                'seleccionado. Haz clic sobre un edificio del mapa o '
                'indica la referencia catastral.')

    if _SUELO_TEMA_RE.search(pregunta):
        return _respuesta_suelo(ctx)

    partes = []
    if cat.get('uso_principal'):
        det = cat.get('usos_detalle') or {}
        usos = ', '.join(f"{u} ({s:,.0f} m²)".replace(',', '.')
                         for u, s in list(det.items())[:4])
        partes.append(f"**Uso principal**: {cat['uso_principal']}"
                      + (f" — {usos}" if usos else ''))
    if cat.get('anio_construccion'):
        partes.append(f"**Año de construcción**: {cat['anio_construccion']}")
    if cat.get('direccion') or res.get('direccion'):
        partes.append(f"**Dirección**: {cat.get('direccion') or res.get('direccion')}")
    if cat.get('refcat') or res.get('ref_catastral'):
        partes.append(f"**Ref. catastral**: {cat.get('refcat') or res.get('ref_catastral')}")
    sups = []
    if res.get('superficie_parcela_m2'):
        sups.append(f"parcela {res['superficie_parcela_m2']:,.0f} m²".replace(',', '.'))
    if cat.get('superficie_construida_m2'):
        sups.append(f"construida {cat['superficie_construida_m2']:,.0f} m²".replace(',', '.'))
    if sups:
        partes.append('**Superficies**: ' + ' · '.join(sups))
    if alt_v is not None:
        partes.append(f"**Altura**: {alt_v} m"
                      + (f" ({alt_dq})" if alt_dq else ''))
    if clas.get('clasificacion_ley') or clas.get('clase_ley'):
        partes.append(
            f"**Clasificación urbanística**: "
            f"{clas.get('clasificacion_ley') or clas.get('clase_ley')}"
            + (f" ({clas.get('denominacion_zona')})"
               if clas.get('denominacion_zona') else ''))
    if ord_p.get('ordenanza'):
        partes.append(f"**Ordenanza**: {ord_p['ordenanza']}"
                      + (f" {ord_p['titulo']}" if ord_p.get('titulo') else '')
                      + _origen_ordenanza(ord_p, ctx))
    elif ord_p.get('ordenanzas_disponibles'):
        codigos = ', '.join(ord_p['ordenanzas_disponibles'][:14])
        partes.append(
            f"**Ordenanza**: no determinada automáticamente — "
            f"disponibles en el municipio: {codigos} "
            f"(indícala, p.ej. «subzona U6», o selecciónala en el visor)")

    faltan = []
    if alt_v is None:
        faltan.append('altura medida')
    if not (clas.get('clasificacion_ley') or clas.get('clase_ley')):
        faltan.append('clasificación SIOTUGA')
    if not ord_p.get('ordenanza'):
        faltan.append('ordenanza aplicable (subzona)')
    out = ['Datos del edificio seleccionado (fuentes oficiales):', '']
    out += partes
    if faltan:
        out.append('')
        out.append('*No disponible: ' + ', '.join(faltan) + '.*')
    return '\n'.join(out)


def _origen_ordenanza(ord_p: dict, ctx: dict) -> str:
    """Etiqueta de procedencia de la ordenanza resuelta."""
    res = ctx.get('ordenanza_resolucion') or {}
    est = res.get('estado')
    if est == 'inferida':
        origen = res.get('origen') or 'coincidencia automática'
        return (f" — **inferida** ({origen}); verificar en la ficha "
                'urbanística')
    if est == 'usuario':
        return ' — seleccionada por el usuario'
    if est == 'oficial':
        origen = res.get('origen') or ord_p.get('fuente')
        inst = f"; {res['instrumento']}" if res.get('instrumento') else ''
        return f" — oficial ({origen}{inst})"
    return f" — oficial, {ord_p.get('fuente')}"


_SUELO_TEMA_RE = re.compile(
    r'suelo|parcela|terreno|clasificaci[oó]n|ordenanza|'
    r'zona\s+urban[ií]stica|qu[eé]\s+normativa', re.I)


def _respuesta_suelo(ctx: dict) -> str:
    """Respuesta centrada en la clasificación/ordenanza del suelo."""
    clas = ctx.get('clasificacion') or {}
    ord_p = ctx.get('ordenanzas_params') or {}
    cat = ctx.get('catastro') or {}
    res = ctx.get('resumen') or {}
    out = []
    clase = clas.get('clasificacion_ley') or clas.get('clase_ley')
    if clase:
        etiqueta = (clas.get('clasificacion_ley_label')
                    or clas.get('clase_ley_label'))
        if not etiqueta:
            try:
                from src.siotuga.vector_downloader import CODE_LABELS
                etiqueta = CODE_LABELS.get(str(clase).upper())
            except Exception:
                etiqueta = None
        out.append(f"El suelo seleccionado está clasificado como "
                   f"**{clase}**" + (f" ({etiqueta})" if etiqueta else '')
                   + ' — fuente oficial SIOTUGA.')
        for k, lbl in [('denominacion_zona', 'Denominación de zona'),
                       ('uso_zona', 'Uso de zona'),
                       ('clasificacion_homo', 'Clasificación homogénea'),
                       ('clase_homo', 'Clase homogénea'),
                       ('categoria_wiug', 'Categoría')]:
            if clas.get(k):
                out.append(f"**{lbl}**: {clas[k]}")
    else:
        out.append('No se pudo obtener la clasificación urbanística '
                   'del punto (fuente SIOTUGA no disponible).')
    if ord_p.get('ordenanza'):
        out.append(f"**Ordenanza aplicable**: {ord_p['ordenanza']}"
                   + (f" {ord_p['titulo']}" if ord_p.get('titulo') else '')
                   + _origen_ordenanza(ord_p, ctx))
    elif ord_p.get('ordenanzas_disponibles'):
        res = ctx.get('ordenanza_resolucion') or {}
        if res.get('estado') == 'ambigua' and res.get('candidatas'):
            cands = ', '.join(res['candidatas'])
            out.append("**Ordenanza aplicable**: ambigua — los datos "
                       f"oficiales de la zona son compatibles con "
                       f"varias ({cands}); indica la correcta, p.ej. "
                       "«subzona U6»")
        else:
            codigos = ', '.join(ord_p['ordenanzas_disponibles'][:14])
            out.append("**Ordenanza aplicable**: no determinada "
                       "automáticamente — disponibles en el municipio: "
                       f"{codigos} (indícala, p.ej. «subzona U6», "
                       "o selecciónala en el visor)")
    extras = []
    if res.get('superficie_parcela_m2'):
        extras.append(f"parcela {res['superficie_parcela_m2']:,.0f} m²"
                      .replace(',', '.'))
    if cat.get('refcat') or res.get('ref_catastral'):
        extras.append(f"ref. {cat.get('refcat') or res.get('ref_catastral')}")
    if cat.get('uso_principal'):
        extras.append(f"edificio: {cat['uso_principal']}")
    if extras:
        out.append('')
        out.append('*Datos de la parcela: ' + ' · '.join(extras) + '*')
    return '\n'.join(out)


def _respuesta_saludo(ctx: dict) -> str:
    c = []
    if ctx.get('municipio'):
        c.append(f"municipio {ctx['municipio']}")
    if ctx.get('subzona'):
        c.append(f"subzona {ctx['subzona']}")
    base = ('¡Hola! Puedo responder sobre la normativa urbanística '
            'aplicable y sobre los datos oficiales del edificio '
            'seleccionado (Catastro, clasificación, ordenanza).')
    return base + (' Contexto actual: ' + ', '.join(c) + '.'
                   if c else ' Selecciona un edificio en el mapa para '
                   'preguntas concretas.')


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
            futs['ordenanza_wfs'] = ex.submit(
                _safe, 'ordenanza_wfs', tools.get_ordenanza_punto,
                lon, lat, ine)
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
    if ords.get('ordenanzas'):
        ctx['ordenanzas_params']['ordenanzas_disponibles'] = \
            sorted(ords['ordenanzas'].keys())

    # Resolución automática parcela → ordenanza. Una selección del
    # usuario solo manda si el código existe en el PGOM; si no existe
    # (código obsoleto/erróneo) la capa oficial sigue resolviendo.
    # Rellena parámetros marcando siempre el origen y la confianza —
    # una inferencia nunca se presenta como dato oficial.
    if ords.get('ordenanza'):
        ctx['ordenanza_resolucion'] = {
            'estado': 'usuario' if subzona else 'oficial',
            'ordenanza': ords['ordenanza'], 'confianza': 'alta'}
    elif (ords.get('ordenanzas')
          or (ctx.get('ordenanza_wfs') or {})
          .get('data_quality') == 'official'):
        try:
            from src.agent.ordinance_resolver import resolver_ordenanza
            res = resolver_ordenanza(ctx)
            ctx['ordenanza_resolucion'] = res
            if res.get('ordenanza') and res['estado'] in ('oficial',
                                                        'inferida'):
                op = ctx['ordenanzas_params']
                op['ordenanza'] = res['ordenanza']
                op['titulo'] = op.get('titulo') or res.get('titulo')
                for k, v in (res.get('params') or {}).items():
                    op[k] = v
                op['resolucion'] = res['estado']
                op['origen_resolucion'] = res.get('origen')
        except Exception:
            pass
    return ctx, usadas


def _fmt_dq(d: dict | None, key: str | None = None) -> str:
    d = d or {}
    if key:
        d = d.get(key) or {}
    dq = d.get('data_quality') if isinstance(d, dict) else None
    return dq or 'unavailable'


def _prompt(pregunta: str, ctx: dict, fragmentos: list[dict],
            calculo: dict | None, historial: str = '') -> str:
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
    if ctx.get('advertencias'):
        lineas += ['', 'ADVERTENCIAS DE CONSISTENCIA (verificar antes de afirmar):']
        lineas += [f"- {a}" for a in ctx['advertencias']]
    if calculo:
        lineas += ['', 'CÁLCULO PREVIO DISPONIBLE (verificado por el sistema):',
                   str(calculo)]
    if historial:
        lineas += ['', historial]
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
                          motivo: str, pregunta: str = '') -> str:
    # Filtrar fragmentos de baja relevancia: si el mejor BM25 es muy
    # flojo, los documentos probablemente no cubren la pregunta — mejor
    # decirlo que volcar texto irrelevante.
    relevantes = fragmentos
    if fragmentos:
        mejor = max(f.get('score', 0) for f in fragmentos)
        if mejor < 3.0:
            relevantes = [f for f in fragmentos
                          if f.get('score', 0) >= mejor * 0.6][:3]
        else:
            relevantes = [f for f in fragmentos
                          if f.get('score', 0) >= mejor * 0.4][:5]
    if not relevantes:
        partes = ['No se pudo generar una respuesta elaborada '
                  f'({motivo}) y los documentos normativos indexados '
                  'no contienen fragmentos claramente relevantes para '
                  'esta pregunta.']
    else:
        partes = ['No se pudo generar una respuesta elaborada '
                  f'({motivo}), pero estos son los artículos aplicables '
                  'recuperados de las fuentes oficiales:']
    if calculo and calculo.get('data_quality') != 'unavailable':
        partes.append('\n**Cálculo previo disponible**:')
        for k, v in calculo.items():
            if k not in ('data_quality', 'fuente'):
                partes.append(f'- {k}: {v}')
    for f in relevantes:
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
                      top_k: int = 10,
                      chat_id: str | None = None) -> dict:
    """Fase 1-4: contexto + RAG + cálculo + prompt (sin invocar el LLM).

    Devuelve todo lo necesario para generar la respuesta — lo usa tanto
    ``responder_consulta_edificio`` como el endpoint SSE, que necesita
    emitir el contexto y las fuentes antes de los tokens.
    """
    from app.main import _get_ine_for_municipio

    mem = get_session(chat_id)
    if mem and mem.usa_referencia(pregunta) and mem.last_building:
        lb = mem.last_building
        lon = lon if lon is not None else lb.get('lon')
        lat = lat if lat is not None else lb.get('lat')
        municipio = municipio or lb.get('municipio')
        subzona = subzona or lb.get('subzona')
        ref_catastral = ref_catastral or lb.get('refcat')
    ine = _get_ine_for_municipio(municipio) if municipio else None

    # Intención con LLM few-shot en paralelo con las herramientas de
    # contexto — si el proveedor no responde en el timeout corto,
    # clasificar_intencion cae al regex sin coste de latencia.
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut_int = ex.submit(clasificar_intencion, pregunta, True)
        ctx, herramientas = _contexto_edificio(
            lon, lat, ine, municipio, subzona, ref_catastral)
        intencion = fut_int.result()

    ctx['punto'] = {'lon': lon, 'lat': lat}

    ctx['advertencias'] = detectar_contradicciones(ctx)

    # Preguntas de contexto/saludo: no hace falta RAG ni LLM — la
    # respuesta sale directamente de los datos de las herramientas.
    if intencion == 'edificio':
        rag = {'fragmentos': [], 'n_corpus': 0, 'n_municipal': 0,
               'rerank': False}
        fragmentos = []
    elif intencion == 'saludo':
        rag = {'fragmentos': [], 'n_corpus': 0, 'n_municipal': 0,
               'rerank': False}
        fragmentos = []
    else:
        rag = tools.search_normativa(pregunta, ine=ine,
                                     municipio=municipio, top_k=top_k)
        fragmentos = rag.get('fragmentos') or []
        herramientas.append('search_normativa')

    # Si la pregunta cita una ordenanza concreta («U6», «SRPA»…), sus
    # parámetros extraídos del PDF oficial entran como fuente
    # determinista con página trazada — no depende del ranking BM25.
    ords_map = (ctx.get('ordenanzas') or {}).get('ordenanzas') or {}
    if ords_map and pregunta:
        from src.normativa_params import buscar_ordenanza
        for tok in re.findall(r'\b([A-Za-z]{1,4}\d{1,2}(?:\.\d+)?)\b',
                              pregunta):
            key, found = buscar_ordenanza(ords_map, tok)
            if found:
                trazas = found.get('trazas') or {}
                paginas = sorted({(t or {}).get('pagina')
                                  for t in trazas.values()} - {None})
                fichero = (found.get('fuente') or '').split(' pág')[0]
                url_pdf = None
                try:
                    from src.normativa_rag import indexar_municipio
                    url_pdf = next(
                        (c.get('url') for c in
                         (indexar_municipio(ine).get('chunks') or [])
                         if c.get('fichero') == fichero), None)
                except Exception:
                    pass
                if url_pdf and paginas:
                    url_pdf = f"{url_pdf}#page={paginas[0]}"
                texto = (f"ORDENANZA {key} — {found.get('titulo') or ''}. "
                         + '; '.join(f"{k}: {v}" for k, v in
                                     (found.get('params') or {}).items()))
                ctx['ordenanza_consultada'] = {
                    'codigo': key, 'titulo': found.get('titulo'),
                    'params': found.get('params') or {},
                    'fuente': found.get('fuente')}
                fragmentos = [{
                    'documento': 'Normativa urbanística municipal '
                                 '(PDF oficial)',
                    'referencia': fichero,
                    'pagina': paginas[0] if paginas else None,
                    'texto': texto,
                    'extracto': texto,
                    'fuente': 'Parámetros extraídos del PDF oficial',
                    'url': url_pdf,
                    'ambito': 'municipal',
                    'score': 99.0,
                }] + fragmentos
                for i, f in enumerate(fragmentos):
                    f['id'] = i + 1
                break

    calculo = None
    if _PISCINA_RE.search(pregunta or ''):
        calculo = tools.check_piscina_viability(ctx)
        herramientas.append('check_piscina_viability')
    elif _CAMBIO_USO_RE.search(pregunta or ''):
        calculo = tools.check_cambio_uso(ctx)
        herramientas.append('check_cambio_uso')

    historial = mem.build_history_context() if mem else ''
    prompt = _prompt(pregunta, ctx, fragmentos, calculo,
                     historial=historial)
    return {'ctx': ctx, 'fragmentos': fragmentos, 'calculo': calculo,
            'prompt': prompt, 'herramientas': herramientas, 'rag': rag,
            'pregunta': pregunta, 'intencion': intencion, 'mem': mem}


def finalizar_respuesta(prep: dict, respuesta: str | None,
                        llm_ok: bool, motivo: str) -> dict:
    """Fase 5-6: validación, degradación y empaquetado de la respuesta."""
    ctx = prep['ctx']
    fragmentos = prep['fragmentos']
    calculo = prep['calculo']
    rag = prep['rag']
    intencion = prep.get('intencion', 'normativa')

    validacion = None
    if intencion == 'edificio':
        respuesta = _respuesta_contexto(prep['pregunta'], ctx)
        llm_ok = False
        modo = 'contexto'
    elif intencion == 'saludo':
        respuesta = _respuesta_saludo(ctx)
        llm_ok = False
        modo = 'contexto'
    elif llm_ok and respuesta:
        validacion = validar_respuesta(respuesta, fragmentos, ctx)
        validacion = validacion_semantica(respuesta, fragmentos,
                                          validacion)
        respuesta = anotar_respuesta(respuesta, validacion)
        modo = 'llm'
    else:
        respuesta = _respuesta_heuristica(fragmentos, calculo, motivo,
                                        pregunta=prep['pregunta'])
        modo = 'heuristico'

    if ctx.get('advertencias'):
        respuesta += ('\n\n> ⚠ ' + '\n> '.join(ctx['advertencias']))

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
        'modo': modo,
        'intencion': intencion,
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
        'advertencias': ctx.get('advertencias') or [],
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
                                top_k: int = 10,
                                chat_id: str | None = None) -> dict:
    """Consulta normativa con contexto de edificio — flujo completo."""
    prep = preparar_consulta(pregunta, lon, lat, municipio,
                             ref_catastral, subzona, top_k, chat_id)

    respuesta = None
    llm_ok = False
    motivo = 'sin proveedor LLM configurado'
    if prep.get('intencion') in ('edificio', 'saludo'):
        final = finalizar_respuesta(prep, respuesta, llm_ok, motivo)
        _guardar_turno(prep, final)
        return final
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

    final = finalizar_respuesta(prep, respuesta, llm_ok, motivo)
    _guardar_turno(prep, final)
    return final


def _guardar_turno(prep: dict, final: dict) -> None:
    """Actualiza la memoria de sesión con el turno y el edificio."""
    mem = prep.get('mem')
    if not mem:
        return
    try:
        ctx = prep.get('ctx') or {}
        res = ctx.get('resumen') or {}
        punto = ctx.get('punto') or {}
        mem.last_building = {
            'lon': punto.get('lon'), 'lat': punto.get('lat'),
            'municipio': ctx.get('municipio'),
            'subzona': ctx.get('subzona'),
            'refcat': res.get('ref_catastral'),
        }
        mem.add_turn(prep['pregunta'], final.get('respuesta') or '')
    except Exception:
        pass
