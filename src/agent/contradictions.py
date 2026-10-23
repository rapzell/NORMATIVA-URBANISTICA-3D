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
        # Sin ordenanza tabulada aún puede haber advertencias del PE-1
        # (casco histórico: altura en alzados de ordenación).
        adv.extend(detectar_altura_pe1(ctx, alt_v))
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

    adv.extend(detectar_altura_pe1(ctx, alt_v))
    return adv


def detectar_altura_pe1(ctx: dict,
                        alt_v: float | None = None) -> list[str]:
    """Advertencias de altura cuando la parcela rige por PE-1.

    El Plan Especial del casco histórico de Santiago fija la altura
    máxima en los alzados de ordenación de cada manzana (arts. 95-98),
    no en una tabla: el sistema nunca inventa un límite numérico, pero
    sí (a) recuerda que la comprobación pasa por el alzado oficial y
    (b) detecta una posible sobreedificación cuando la altura medida
    implica claramente más plantas de las que Catastro declara.

    Acepta las dos formas de contexto: la del orquestador
    (``building.altura.value``) y la de ``/official/context``
    (``edificio_datos.altura.value``).
    """
    adv: list[str] = []
    pe1 = ctx.get('pe1') or {}
    if not pe1.get('califica'):
        return adv
    op = pe1.get('ordenanza_params') or pe1.get('params') or {}
    regimen = ((op.get('params') or {}).get('altura_regimen')
               or op.get('altura_regimen')
               or ctx.get('pe1_altura_regimen'))
    if alt_v is None:
        alt_v = ((ctx.get('edificio_datos') or {}).get('altura') or {}) \
            .get('value')
    masa = pe1.get('masa') or ''
    alz = pe1.get('alzados') or ctx.get('pe1_alzados') or []
    tiene_plano = any(a.get('pdfs') for a in alz if isinstance(a, dict))
    if regimen == 'alzados_ordenacion':
        msg = ("La altura máxima de esta parcela la fija el alzado de "
               "ordenación del PE-1 (arts. 95-98), no un valor "
               "tabulado")
        if alt_v is not None:
            msg += (f" — la altura medida por LiDAR es {alt_v:g} m; "
                    "compárela con el alzado oficial")
            msg += (f" de la manzana {masa}." if masa else
                    " de su manzana.")
            if not tiene_plano:
                msg += (" (Plano de fachada no localizado "
                        "automáticamente — consúltelo en el localizador"
                        " do Xeoportal.)")
        else:
            msg += "."
        adv.append(msg)

    # Posible sobreedificación: la altura medida (~3,2 m/planta) implica
    # más plantas de las que Catastro declara oficialmente. Es una
    # heurística marcada como estimada — LiDAR incluye cubierta y
    # Catastro no siempre refleja reformas — nunca una conclusión legal.
    cat = ctx.get('catastro') or {}
    plantas_of = cat.get('plantas_oficiales') \
        or cat.get('plantas_sobre_rasante')
    if alt_v and plantas_of:
        plantas_est = alt_v / 3.2
        if plantas_est > plantas_of + 1.5:
            adv.append(
                f"Posible sobreedificación: la altura medida "
                f"({alt_v:g} m ≈ {plantas_est:.1f} plantas) supera las "
                f"{plantas_of} plantas declaradas en Catastro — "
                "revisar el alzado oficial o la ficha catastral "
                "(estimación ~3,2 m/planta).")
    return adv
