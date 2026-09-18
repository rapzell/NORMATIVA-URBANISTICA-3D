"""Detector de contradicciones entre datos medidos y parámetros
normativos asignados.

Caso real: un edificio de 23 m / 380 viviendas quedó asociado a la
ordenanza U6 "vivienda unifamiliar" (altura máx. 7 m). Sin capa
vectorial parcela→ordenanza, estas advertencias son el mínimo viable
para no presentar una asignación incompatible como válida.
"""
from __future__ import annotations


def detectar_contradicciones(ctx: dict) -> list[str]:
    """Devuelve advertencias visibles si los datos chocan."""
    adv: list[str] = []
    bld = ctx.get('building') or {}
    alt = bld.get('altura') or {}
    alt_v = alt.get('value') if isinstance(alt, dict) else None
    ord_p = ctx.get('ordenanzas_params') or {}
    cat = ctx.get('catastro') or {}
    res = ctx.get('resumen') or {}

    ordenanza = ord_p.get('ordenanza')
    if not ordenanza:
        return adv

    altura_max = ord_p.get('altura_maxima_m')
    if alt_v is not None and altura_max and alt_v > altura_max * 1.1:
        adv.append(
            f"Posible ordenanza mal asignada: la altura medida "
            f"({alt_v:g} m) supera la altura máxima de {ordenanza} "
            f"({altura_max:g} m). Verificar que la ordenanza "
            f"corresponde realmente a esta parcela.")

    sup_parcela = res.get('superficie_parcela_m2')
    parcela_min = ord_p.get('parcela_minima_m2')
    if sup_parcela and parcela_min and sup_parcela < parcela_min:
        adv.append(
            f"La parcela ({sup_parcela:,.0f} m²) es inferior a la "
            f"parcela mínima de {ordenanza} ({parcela_min:g} m²) — "
            f"puede ser situación fuera de ordenación o asignación "
            f"incorrecta.".replace(',', '.'))

    sup_construida = cat.get('superficie_construida_m2')
    edif_max = ord_p.get('edificabilidad_max_m2_m2')
    if sup_parcela and sup_construida and edif_max:
        edif_real = sup_construida / sup_parcela
        if edif_real > edif_max * 1.15:
            adv.append(
                f"La edificabilidad construida (~{edif_real:.1f} m²/m²) "
                f"supera la máxima de {ordenanza} ({edif_max:g} m²/m²) — "
                f"edificio preexistente a la norma o asignación "
                f"incorrecta.")

    uso = (cat.get('uso_principal') or '').lower()
    titulo = (ord_p.get('titulo') or '').lower()
    if ordenanza and 'unifamiliar' in titulo and cat.get('usos_detalle'):
        n_usos = len(cat['usos_detalle'])
        if n_usos > 2 or uso in ('industrial', 'oficinas'):
            adv.append(
                f"La ordenanza {ordenanza} es de vivienda unifamiliar "
                f"pero el edificio tiene {n_usos} usos catastrales "
                f"('{cat.get('uso_principal')}') — probablemente la "
                f"ordenanza correcta sea otra.")

    return adv
