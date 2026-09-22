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

    # Subzona indicada manualmente vs realidad: si el código no existe
    # en el PGOM o difiere de la capa oficial municipal, se avisa — la
    # selección nunca se descarta en silencio.
    sub = ctx.get('subzona')
    resolucion = ctx.get('ordenanza_resolucion') or {}
    if sub:
        ords_map = (ctx.get('ordenanzas') or {}).get('ordenanzas') or {}
        wfs = ctx.get('ordenanza_wfs') or {}
        if ords_map:
            from src.normativa_params import buscar_ordenanza, \
                _norm_code
            key, found = buscar_ordenanza(ords_map, sub)
            if key is None:
                resuelta = resolucion.get('ordenanza')
                adv.append(
                    f"La ordenanza indicada «{sub}» no existe en las "
                    f"ordenanzas del PGOM del municipio"
                    + (f" — la capa oficial asigna {resuelta}."
                       if resuelta else
                       " — se ha ignorado al no existir."))
            elif (wfs.get('data_quality') == 'official'
                  and wfs.get('ordenanza')
                  and not _norm_code(wfs['ordenanza']).startswith(
                      _norm_code(key))
                  and not _norm_code(key).startswith(
                      _norm_code(wfs['ordenanza']))):
                adv.append(
                    f"La ordenanza indicada ({key}) difiere de la que "
                    f"asigna la capa oficial municipal "
                    f"({wfs['ordenanza']}) — verificar en la ficha "
                    f"urbanística.")

    ordenanza = ord_p.get('ordenanza')
    if not ordenanza:
        return adv

    altura_max = ord_p.get('altura_maxima_m')
    # Si la ordenanza fija un tope absoluto («medido desde cualquier
    # punto del terreno»), la altura LiDAR —que mide la cumbrera— se
    # compara contra él; superar solo la cornisa suele ser la cubierta.
    abs_cap = ord_p.get('altura_absoluta_m')
    limite_alt = abs_cap if (abs_cap and altura_max) else altura_max
    if alt_v is not None and limite_alt and alt_v > limite_alt * 1.1:
        adv.append(
            f"Posible ordenanza mal asignada: la altura medida "
            f"({alt_v:g} m) supera "
            + (f"el tope absoluto de {ordenanza} ({abs_cap:g} m; "
               f"la altura a cornisa es {altura_max:g} m). "
               if abs_cap and altura_max else
               f"la altura máxima de {ordenanza} ({altura_max:g} m). ")
            + "Verificar que la ordenanza corresponde realmente a "
              "esta parcela.")

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
