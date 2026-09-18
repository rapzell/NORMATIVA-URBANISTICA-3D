"""Herramientas de acceso a datos para el orquestador agéntico.

Cada herramienta envuelve un módulo ya existente del backend y
devuelve un dict serializable con ``data_quality`` — la misma
disciplina de trazabilidad que el resto del sistema: lo que no se
puede obtener se declara ``unavailable``, nunca se rellena.
"""
from __future__ import annotations

from typing import Any


def get_catastro_data(lon: float, lat: float) -> dict:
    """Referencia catastral, dirección, superficie y edificios (OVC/INSPIRE/BU)."""
    try:
        from src.catastro import client as catastro
        data = catastro.obtener_edificio_por_coordenadas(lon, lat)
        data['data_quality'] = 'official' if data.get('refcat') else 'unavailable'
        data['fuente'] = 'Catastro OVC/INSPIRE'
        return data
    except Exception as e:
        return {'data_quality': 'unavailable', 'error': str(e)}


def get_siotuga_clasificacion(lon: float, lat: float, ine: str | None) -> dict:
    """Clasificación urbanística oficial del punto (3CLAS vectorial/WFS)."""
    if not ine:
        return {'data_quality': 'unavailable',
                'error': 'Municipio sin código INE resuelto'}
    try:
        from src.siotuga.vector_downloader import consultar_clasificacion_punto
        data = consultar_clasificacion_punto(lon, lat, ine)
        if data:
            data['data_quality'] = 'official'
            data['fuente'] = 'SIOTUGA 3CLAS'
            return data
        return {'data_quality': 'unavailable',
                'error': 'Sin clasificación vectorial en el punto'}
    except Exception as e:
        return {'data_quality': 'unavailable', 'error': str(e)}


def get_building_data(lon: float, lat: float,
                      footprint: dict | None = None) -> dict:
    """Altura medida (LiDAR local → MDSN WCS) y huella del edificio."""
    try:
        from src.building_data.height_extractor import obtener_datos_edificio
        return obtener_datos_edificio(lon, lat, footprint=footprint)
    except Exception as e:
        return {'altura': {'data_quality': 'unavailable', 'error': str(e)}}


def get_ordenanza_punto(lon: float, lat: float, ine: str | None) -> dict:
    """Ordenanza SUC oficial del punto vía capa vectorial municipal
    (GeoServer/WFS propio del concello, p. ej. Vigo)."""
    if not ine:
        return {'data_quality': 'unavailable',
                'error': 'Municipio sin código INE resuelto'}
    try:
        from src.muni_wfs import consultar_ordenanza_punto
        return consultar_ordenanza_punto(lon, lat, ine) or \
            {'data_quality': 'unavailable',
             'error': 'Sin capa de ordenanzas para el municipio'}
    except Exception as e:
        return {'data_quality': 'unavailable', 'error': str(e)}


def get_ordenanzas_params(ine: str | None,
                          subzona: str | None = None) -> dict:
    """Parámetros normativos oficiales extraídos del PGOM (por ordenanza)."""
    if not ine:
        return {'data_quality': 'unavailable',
                'error': 'Municipio sin código INE resuelto'}
    try:
        from src.normativa_params import parametros_subzona
        return parametros_subzona(ine, subzona)
    except Exception as e:
        return {'data_quality': 'unavailable', 'error': str(e)}


def get_ordenanzas_locales(municipio: str | None) -> dict:
    """Ordenanzas municipales estructuradas (datos aportados, p.ej. AC8)."""
    if not municipio:
        return {'data_quality': 'unavailable', 'error': 'Sin municipio'}
    try:
        from src.ordenanzas_service import get_ordenanza_municipio
        data = get_ordenanza_municipio(municipio)
        if data:
            return {'data_quality': 'official', 'ordenanzas': data,
                    'fuente': 'Ordenanzas municipales (datos estructurados)'}
        return {'data_quality': 'unavailable',
                'error': 'Sin ordenanzas estructuradas para el municipio'}
    except Exception as e:
        return {'data_quality': 'unavailable', 'error': str(e)}


def get_inventario_planeamiento(municipio: str | None) -> dict:
    """Estado del planeamiento municipal vigente (CSV SIOTUGA)."""
    if not municipio:
        return {'data_quality': 'unavailable', 'error': 'Sin municipio'}
    try:
        from app.main import planeamento_inventario
        inv = planeamento_inventario(municipio)
        rows = inv.get('rows') or []
        return {'data_quality': 'official' if rows else 'unavailable',
                'rows': rows,
                'fuente': inv.get('source') or 'SIOTUGA inventario municipal',
                'descargado': inv.get('downloaded_at')}
    except Exception as e:
        return {'data_quality': 'unavailable', 'error': str(e)}


def check_cambio_uso(contexto: dict,
                     altura_libre_m: float | None = None,
                     piezas: list | None = None) -> dict:
    """Pre-verificación NHV (Decreto 128/2023) de conversión
    local→vivienda usando el motor de reglas verificado.

    Sin datos del interior del local devuelve igualmente la lista de
    requisitos oficiales (altura libre, acristalamiento, ventilación,
    superficies por estancia) — nunca inventa las medidas que faltan.
    """
    try:
        from src.habitabilidad_checker import (HabitabilityInput,
                                              HabitabilityRoom,
                                              check_habitability)
        rooms = [HabitabilityRoom(**p) for p in (piezas or [])]
        inp = HabitabilityInput(
            municipio=contexto.get('municipio'),
            tipo_operacion='cambio_uso_local_a_vivienda',
            altura_libre_m=altura_libre_m,
            piezas=rooms)
        r = check_habitability(inp)
        return {
            'data_quality': 'official',
            'estado_global': r.estado_global,
            'incumplimientos': r.incumplimientos,
            'requisitos': [{'parametro': c.parametro,
                            'estado': c.estado,
                            'requisito': c.requisito,
                            'referencia': c.referencia}
                           for c in r.comprobaciones],
            'fuentes': r.fuentes,
            'normativa': r.normativa,
            'nota': ('Sin medidas del interior del local se listan los '
                     'requisitos NHV oficiales; aportar altura libre y '
                     'piezas (superficie/acristalamiento/ventilación) '
                     'para la verificación concreta.'),
        }
    except Exception as e:
        return {'data_quality': 'unavailable', 'error': str(e)}


def search_normativa(query: str, ine: str | None,
                     municipio: str | None = None,
                     top_k: int = 10) -> dict:
    """RAG normativo: corpus autonómico + PDFs municipales."""
    from src.rag.search import buscar_normativa
    return buscar_normativa(query, ine=ine, municipio=municipio,
                            top_k=top_k)


def check_piscina_viability(contexto: dict,
                            sup_piscina_m2: float = 24.0,
                            computo: float = 0.5) -> dict:
    """Viabilidad geométrica de una piscina por ocupación disponible.

    Usa la superficie de parcela, la ocupación actual (huella/parcela)
    y la ocupación máxima de la ordenanza si se conoce. Devuelve el
    cálculo paso a paso para que el LLM lo cite con valores concretos.
    """
    res = contexto.get('resumen') or {}
    sup_parcela = res.get('superficie_parcela_m2') \
        or (contexto.get('catastro') or {}).get('superficie_parcela_m2') \
        or (contexto.get('catastro') or {}).get('area_parcela_m2')
    huella = (contexto.get('building') or {}).get('huella_m2')
    if isinstance(huella, dict):
        huella = huella.get('value')
    ocup_max = (contexto.get('ordenanzas_params') or {}).get('ocupacion_max_pct')
    calc = {'data_quality': 'estimated', 'sup_piscina_m2': sup_piscina_m2,
            'computo': computo}
    if not sup_parcela:
        calc['data_quality'] = 'unavailable'
        calc['error'] = 'Superficie de parcela no disponible'
        return calc
    calc['superficie_parcela_m2'] = sup_parcela
    if huella:
        ocup_actual = huella / sup_parcela
        calc['huella_m2'] = huella
        calc['ocupacion_actual_pct'] = round(ocup_actual * 100, 1)
    else:
        calc['nota_huella'] = ('Huella del edificio no disponible; la '
                               'ocupación resultante solo computa la '
                               'piscina — verificar la ocupación actual')
    if ocup_max:
        limite_m2 = sup_parcela * ocup_max / 100.0
        usada = huella or 0.0
        margen_m2 = limite_m2 - usada
        computa = sup_piscina_m2 * computo
        calc.update({
            'ocupacion_max_pct': ocup_max,
            'limite_m2': round(limite_m2, 1),
            'margen_m2': round(margen_m2, 1),
            'piscina_computa_m2': round(computa, 1),
            'viable_ocupacion': computa <= margen_m2,
            'ocupacion_resultante_pct': round(
                (usada + computa) / sup_parcela * 100, 1),
        })
    else:
        disponibles = (contexto.get('ordenanzas_params') or {}) \
            .get('ordenanzas_disponibles')
        if disponibles:
            calc['nota'] = (
                'Ocupación máxima no calculable: falta la ordenanza '
                f'aplicable. Disponibles en el municipio: '
                f"{', '.join(disponibles[:14])} — indica la subzona")
        else:
            calc['nota'] = ('Ocupación máxima de la ordenanza no '
                            'disponible; verificar en la ficha '
                            'urbanística municipal')
    return calc
