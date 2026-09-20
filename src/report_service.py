from typing import Any, Optional

from src.plans_service import get_plan_provider_kind


def _extract_polygon_coords(geometry: dict | None) -> list[tuple[float, float]] | None:
    """Extrae los vertices de un poligono GeoJSON (solo el anillo exterior)."""
    if not geometry:
        return None
    gtype = geometry.get('type', '')
    coords = geometry.get('coordinates', [])
    if gtype == 'Polygon' and coords:
        return [(float(p[0]), float(p[1])) for p in coords[0]]
    if gtype == 'MultiPolygon' and coords:
        # Usar el poligono mas grande
        biggest = max(coords[0] if coords else [], key=len) if coords else []
        return [(float(p[0]), float(p[1])) for p in biggest]
    return None


def render_svg_minimap(parcel_geom: dict | None, envelope_feat: dict | None, *, width: int = 400, height: int = 300) -> str:
    """Genera un SVG mini-mapa mostrando la parcela y la envolvente edificable.

    Args:
        parcel_geom: GeoJSON geometry de la parcela.
        envelope_feat: GeoJSON Feature de la envolvente (con properties).
        width: ancho del SVG en px.
        height: alto del SVG en px.

    Returns:
        String con el SVG embebible.
    """
    parcel_points = _extract_polygon_coords(parcel_geom)
    env_points = None
    if envelope_feat and isinstance(envelope_feat, dict):
        env_geom = envelope_feat.get('geometry', envelope_feat)
        env_points = _extract_polygon_coords(env_geom)

    if not parcel_points and not env_points:
        return '<div class="muted">Sin geometría para mostrar</div>'

    # Calcular bounds de todos los puntos
    all_points = (parcel_points or []) + (env_points or [])
    if not all_points:
        return '<div class="muted">Sin geometría para mostrar</div>'

    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Padding
    pad = 20
    dx = (max_x - min_x) or 1.0
    dy = (max_y - min_y) or 1.0

    def project(x: float, y: float) -> tuple[float, float]:
        """Proyecta lon/lat a coordenadas SVG (invierte Y)."""
        px = pad + (x - min_x) / dx * (width - 2 * pad)
        py = height - pad - (y - min_y) / dy * (height - 2 * pad)
        return px, py

    def points_to_path(pts: list[tuple[float, float]]) -> str:
        projected = [project(x, y) for x, y in pts]
        if len(projected) < 2:
            return ''
        return 'M ' + ' L '.join(f'{px:.1f},{py:.1f}' for px, py in projected) + ' Z'

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" style="border:1px solid #444;border-radius:8px;background:#1a1a2e">'
    ]

    # Grid de fondo
    for i in range(1, 4):
        gx = pad + i * (width - 2 * pad) / 4
        gy = pad + i * (height - 2 * pad) / 4
        svg_parts.append(f'<line x1="{gx:.0f}" y1="{pad}" x2="{gx:.0f}" y2="{height-pad}" stroke="#2a2a3e" stroke-width="0.5"/>')
        svg_parts.append(f'<line x1="{pad}" y1="{gy:.0f}" x2="{width-pad}" y2="{gy:.0f}" stroke="#2a2a3e" stroke-width="0.5"/>')

    # Parcela (contorno azul)
    if parcel_points:
        path = points_to_path(parcel_points)
        svg_parts.append(f'<path d="{path}" fill="rgba(52,152,219,0.15)" stroke="#3498db" stroke-width="2"/>')

    # Envolvente (relleno rojo semitransparente)
    if env_points:
        path = points_to_path(env_points)
        svg_parts.append(f'<path d="{path}" fill="rgba(233,69,96,0.35)" stroke="#e94560" stroke-width="2"/>')

    # Etiquetas
    svg_parts.append(f'<text x="{pad}" y="{pad-4}" fill="#888" font-size="10" font-family="sans-serif">Composición cartográfica</text>')

    # Leyenda
    legend_y = height - pad - 10
    if parcel_points:
        svg_parts.append(f'<rect x="{pad}" y="{legend_y}" width="12" height="12" fill="rgba(52,152,219,0.3)" stroke="#3498db" stroke-width="1"/>')
        svg_parts.append(f'<text x="{pad+16}" y="{legend_y+10}" fill="#aaa" font-size="10" font-family="sans-serif">Parcela</text>')
    if env_points:
        lx = pad + 80 if parcel_points else pad
        svg_parts.append(f'<rect x="{lx}" y="{legend_y}" width="12" height="12" fill="rgba(233,69,96,0.4)" stroke="#e94560" stroke-width="1"/>')
        svg_parts.append(f'<text x="{lx+16}" y="{legend_y+10}" fill="#aaa" font-size="10" font-family="sans-serif">Envolvente</text>')

    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


def render_assess_report_html(body: dict, res: Any, *, logo: Optional[str] = None, title: Optional[str] = None, client: Optional[str] = None, project: Optional[str] = None, snapshot_data_url: Optional[str] = None, brand_color: Optional[str] = None, signature: bool = False, sign_by: Optional[str] = None, sign_place: Optional[str] = None, notes: Optional[str] = None, source_ref: Optional[str] = None, official_context: Optional[dict] = None) -> str:
    import html as _html
    def esc(x: str) -> str:
        try:
            return _html.escape(x if isinstance(x, str) else str(x))
        except Exception:
            return str(x)
    def _num(x):
        try:
            return None if x is None else float(x)
        except Exception:
            return None
    v = (res.viability or '').upper()
    color = {'APTO':'#2e7d32','CONDICIONADO':'#f57f17','NO APTO':'#c62828'}.get(v, (brand_color or '#37474f'))
    reasons = ''.join(f"<li>{esc(r)}</li>" for r in (res.reasons or []))
    pe = res.params_effective or {}
    # Detectar si los parámetros provienen de un CSV local (datos orientativos, no oficiales)
    try:
        from src.plans_service import get_plan_provider_kind as _prov_kind
        _prov = (_prov_kind() or '').lower()
    except Exception:
        _prov = ''
    _csv_orientativo = _prov in ('csv', 'local', 'uploaded')
    plan_source = pe.get('plan_source') or ''
    if _csv_orientativo or 'csv' in str(plan_source).lower():
        v = f"{v} (ORIENTATIVO)" if v else 'ORIENTATIVO'
        color = '#f57f17'
        reasons += (
            "<li><b>Parámetros normativos orientativos:</b> provienen de un CSV local "
            "(<code>plan_uploaded.csv</code>), no de la ordenanza oficial. "
            "La viabilidad mostrada es solo volumétrica; verifique siempre la normativa municipal vigente.</li>"
        )
    rows = ''
    pe_labels = {
        'altura_maxima_m': 'Altura máxima (m)',
        'retranqueo_min_m': 'Retranqueo mínimo (m)',
        'setback_front_m': 'Retranqueo frontal (m)',
        'setback_side_m': 'Retranqueo lateral (m)',
        'setback_back_m': 'Retranqueo trasero (m)',
        'front_direction': 'Orientación del frente',
        'front_direction_source': 'Fuente de orientación',
    }
    for k in ['altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','front_direction','front_direction_source']:
        label = pe_labels.get(k, k)
        _pv = pe.get(k)
        rows += f"<tr><td>{esc(label)}</td><td>{esc(_pv) if _pv is not None else '—'}</td></tr>"
    # Datos del edificio como parámetros efectivos
    try:
        bld = body.get('edificio_osm') if isinstance(body, dict) else None
        if isinstance(bld, dict) and bld:
            if bld.get('altura_m') is not None: rows += f"<tr><td>altura_edificio_m</td><td>{esc(bld['altura_m'])}</td></tr>"
            if bld.get('huella_m2') is not None: rows += f"<tr><td>huella_edificio_m2</td><td>{esc(bld['huella_m2'])}</td></tr>"
            if bld.get('plantas'): rows += f"<tr><td>plantas_edificio</td><td>{esc(bld['plantas'])}</td></tr>"
    except Exception:
        pass
    # Edificabilidad oficial de SIOTUGA cuando no hay parámetro del plan
    try:
        clas_pe = (official_context or {}).get('clasificacion_siotuga') or {}
        if clas_pe.get('edificabilidad_ficha') is not None and pe.get('edificabilidad_max_m2_m2') is None:
            rows += f"<tr><td>Edificabilidad oficial (SIOTUGA)</td><td>{esc(clas_pe['edificabilidad_ficha'])}</td></tr>"
        if clas_pe.get('uso_zona'):
            rows += f"<tr><td>Uso permitido (SIOTUGA)</td><td>{esc(clas_pe['uso_zona'])}</td></tr>"
    except Exception:
        pass
    area_txt = ''
    try:
        a = (res.geometry_summary or {}).get('area') or (res.geometry_summary or {}).get('area_m2')
        if a is not None:
            area_txt = f"<div class=muted>Área de parcela: {esc(round(float(a), 2))} m²</div>"
    except Exception:
        pass
    muni = (body.get('municipio') or '').strip() if isinstance(body, dict) else ''
    subz = (body.get('subzona') or '').strip() if isinstance(body, dict) else ''
    amb = (body.get('ambito') or '').strip() if isinstance(body, dict) else ''
    amb_nom = (body.get('ambito_nombre') or '').strip() if isinstance(body, dict) else ''
    loc_txt = ''
    if muni or subz:
        loc_txt = f"<div class=muted>Municipio: {esc(muni) or '—'}{(' · Subzona: ' + esc(subz)) if subz else ''}</div>"
    if amb:
        loc_txt += (f"<div class=muted>Ámbito de planeamento: "
                    f"{esc(amb)}{(' — ' + esc(amb_nom)) if amb_nom else ''}"
                    " (oficial, PXOM)</div>")
    import datetime as _dt
    gen_date = _dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    ttl = esc(title) if title else 'Informe de Viabilidad'
    cl = esc(client) if client else ''
    pj = esc(project) if project else ''
    logo_html = f"<img src='{esc(logo)}' alt='logo' style='height:40px'/>" if logo else ''
    client_proj = ''
    if cl or pj:
        client_proj = f"<div class=muted>{('Cliente: ' + cl) if cl else ''}{(' · Proyecto: ' + pj) if pj else ''}</div>"
    snap_html = ''
    if snapshot_data_url:
        try:
            snap_html = f"<div style='margin-top:10px'><img alt='snapshot' src='{esc(snapshot_data_url)}' style='max-width:100%;border:1px solid #333;border-radius:6px'/></div>"
        except Exception:
            snap_html = ''
    sig_html = ''
    if signature:
        try:
            _sb = esc(sign_by) if sign_by else ''
            _sp = esc(sign_place) if sign_place else 'Lugar y fecha'
            _sb_txt = (f" · {_sb}") if _sb else ''
            sig_html = (
                "<h2>Firma</h2>"
                "<div style=\"display:flex;gap:24px;flex-wrap:wrap;margin-top:8px\">"
                "<div style=\"flex:1 1 280px;border:1px dashed var(--line);border-radius:6px;padding:12px;\">"
                "<div style=\"height:70px\"></div>"
                f"<div class=\"muted\" style=\"margin-top:6px\">Firma{_sb_txt}</div>"
                "</div>"
                "<div style=\"flex:1 1 240px;border:1px dashed var(--line);border-radius:6px;padding:12px;\">"
                "<div style=\"height:70px\"></div>"
                "<div class=\"muted\" style=\"margin-top:6px\">Sello</div>"
                "</div>"
                "<div style=\"flex:1 1 240px;border:1px dashed var(--line);border-radius:6px;padding:12px;\">"
                "<div style=\"height:70px\"></div>"
                f"<div class=\"muted\" style=\"margin-top:6px\">{_sp}</div>"
                "</div>"
                "</div>"
            )
        except Exception:
            sig_html = ''
    try:
        muni = esc((pe.get('municipio') or '') or (body.get('municipio') if isinstance(body, dict) else '') or '')
    except Exception:
        muni = ''
    try:
        subz = esc((pe.get('subzona') or '') or (body.get('subzona') if isinstance(body, dict) else '') or '')
    except Exception:
        subz = ''
    prov_kind = esc(get_plan_provider_kind())
    alt = pe.get('altura_maxima_m')
    ret = pe.get('retranqueo_min_m')
    ocu = pe.get('ocupacion_max') or pe.get('ocupacion')
    edi = pe.get('edificabilidad_max_m2_m2') or pe.get('edificabilidad')
    def _fmt(x):
        try:
            if x is None:
                return '—'
            if isinstance(x, (int, float)):
                return str(round(float(x), 2))
            return esc(str(x))
        except Exception:
            return esc(str(x))
    resumen_html = (
        f"<p class=muted>Zona: {muni or '—'}{(' · ' + subz) if subz else ''} · Proveedor: {prov_kind}. "
        f"Viabilidad: <b>{esc(v or '—')}</b>. Altura máx: {_fmt(alt)} m; Retranqueo: {_fmt(ret)} m; "
        f"Ocupación: {_fmt(ocu)}; Edificabilidad: {_fmt(edi)}.</p>"
    )
    # Datos del edificio para el resumen
    bld_summary = ''
    try:
        bld_data = body.get('edificio_osm') if isinstance(body, dict) else None
        if isinstance(bld_data, dict) and bld_data:
            parts = []
            if bld_data.get('tipo'): parts.append(f"Tipo: {esc(bld_data['tipo'])}")
            if bld_data.get('altura_m') is not None: parts.append(f"Altura: {esc(bld_data['altura_m'])} m")
            if bld_data.get('huella_m2') is not None: parts.append(f"Huella: {esc(bld_data['huella_m2'])} m²")
            if bld_data.get('plantas'): parts.append(f"Plantas: {esc(bld_data['plantas'])}")
            if parts:
                bld_summary = f"<p class=muted>Edificio (OSM): {' · '.join(parts)}.</p>"
    except Exception:
        pass
    # Catastro para el resumen
    cat_summary = ''
    try:
        cat_ctx = (official_context or {}).get('catastro') or {}
        if cat_ctx.get('available'):
            parts = []
            if cat_ctx.get('refcat'): parts.append(f"Ref. catastral: {esc(cat_ctx['refcat'])}")
            if cat_ctx.get('superficie_construida_m2'): parts.append(f"Sup. construida: {esc(cat_ctx['superficie_construida_m2'])} m²")
            if cat_ctx.get('uso_principal'): parts.append(f"Uso: {esc(cat_ctx['uso_principal'])}")
            if cat_ctx.get('anio_construccion'): parts.append(f"Año: {esc(cat_ctx['anio_construccion'])}")
            if cat_ctx.get('superficie_comercial_m2'): parts.append(f"Sup. no residencial: {esc(cat_ctx['superficie_comercial_m2'])} m²")
            if parts:
                cat_summary = f"<p class=muted>Catastro: {' · '.join(parts)}.</p>"
    except Exception:
        pass
    # Clasificación SIOTUGA para el resumen
    siotuga_summary = ''
    try:
        clas_ctx = (official_context or {}).get('clasificacion_siotuga') or {}
        if clas_ctx.get('clasificacion_ley') or clas_ctx.get('clasificacion_plan'):
            parts = []
            if clas_ctx.get('clasificacion_ley_label'):
                parts.append(f"Clasificación: {esc(clas_ctx['clasificacion_ley_label'])}")
            if clas_ctx.get('denominacion_zona'):
                parts.append(f"Zona: {esc(clas_ctx['denominacion_zona'])}")
            if clas_ctx.get('uso_zona'):
                parts.append(f"Uso: {esc(clas_ctx['uso_zona'])}")
            if clas_ctx.get('edificabilidad_ficha') is not None:
                parts.append(f"Edificabilidad: {esc(clas_ctx['edificabilidad_ficha'])}")
            if parts:
                siotuga_summary = f"<p class=muted>SIOTUGA (oficial): {' · '.join(parts)}.</p>"
    except Exception:
        pass
    # Indicador de disponibilidad de datos
    data_flags = []
    data_flags.append(('Subzona/normativa', subz is not None and subz != ''))
    data_flags.append(('Catastro', bool((official_context or {}).get('catastro', {}).get('available'))))
    data_flags.append(('Habitabilidad', bool(body.get('habitabilidad') if isinstance(body, dict) else False)))
    data_flags.append(('Costes', bool(body.get('costes') if isinstance(body, dict) else False)))
    data_flags.append(('Edificio OSM', bool(body.get('edificio_osm') if isinstance(body, dict) else False)))
    avail_items = ''.join(
        f"<span style='color:{'#2e7d32' if ok else '#f57f17'}'>{'✓' if ok else '○'} {esc(name)}</span>"
        for name, ok in data_flags
    )
    avail_html = f"<p class=muted style='margin-top:6px'>Disponibilidad de datos: {avail_items}</p>"
    resumen_html = bld_summary + cat_summary + siotuga_summary + resumen_html + avail_html
    ficha_rows = ''.join([
        f"<tr><td>Municipio</td><td>{muni or '—'}</td></tr>",
        f"<tr><td>Subzona</td><td>{subz or '—'}</td></tr>",
        f"<tr><td>Proveedor</td><td>{prov_kind}</td></tr>",
        f"<tr><td>Altura máxima (m)</td><td>{_fmt(alt)}</td></tr>",
        f"<tr><td>Retranqueo mínimo (m)</td><td>{_fmt(ret)}</td></tr>",
        f"<tr><td>Ocupación máx</td><td>{_fmt(ocu)}</td></tr>",
        f"<tr><td>Edificabilidad máx</td><td>{_fmt(edi)}</td></tr>",
    ])
    # Datos del edificio en la ficha técnica
    try:
        bld = body.get('edificio_osm') if isinstance(body, dict) else None
        if isinstance(bld, dict) and bld:
            if bld.get('tipo'): ficha_rows += f"<tr><td>Tipo de edificio (OSM)</td><td>{esc(bld['tipo'])}</td></tr>"
            if bld.get('altura_m') is not None: ficha_rows += f"<tr><td>Altura del edificio (m)</td><td>{esc(bld['altura_m'])}</td></tr>"
            if bld.get('altura_fuente'): ficha_rows += f"<tr><td>Procedencia altura</td><td>{esc(bld['altura_fuente'])}</td></tr>"
            if bld.get('plantas'): ficha_rows += f"<tr><td>Plantas (OSM)</td><td>{esc(bld['plantas'])}</td></tr>"
            if bld.get('huella_m2') is not None: ficha_rows += f"<tr><td>Huella del edificio (m²)</td><td>{esc(bld['huella_m2'])}</td></tr>"
    except Exception:
        pass
    # Datos de Catastro en la ficha técnica
    try:
        cat_ctx = (official_context or {}).get('catastro') or {}
        if cat_ctx.get('available'):
            if cat_ctx.get('refcat'): ficha_rows += f"<tr><td>Referencia catastral</td><td>{esc(cat_ctx['refcat'])}</td></tr>"
            if cat_ctx.get('direccion'): ficha_rows += f"<tr><td>Dirección catastral</td><td>{esc(cat_ctx['direccion'])}</td></tr>"
            if cat_ctx.get('superficie_construida_m2'): ficha_rows += f"<tr><td>Sup. construida (Catastro)</td><td>{esc(cat_ctx['superficie_construida_m2'])} m²</td></tr>"
            if cat_ctx.get('superficie_parcela_m2'): ficha_rows += f"<tr><td>Sup. parcela (Catastro)</td><td>{esc(cat_ctx['superficie_parcela_m2'])} m²</td></tr>"
            if cat_ctx.get('uso_principal'): ficha_rows += f"<tr><td>Uso principal</td><td>{esc(cat_ctx['uso_principal'])}</td></tr>"
            if cat_ctx.get('anio_construccion'): ficha_rows += f"<tr><td>Año construcción</td><td>{esc(cat_ctx['anio_construccion'])}</td></tr>"
            if cat_ctx.get('num_unidades'): ficha_rows += f"<tr><td>Unidades catastrales</td><td>{esc(cat_ctx['num_unidades'])}</td></tr>"
            if cat_ctx.get('superficie_comercial_m2'): ficha_rows += f"<tr><td>Sup. no residencial (Catastro)</td><td>{esc(cat_ctx['superficie_comercial_m2'])} m²</td></tr>"
    except Exception:
        pass
    # Datos SIOTUGA en la ficha técnica
    try:
        clas_ctx = (official_context or {}).get('clasificacion_siotuga') or {}
        if clas_ctx.get('clasificacion_ley'):
            ficha_rows += f"<tr><td>Clasificación suelo (SIOTUGA)</td><td>{esc(clas_ctx.get('clasificacion_ley_label') or clas_ctx['clasificacion_ley'])}</td></tr>"
            if clas_ctx.get('id_recinto'): ficha_rows += f"<tr><td>Recinto SIOTUGA</td><td>{esc(clas_ctx['id_recinto'])}</td></tr>"
            if clas_ctx.get('denominacion_zona'): ficha_rows += f"<tr><td>Denominación zona</td><td>{esc(clas_ctx['denominacion_zona'])}</td></tr>"
            if clas_ctx.get('uso_zona'): ficha_rows += f"<tr><td>Uso permitido</td><td>{esc(clas_ctx['uso_zona'])}</td></tr>"
            if clas_ctx.get('edificabilidad_ficha') is not None: ficha_rows += f"<tr><td>Edificabilidad oficial</td><td>{esc(clas_ctx['edificabilidad_ficha'])}</td></tr>"
    except Exception:
        pass
    src_row = ''
    if source_ref:
        try:
            _s = esc(source_ref)
            if isinstance(source_ref, str) and (source_ref.startswith('http://') or source_ref.startswith('https://')):
                _s = f"<a href=\"{_s}\" target=\"_blank\" rel=\"noopener\">{_s}</a>"
            src_row = f"<tr><td>Fuente normativa</td><td>{_s}</td></tr>"
        except Exception:
            src_row = ''
    notes_html = ''
    if notes:
        try:
            notes_html = f"<section>\n      <h2>Observaciones</h2>\n      <p>{esc(notes)}</p>\n    </section>"
        except Exception:
            notes_html = ''

    # Composicion cartografica (Fase 5): SVG mini-mapa con parcela + envolvente
    carto_html = ''
    try:
        parcel_geom = body.get('geometry') if isinstance(body, dict) else None
        # Preferir la geometría real de la parcela de Catastro si está disponible
        cat_parcel_geom = ((official_context or {}).get('catastro') or {}).get('geometry')
        if isinstance(cat_parcel_geom, dict) and cat_parcel_geom.get('coordinates'):
            parcel_geom = cat_parcel_geom
        envelope_feat = None
        if hasattr(res, 'feature') and res.feature:
            envelope_feat = res.feature
        elif isinstance(res, dict) and res.get('feature'):
            envelope_feat = res.get('feature')
        svg = render_svg_minimap(parcel_geom, envelope_feat)
        if svg and 'Sin geometría' not in svg:
            # Enlace a OSM con la ubicación de la parcela
            osm_link = ''
            try:
                from src.zoning_assess import centroid_lonlat_from_geojson
                c_lon, c_lat = centroid_lonlat_from_geojson(parcel_geom)
                if c_lon is not None and c_lat is not None:
                    cat_link = (
                        f'https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCBusqueda.aspx'
                        f'?pest=coordenadas&latitud={c_lat}&longitud={c_lon}&tipoCoordenadas=2'
                    )
                    osm_link = (
                        f'<div class="muted" style="margin-top:6px">'
                        f'<a href="https://www.openstreetmap.org/#map=18/{c_lat:.6f}/{c_lon:.6f}" '
                        f'target="_blank" rel="noopener">Ver en OpenStreetMap</a>'
                        f' · <a href="{cat_link}" target="_blank" rel="noopener">Ver en Catastro</a>'
                        f' · Coordenadas: {c_lon:.6f}, {c_lat:.6f}</div>'
                    )
            except Exception:
                pass
            carto_html = (
                f"<section>\n"
                f"      <div>{svg}</div>\n"
                f"      <div class='muted' style='margin-top:6px'>"
                f"Vista esquemática de la parcela (azul) y la envolvente edificable (rojo). "
                f"Coordenadas en EPSG:4326.</div>"
                f"      {osm_link}\n    </section>"
            )
    except Exception:
        carto_html = ''
    surface_html = ''
    try:
        parcel_area = _num((res.geometry_summary or {}).get('area') or (res.geometry_summary or {}).get('area_m2'))
        cat_parcel_area = _num(((official_context or {}).get('catastro') or {}).get('superficie_parcela_m2'))
        buildable_area = _num(((res.feature or {}) if hasattr(res, 'feature') else (res.get('feature') if isinstance(res, dict) else {})).get('properties', {}).get('area_m2'))
        occ_ratio = _num(ocu)
        occ_cap_area = parcel_area * occ_ratio if parcel_area is not None and occ_ratio is not None else None
        # Huella real del edificio si el frontend la aporta; si no, la envolvente
        footprint = _num(body.get('footprint_m2')) if isinstance(body, dict) else None
        if footprint is None and isinstance(body, dict):
            footprint = _num((body.get('edificio_osm') or {}).get('huella_m2'))
        occupied_area = footprint if footprint is not None else (buildable_area if buildable_area is not None else occ_cap_area)
        occupied_label = ('Huella real del edificio' if footprint is not None
                          else 'Superficie ocupada estimada (envolvente)')
        free_area = max(parcel_area - occupied_area, 0.0) if parcel_area is not None and occupied_area is not None else None
        if any(v is not None for v in (parcel_area, buildable_area, occ_cap_area, free_area, cat_parcel_area)):
            surface_rows = ''.join([
                f"<tr><td>Superficie de parcela (geométrica)</td><td>{_fmt(parcel_area)} m²</td></tr>",
                f"<tr><td>Superficie parcela oficial (Catastro)</td><td>{_fmt(cat_parcel_area)} m²</td></tr>" if cat_parcel_area else '',
                f"<tr><td>{occupied_label}</td><td>{_fmt(occupied_area)} m²</td></tr>",
                f"<tr><td>Superficie libre estimada</td><td>{_fmt(free_area)} m²</td></tr>",
                f"<tr><td>Envolvente edificable</td><td>{_fmt(buildable_area)} m²</td></tr>",
                f"<tr><td>Ocupación máxima teórica</td><td>{_fmt(occ_cap_area)} m²</td></tr>",
            ])
            surface_html = (
                "<section>"
                "<table><thead><tr><th>Concepto</th><th>Valor</th></tr></thead><tbody>"
                f"{surface_rows}"
                "</tbody></table>"
                "<div class='muted' style='margin-top:8px'>"
                "La superficie libre se estima a partir de la huella del edificio (o de la envolvente si no hay huella) "
                "sobre la parcela. La envolvente edificable es el área disponible tras retranqueos.</div>"
                "</section>"
            )
    except Exception:
        surface_html = ''
    # Datos del edificio desde OSM
    building_html = ''
    try:
        bld = body.get('edificio_osm') if isinstance(body, dict) else None
        if isinstance(bld, dict):
            bld_rows = ''
            if bld.get('nombre'): bld_rows += f"<tr><td>Nombre</td><td>{esc(bld['nombre'])}</td></tr>"
            if bld.get('tipo'): bld_rows += f"<tr><td>Tipo de edificio (OSM)</td><td>{esc(bld['tipo'])}</td></tr>"
            if bld.get('altura_m') is not None: bld_rows += f"<tr><td>Altura</td><td>{esc(bld['altura_m'])} m</td></tr>"
            if bld.get('altura_fuente'): bld_rows += f"<tr><td>Procedencia de la altura</td><td>{esc(bld['altura_fuente'])}</td></tr>"
            if bld.get('plantas'): bld_rows += f"<tr><td>Plantas (OSM)</td><td>{esc(bld['plantas'])}</td></tr>"
            if bld.get('huella_m2') is not None: bld_rows += f"<tr><td>Huella aproximada</td><td>{esc(bld['huella_m2'])} m²</td></tr>"
            if bld.get('osm_id'):
                osm_url = f"https://www.openstreetmap.org/way/{esc(bld['osm_id'])}"
                bld_rows += f"<tr><td>OSM ID</td><td><a href=\"{osm_url}\" target=\"_blank\" rel=\"noopener\">{esc(bld['osm_id'])}</a></td></tr>"
            if bld_rows:
                building_html = (
                    "<section>"
                    "<h2>Datos del edificio (OpenStreetMap)</h2>"
                    "<table><tbody>"
                    f"{bld_rows}"
                    "</tbody></table>"
                    "<div class='muted' style='margin-top:8px'>"
                    "Datos procedentes de OpenStreetMap. La altura puede ser estimada por plantas, tipo o valor genérico. "
                    "No sustituye un levantamiento topográfico.</div>"
                    "</section>"
                )
    except Exception:
        building_html = ''
    # Altura medida del edificio (IDEE WCS MDSN / LiDAR) y datos Catastro BU
    measured_html = ''
    try:
        edif = (official_context or {}).get('edificio_datos') or {}
        alt_dp = edif.get('altura') or {}
        rows_m = ''
        labels_q = {'official': 'Oficial', 'measured': 'Medido',
                    'estimated': 'Estimado', 'unavailable': 'No disponible'}
        if alt_dp:
            q = alt_dp.get('data_quality') or 'unavailable'
            val = alt_dp.get('value')
            val_txt = f"{esc(val)} {esc(alt_dp.get('unit') or 'm')}" if val is not None else 'No disponible'
            src = esc(alt_dp.get('source') or '—')
            sref = f" · {esc(alt_dp['source_ref'])}" if alt_dp.get('source_ref') else ''
            rows_m += (
                f"<tr><td>Altura medida</td><td>{val_txt}</td>"
                f"<td>{esc(labels_q.get(q, q))}</td><td>{src}{sref}</td></tr>")
        for campo, nombre in (('plantas', 'Plantas'), ('uso', 'Uso'),
                              ('anio_construccion', 'Año de construcción'),
                              ('edificios_catastro', 'Edificios en parcela')):
            dp = edif.get(campo) or {}
            if dp.get('value') is not None:
                q = dp.get('data_quality') or 'unavailable'
                rows_m += (
                    f"<tr><td>{nombre}</td><td>{esc(dp['value'])} {esc(dp.get('unit') or '')}</td>"
                    f"<td>{esc(labels_q.get(q, q))}</td><td>{esc(dp.get('source') or '—')}</td></tr>")
        if alt_dp.get('data_quality') == 'unavailable' and (edif.get('lidar_tile') or {}).get('available'):
            tile = edif['lidar_tile']
            rows_m += (
                f"<tr><td>Tesela LiDAR disponible</td>"
                f"<td colspan='3'>{esc(tile.get('hoja'))} — "
                f"<a href=\"{esc(tile.get('url_descarga') or '')}\" target=\"_blank\" rel=\"noopener\">descargar (CENDES)</a></td></tr>")
        if rows_m:
            measured_html = (
                "<section id=\"sec-3aa\">"
                "<h2>Altura medida del edificio (IDEE WCS / LiDAR)</h2>"
                "<table><thead><tr><th>Dato</th><th>Valor</th><th>Calidad</th><th>Fuente</th></tr></thead>"
                f"<tbody>{rows_m}</tbody></table>"
                "<div class='muted' style='margin-top:8px'>"
                "Altura derivada del Modelo Digital de Superficies normalizado de edificación "
                "(LiDAR PNOA 1ª cobertura, resolución 2,5 m, percentil P90). "
                "Si hay un fichero LAZ en caché se usa el punto de nube directamente. "
                "No sustituye un levantamiento topográfico ni la verificación del proyectista.</div>"
                "</section>"
            )
    except Exception:
        measured_html = ''
    # Diagnóstico comparativo edificio vs subzona
    diagnostic_html = ''
    try:
        from src.subzones_service import find_subzone_by_name, find_subzone_for_point
        diag_subzone = None
        if subz and muni:
            try:
                diag_subzone = find_subzone_by_name(muni, subz)
            except Exception:
                pass
        if diag_subzone is None and isinstance(body, dict) and body.get('geometry'):
            try:
                from app.main import centroid_lonlat_from_geojson
                lon, lat = centroid_lonlat_from_geojson(body.get('geometry'))
                diag_subzone = find_subzone_for_point(
                    lon, lat, muni if isinstance(muni, str) else None)
            except Exception:
                pass
        # Hueco de cobertura de la capa oficial o punto ambiguo:
        # no hay ordenanza asignable — se trata como "sin subzona".
        diag_nota = None
        if diag_subzone and str((diag_subzone.get('normative_status') or '')).lower() \
                in ('unavailable', 'ambiguous'):
            diag_nota = diag_subzone.get('nota') or \
                'La capa oficial de ordenanzas no determina una ordenanza para este punto.'
            diag_subzone = None
        # Parámetros oficiales del PGOM: si la subzona coincide con una
        # ordenanza extraída de la normativa, tienen prioridad sobre el piloto.
        _ord_code = subz or (diag_subzone or {}).get('ordenanza') \
            or (diag_subzone or {}).get('subzona') or ''
        norma_oficial = None
        try:
            from app.main import _get_ine_for_municipio
            from src.normativa_params import parametros_subzona
            _ine = _get_ine_for_municipio(muni) if muni else None
            if _ine and _ord_code:
                _prs = parametros_subzona(_ine, _ord_code)
                if _prs.get('params'):
                    norma_oficial = _prs
        except Exception:
            norma_oficial = None
        op = (norma_oficial or {}).get('params') or {}
        if diag_subzone or op:
            altura_max = op.get('altura_maxima_m') or (diag_subzone or {}).get('altura_maxima_m')
            ocupacion_max = (op.get('ocupacion_max_pct') / 100.0) if op.get('ocupacion_max_pct') is not None else (diag_subzone or {}).get('ocupacion_max')
            edificabilidad_max = op.get('edificabilidad_max_m2_m2') or (diag_subzone or {}).get('edificabilidad_max_m2_m2')
            retranqueo_min = op.get('retranqueo_lateral_m') or (diag_subzone or {}).get('retranqueo_min_m')
            # Valores del edificio/proyecto desde body; la altura medida (MDSN/LiDAR) tiene preferencia sobre la estimada OSM
            edif = (official_context or {}).get('edificio_datos') or {}
            alt_meas = (edif.get('altura') or {})
            h_meas = _num(alt_meas.get('value')) if alt_meas.get('data_quality') == 'measured' else None
            h_osm = _num(body.get('height_m') or body.get('altura_m')) if isinstance(body, dict) else None
            h = h_meas if h_meas is not None else h_osm
            h_tag = ' <span style="font-size:10px;color:#57606a">(medida)</span>' if h_meas is not None else (' <span style="font-size:10px;color:#57606a">(OSM, estimada)</span>' if h is not None else '')
            lv = body.get('levels') if isinstance(body, dict) else None
            if lv is None and isinstance(body, dict):
                lv = (body.get('edificio_osm') or {}).get('plantas')
            fp = _num(body.get('footprint_m2')) if isinstance(body, dict) else None
            if fp is None and isinstance(body, dict):
                fp = _num((body.get('edificio_osm') or {}).get('huella_m2'))
            pa = _num((res.geometry_summary or {}).get('area') or (res.geometry_summary or {}).get('area_m2'))
            if pa is None:
                pa = _num(((official_context or {}).get('catastro') or {}).get('superficie_parcela_m2'))
            diag_rows = ''
            verdict = 'compatible'
            issues = []
            # Altura
            if h is not None and altura_max is not None:
                diff = round(h - float(altura_max), 2)
                if diff <= 0:
                    diag_rows += f"<tr><td>Altura</td><td>{h} m{h_tag}</td><td>{altura_max} m</td><td style='color:#2e7d32'>✓ {abs(diff)} m margen</td></tr>"
                else:
                    diag_rows += f"<tr><td>Altura</td><td>{h} m{h_tag}</td><td>{altura_max} m</td><td style='color:#c62828'>✗ {diff} m exceso</td></tr>"
                    verdict = 'supera_altura'
                    issues.append(f'Altura: exceso de {diff} m')
            elif altura_max is not None:
                diag_rows += f"<tr><td>Altura</td><td>—</td><td>{altura_max} m</td><td>—</td></tr>"
            # Plantas: estimadas desde la altura cuando OSM no las declara
            lv_eff = lv
            lv_tag = ''
            if lv_eff is None and h is not None and h > 0:
                lv_eff = max(int(round(h / 3.0)), 1)
                lv_tag = ' <span style="font-size:10px;color:#57606a">(estimadas)</span>'
            if altura_max is not None:
                max_levels = int(float(altura_max) / 3.2)
                if lv_eff is not None:
                    if int(lv_eff) <= max_levels:
                        diag_rows += f"<tr><td>Plantas</td><td>{lv_eff}{lv_tag}</td><td>≤ {max_levels}</td><td style='color:#2e7d32'>✓</td></tr>"
                    else:
                        diag_rows += f"<tr><td>Plantas</td><td>{lv_eff}{lv_tag}</td><td>≤ {max_levels}</td><td style='color:#c62828'>✗</td></tr>"
                        if verdict == 'compatible':
                            verdict = 'supera_altura'
                        issues.append(f'Plantas: excede el máximo estimado')
                else:
                    diag_rows += f"<tr><td>Plantas</td><td>—</td><td>≤ {max_levels}</td><td>—</td></tr>"
            # Ocupación: % de huella sobre parcela cuando hay superficie disponible
            if ocupacion_max is not None:
                pct = int(float(ocupacion_max) * 100) if float(ocupacion_max) <= 1 else int(float(ocupacion_max))
                if fp is not None and pa:
                    occ_pct = round(fp / pa * 100.0, 1)
                    if occ_pct <= pct:
                        diag_rows += f"<tr><td>Ocupación</td><td>{occ_pct}% ({fp} m² huella)</td><td>≤ {pct}%</td><td style='color:#2e7d32'>✓</td></tr>"
                    else:
                        diag_rows += f"<tr><td>Ocupación</td><td>{occ_pct}% ({fp} m² huella)</td><td>≤ {pct}%</td><td style='color:#c62828'>✗</td></tr>"
                        if verdict == 'compatible':
                            verdict = 'supera_altura'
                        issues.append(f'Ocupación: {occ_pct}% supera el {pct}% permitido')
                elif fp is not None:
                    diag_rows += f"<tr><td>Ocupación</td><td>{fp} m² (huella)</td><td>≤ {pct}%</td><td>—</td></tr>"
                else:
                    diag_rows += f"<tr><td>Ocupación</td><td>—</td><td>≤ {pct}%</td><td>—</td></tr>"
            # Edificabilidad existente: huella × plantas / parcela
            if edificabilidad_max is not None:
                if fp is not None and pa and lv_eff:
                    edif_real = round(fp * int(lv_eff) / pa, 2)
                    if edif_real <= float(edificabilidad_max):
                        diag_rows += f"<tr><td>Edificabilidad</td><td>{edif_real} m²/m² (exist.)</td><td>≤ {edificabilidad_max} m²/m²</td><td style='color:#2e7d32'>✓</td></tr>"
                    else:
                        diag_rows += f"<tr><td>Edificabilidad</td><td>{edif_real} m²/m² (exist.)</td><td>≤ {edificabilidad_max} m²/m²</td><td style='color:#c62828'>✗</td></tr>"
                        if verdict == 'compatible':
                            verdict = 'supera_altura'
                        issues.append(f'Edificabilidad: {edif_real} supera {edificabilidad_max} m²/m²')
                else:
                    diag_rows += f"<tr><td>Edificabilidad</td><td>—</td><td>≤ {edificabilidad_max} m²/m²</td><td>—</td></tr>"
            # Retranqueo: distancia huella→lindero cuando la geometría base es la parcela catastral
            if retranqueo_min is not None:
                retr_med = None
                try:
                    if (body.get('geometria_base') == 'catastro') and isinstance(body, dict):
                        bgeom = (body.get('edificio_osm') or {}).get('geometria')
                        if bgeom and body.get('geometry'):
                            from shapely.geometry import shape as _shp
                            from src.geo import auto_reproject_to_metric
                            pg, _ = auto_reproject_to_metric(body['geometry'], body.get('crs') or 'EPSG:4326')
                            bg, _ = auto_reproject_to_metric(bgeom, body.get('crs') or 'EPSG:4326')
                            pgeom, bgeom_s = _shp(pg), _shp(bg)
                            if pgeom.is_valid and not bgeom_s.is_empty:
                                retr_med = round(float(bgeom_s.distance(pgeom.boundary)), 2)
                except Exception:
                    retr_med = None
                if retr_med is not None:
                    if retr_med >= float(retranqueo_min) - 0.01:
                        diag_rows += f"<tr><td>Retranqueo mín.</td><td>{retr_med} m (geom.)</td><td>≥ {retranqueo_min} m</td><td style='color:#2e7d32'>✓</td></tr>"
                    else:
                        diag_rows += f"<tr><td>Retranqueo mín.</td><td>{retr_med} m (geom.)</td><td>≥ {retranqueo_min} m</td><td style='color:#c62828'>✗</td></tr>"
                        issues.append(f'Retranqueo: {retr_med} m < {retranqueo_min} m')
                else:
                    diag_rows += f"<tr><td>Retranqueo mín.</td><td>—</td><td>≥ {retranqueo_min} m</td><td>—</td></tr>"
            verdict_label = {'compatible': 'Compatible (orientativo)', 'supera_altura': 'Supera parámetros (orientativo)', 'sin_dato': 'Sin datos'}.get(verdict, verdict)
            verdict_color = '#2e7d32' if verdict == 'compatible' else '#c62828'
            _diag_status = str((diag_subzone or {}).get('normative_status') or '').lower()
            if norma_oficial:
                _ord = esc((norma_oficial.get('resultado') or {}).get('ordenanza') or _ord_code or '')
                _fn = esc((norma_oficial.get('resultado') or {}).get('fuente') or 'PGOM')
                norma_tag = f"<span style='color:#2e7d32'>(ordenanza {_ord}, oficial PGOM — {_fn})</span>"
            elif _diag_status == 'official':
                _fs = esc((diag_subzone or {}).get('fuente') or 'capa oficial municipal')
                norma_tag = f"<span style='color:#2e7d32'>(ordenanza oficial — {_fs}; sin parámetros extraídos del PDF)</span>"
            else:
                norma_tag = "<span style='color:#f57f17'>(parámetros de subzona piloto, no oficiales)</span>"
            issues_html = ''.join(f"<li>{esc(i)}</li>" for i in issues) if issues else ''
            diagnostic_html = (
                "<section>"
                f"<div class='muted' style='margin-bottom:8px'>Veredicto: <strong style='color:{verdict_color}'>{esc(verdict_label)}</strong> "
                f"{norma_tag}</div>"
                "<table><thead><tr><th>Parámetro</th><th>Edificio</th><th>Norma</th><th>Estado</th></tr></thead><tbody>"
                f"{diag_rows}"
                "</tbody></table>"
                f"{'<ul>' + issues_html + '</ul>' if issues_html else ''}"
                "<div class='muted' style='margin-top:6px'>Nota: las alturas de edificios existentes pueden ser estimadas a partir de OSM y no sustituyen un levantamiento topográfico. "
                + ("Los parámetros normativos proceden de la ordenanza oficial extraída del PGOM. " if norma_oficial else
                   "Los parámetros de la subzona son orientativos (datos piloto), no oficiales. Consulte el planeamiento municipal para los valores normativos reales. ")
                + "</div>"
                "</section>"
            )
        else:
            # Sin subzona: mostrar datos del edificio disponibles (altura medida preferida)
            edif = (official_context or {}).get('edificio_datos') or {}
            alt_meas = (edif.get('altura') or {})
            h_meas = _num(alt_meas.get('value')) if alt_meas.get('data_quality') == 'measured' else None
            h = h_meas if h_meas is not None else (_num(body.get('height_m') or body.get('altura_m')) if isinstance(body, dict) else None)
            lv = body.get('levels') if isinstance(body, dict) else None
            if lv is None and isinstance(body, dict):
                lv = (body.get('edificio_osm') or {}).get('plantas')
            fp = _num(body.get('footprint_m2')) if isinstance(body, dict) else None
            if fp is None and isinstance(body, dict):
                fp = _num((body.get('edificio_osm') or {}).get('huella_m2'))
            diag_rows = ''
            if h is not None:
                h_tag = ' (medida)' if h_meas is not None else ' (OSM)'
                diag_rows += f"<tr><td>Altura del edificio</td><td>{h} m{h_tag}</td><td>—</td><td>—</td></tr>"
            if lv is not None:
                diag_rows += f"<tr><td>Plantas (OSM)</td><td>{lv}</td><td>—</td><td>—</td></tr>"
            if fp is not None:
                diag_rows += f"<tr><td>Huella</td><td>{fp} m²</td><td>—</td><td>—</td></tr>"
            if diag_rows:
                diagnostic_html = (
                    "<section>"
                    "<div class='muted' style='margin-bottom:8px'>Sin subzona normativa asociada. "
                    + (esc(diag_nota) + ' ' if diag_nota else '')
                    + "Los parámetros normativos (altura máxima, ocupación, edificabilidad, retranqueo) "
                    "no están disponibles para esta zona.</div>"
                    "<table><thead><tr><th>Parámetro</th><th>Edificio</th><th>Norma</th><th>Estado</th></tr></thead><tbody>"
                    f"{diag_rows}"
                    "</tbody></table>"
                    "<div class='muted' style='margin-top:6px'>Consulte el planeamiento municipal en SIOTUGA o el ayuntamiento "
                    "para obtener los parámetros normativos aplicables a esta parcela.</div>"
                    "</section>"
                )
    except Exception:
        diagnostic_html = ''
    # Parámetros oficiales por ordenanza extraídos del PGOM (PDFs SIOTUGA)
    ordenanzas_html = ''
    try:
        from app.main import _get_ine_for_municipio
        from src.normativa_params import parametros_subzona
        _ine = _get_ine_for_municipio(muni) if muni else None
        _ords = {}
        if _ine:
            _prs = parametros_subzona(_ine)
            _ords = _prs.get('ordenanzas') or {}
            if _prs.get('resultado'):
                _ords = {_prs['ordenanza']: _prs['resultado']}
        if _ords:
            rows_o = ''
            _empty_ords = []
            for _code, _o in sorted(_ords.items()):
                _p = _o.get('params') or {}
                if not _p:
                    _empty_ords.append(_code)
                    continue
                _oc = f"{_p['ocupacion_max_pct']:g}%" if _p.get('ocupacion_max_pct') is not None else '—'
                _ed = f"{_p['edificabilidad_max_m2_m2']:g}" if _p.get('edificabilidad_max_m2_m2') is not None else '—'
                _alt = f"{_p['altura_maxima_m']:g} m" if _p.get('altura_maxima_m') is not None else '—'
                _ret_parts = []
                if _p.get('retranqueo_frontal_m') is not None:
                    _ret_parts.append(f"frente {_p['retranqueo_frontal_m']:g}")
                if _p.get('retranqueo_lateral_m') is not None:
                    _ret_parts.append(f"lat {_p['retranqueo_lateral_m']:g}")
                if _p.get('retranqueo_posterior_m') is not None:
                    _ret_parts.append(f"post {_p['retranqueo_posterior_m']:g}")
                _ret = ' / '.join(_ret_parts) + ' m' if _ret_parts else '—'
                _pm = f"{_p['parcela_minima_m2']:g} m²" if _p.get('parcela_minima_m2') is not None else '—'
                rows_o += (
                    f"<tr><td><b>{esc(_code)}</b></td><td>{esc(_o.get('titulo') or '—')}</td>"
                    f"<td>{_oc}</td><td>{_ed}</td><td>{_alt}</td><td>{_ret}</td><td>{_pm}</td>"
                    f"<td class='muted' style='font-size:10px'>{esc(_o.get('fuente') or '')}</td></tr>")
            _empty_note = ''
            if _empty_ords:
                _empty_note = (
                    "<div class='muted' style='margin-top:6px'>Ordenanzas sin parámetros numéricos extraíbles "
                    f"(conservan la edificabilidad existente o se rigen por planos/licencias): {esc(', '.join(_empty_ords))}.</div>")
            ordenanzas_html = (
                "<section id=\"sec-3d\">"
                "<h2>Parámetros por ordenanza (PGOM oficial)</h2>"
                "<table><thead><tr><th>Ordenanza</th><th>Denominación</th><th>Ocupación</th>"
                "<th>Edificabilidad</th><th>Altura</th><th>Recuados (m)</th><th>Parcela mín.</th><th>Fuente</th></tr></thead>"
                f"<tbody>{rows_o}</tbody></table>"
                f"{_empty_note}"
                "<div class='muted' style='margin-top:8px'>Parámetros extraídos automáticamente de la normativa urbanística oficial "
                "(PDF del plan vigente descargado de SIOTUGA), con trazabilidad de página. "
                "Para conocer la ordenanza aplicable a la parcela consulte el plano de ordenación del plan. "
                "No sustituye la consulta del planeamiento municipal.</div>"
                "</section>"
            )
    except Exception:
        ordenanzas_html = ''
    habitability_html = ''
    try:
        habitability_input = body.get('habitabilidad') if isinstance(body, dict) else None
        if isinstance(habitability_input, dict):
            from src.habitabilidad_checker import check_habitability
            habitability = check_habitability(habitability_input)
            status_label = {
                'cumple': 'Cumple las reglas comprobables',
                'no_cumple': 'No cumple',
                'no_verificable': 'No verificable con los datos aportados',
            }.get(habitability.estado_global, habitability.estado_global)
            status_color = {'cumple': '#2e7d32', 'no_cumple': '#c62828', 'no_verificable': '#f57f17'}.get(habitability.estado_global, '#37474f')
            check_rows = ''.join(
                f"<tr><td>{esc(check.parametro)}</td><td>{esc(check.valor_observado)}</td><td>{esc(check.requisito)}</td><td>{esc(check.estado)}</td><td>{esc(check.referencia)}</td></tr>"
                for check in habitability.comprobaciones
            )
            source_rows = ''.join(
                f"<li><a href='{esc(source['url'])}'>{esc(source['nombre'])}</a></li>"
                for source in habitability.fuentes
            )
            habitability_html = (
                "<section id='sec-3c'>"
                "<h2><span class='section-num'>3.2</span>Verificación de habitabilidad</h2>"
                f"<div style='color:{status_color};font-weight:700;margin-bottom:8px'>{esc(status_label)}</div>"
                f"<div class='muted'>{esc(habitability.normativa)} · versión de reglas {esc(habitability.version_reglas)}</div>"
                "<table><thead><tr><th>Parámetro</th><th>Observado</th><th>Requisito</th><th>Estado</th><th>Referencia</th></tr></thead><tbody>"
                f"{check_rows}</tbody></table>"
            )
            # Datos pendientes
            missing_items = [c for c in habitability.comprobaciones if c.estado == 'no_verificable']
            if missing_items:
                missing_list = ''.join(
                    f"<li>{esc(c.parametro)}: {esc(c.detalle)}</li>"
                    for c in missing_items[:5]
                )
                habitability_html += (
                    f"<div class='muted' style='margin-top:8px'><b>Datos pendientes ({len(missing_items)}):</b>"
                    f"<ul>{missing_list}</ul>"
                    "Aporte las dimensiones del proyecto terminado en el formulario de habitabilidad del visor "
                    "para verificar estas reglas.</div>"
                )
            habitability_html += (
                f"<h3>Fuentes oficiales</h3><ul>{source_rows}</ul>"
                "<div class='muted'>Prechequeo técnico; no sustituye la revisión profesional, el planeamiento municipal ni el resto de normativa aplicable.</div>"
                "</section>"
            )
    except Exception:
        habitability_html = ''
    economic_html = ''
    try:
        edi_ratio = _num(edi)
        # Fallback a la edificabilidad oficial de SIOTUGA si el plan no la tiene
        if edi_ratio is None:
            try:
                clas_ec = (official_context or {}).get('clasificacion_siotuga') or {}
                edi_ratio = _num(clas_ec.get('edificabilidad_ficha'))
            except Exception:
                pass
        alt_m = _num(alt)
        bld_footprint = _num(body.get('footprint_m2')) if isinstance(body, dict) else None
        bld_height = _num(body.get('height_m')) if isinstance(body, dict) else None
        if isinstance(body, dict):
            _osm = body.get('edificio_osm') or {}
            if bld_footprint is None:
                bld_footprint = _num(_osm.get('huella_m2'))
            if bld_height is None:
                _edif = (official_context or {}).get('edificio_datos') or {}
                _alt = _edif.get('altura') or {}
                bld_height = _num(_alt.get('value')) if _alt.get('data_quality') == 'measured' else _num(_osm.get('altura_m'))
        footprint = buildable_area if buildable_area is not None else occ_cap_area
        if footprint is None and bld_footprint is not None:
            footprint = bld_footprint
        eff_alt = alt_m if alt_m is not None else bld_height
        total_buildable_m2 = None
        if footprint is not None and eff_alt is not None:
            floors = max(int(round(eff_alt / 3.0)), 1) if eff_alt > 0 else 1
            total_buildable_m2 = footprint * floors
        elif edi_ratio is not None and parcel_area is not None:
            total_buildable_m2 = parcel_area * edi_ratio
        avg_dwelling_m2 = 90.0
        dwellings = None
        if total_buildable_m2 is not None:
            dwellings = max(int(total_buildable_m2 / avg_dwelling_m2), 0)
        if any(v is not None for v in (total_buildable_m2, dwellings, edi_ratio)):
            econ_rows = ''.join([
                f"<tr><td>Superficie edificable total estimada</td><td>{_fmt(total_buildable_m2)} m²</td></tr>",
                f"<tr><td>Plantas estimadas (h/3m)</td><td>{_fmt(int(round(eff_alt / 3.0)) if eff_alt else None)}</td></tr>" if eff_alt else '',
                f"<tr><td>Edificabilidad (m²/m²)</td><td>{_fmt(edi_ratio)}</td></tr>" if edi_ratio is not None else '',
                f"<tr><td>Viviendas potenciales (≈{int(avg_dwelling_m2)} m²/viv)</td><td>{_fmt(dwellings)}</td></tr>" if dwellings is not None else '',
            ])
            econ_source = "Estimación orientativa basada en la envolvente, altura y edificabilidad." if buildable_area is not None else "Estimación orientativa basada en la huella y altura del edificio (sin datos de subzona)."
            if edi_ratio is not None and pe.get('edificabilidad_max_m2_m2') is None:
                econ_source += " Edificabilidad procedente de la clasificación SIOTUGA oficial."
            economic_html = (
                "<section>"
                "<table><thead><tr><th>Concepto</th><th>Valor</th></tr></thead><tbody>"
                f"{econ_rows}"
                "</tbody></table>"
                f"<div class='muted' style='margin-top:8px'>"
                f"{econ_source} "
                "No sustituye un estudio económico ni de mercado. La superficie media por vivienda es una hipótesis por defecto.</div>"
                "</section>"
            )
    except Exception:
        economic_html = ''
    shadow_html = ''
    try:
        from src.shadow_service import shadow_analysis_multi_hour
        import datetime as _sdt
        parcel_geom = body.get('geometry') if isinstance(body, dict) else None
        env_feat = None
        if hasattr(res, 'feature') and res.feature:
            env_feat = res.feature
        elif isinstance(res, dict) and res.get('feature'):
            env_feat = res.get('feature')
        shadow_geom = None
        if env_feat and isinstance(env_feat, dict):
            shadow_geom = env_feat.get('geometry')
        if shadow_geom is None and parcel_geom:
            shadow_geom = parcel_geom
        shadow_alt = _num(alt) or _num(body.get('height_m')) if isinstance(body, dict) else _num(alt)
        if shadow_geom and shadow_alt:
            centroid_lon = None
            centroid_lat = None
            try:
                from src.zoning_assess import centroid_lonlat_from_geojson
                centroid_lon, centroid_lat = centroid_lonlat_from_geojson(shadow_geom)
            except Exception:
                pass
            if centroid_lon is not None and centroid_lat is not None:
                winter = _sdt.date(_sdt.date.today().year, 12, 21)
                shadow_res = shadow_analysis_multi_hour(
                    shadow_geom, float(shadow_alt), centroid_lat, centroid_lon, winter,
                    hours=[8, 10, 12, 14, 16, 18],
                )
                shadow_rows = ''
                for r in shadow_res.get('results', []):
                    hour = r.get('hour_utc', '?')
                    solar = r.get('solar', {})
                    elev = solar.get('elevation_deg', '—')
                    azim = solar.get('azimuth_deg', '—')
                    slen = r.get('shadow_length_m', 0)
                    has_shadow = 'Sí' if r.get('has_shadow') else 'No'
                    shadow_rows += (
                        f"<tr><td>{hour}:00 UTC</td><td>{elev}°</td><td>{azim}°</td>"
                        f"<td>{slen} m</td><td>{has_shadow}</td></tr>"
                    )
                shadow_html = (
                    "<section>"
                    "<div class='muted' style='margin-bottom:6px'>Solsticio de invierno</div>"
                    "<table><thead><tr><th>Hora</th><th>Elevación solar</th><th>Azimut solar</th><th>Longitud sombra</th><th>Sombra</th></tr></thead><tbody>"
                    f"{shadow_rows}"
                    "</tbody></table>"
                    f"<div class='muted' style='margin-top:8px'>Sombra máxima: {shadow_res.get('max_shadow_length_m', '—')} m. "
                    "Análisis preliminar basado en modelo solar simplificado; no considera sombras entre edificios ni relieve. "
                    "No sustituye un estudio de soleamiento oficial.</div>"
                    "</section>"
                )
    except Exception:
        shadow_html = ''
    solar_html = ''
    try:
        from src.solar_analysis import analyze_solar_exposure, render_solar_exposure_html
        parcel_geom = body.get('geometry') if isinstance(body, dict) else None
        env_feat = None
        if hasattr(res, 'feature') and res.feature:
            env_feat = res.feature
        elif isinstance(res, dict) and res.get('feature'):
            env_feat = res.get('feature')
        solar_geom = None
        if env_feat and isinstance(env_feat, dict):
            solar_geom = env_feat.get('geometry')
        if solar_geom is None and parcel_geom:
            solar_geom = parcel_geom
        if solar_geom:
            from src.zoning_assess import centroid_lonlat_from_geojson
            s_lon, s_lat = centroid_lonlat_from_geojson(solar_geom)
            if s_lon is not None and s_lat is not None:
                solar_res = analyze_solar_exposure(s_lat, s_lon)
                solar_inner = render_solar_exposure_html(solar_res)
                solar_html = (
                    "<section id='sec-5b'>"
                    "<h2><span class='section-num'>5.1</span>Soleamiento por orientación</h2>"
                    f"{solar_inner}"
                    "</section>"
                )
    except Exception:
        solar_html = ''
    cost_html = ''
    try:
        cost_input = body.get('costes') if isinstance(body, dict) else None
        if isinstance(cost_input, dict):
            from src.cost_estimator import estimate_conversion_costs
            cost_res = estimate_conversion_costs(cost_input)
            cost_rows = []
            if cost_res.coste_obra_total is not None:
                cost_rows.append(f"<tr><td>Coste de obra</td><td>{esc(cost_res.coste_obra_total)} €</td></tr>")
            if cost_res.coste_total_inversion is not None:
                cost_rows.append(f"<tr><td>Inversión total</td><td>{esc(cost_res.coste_total_inversion)} €</td></tr>")
            if cost_res.coste_por_m2_total is not None:
                cost_rows.append(f"<tr><td>Coste total/m²</td><td>{esc(cost_res.coste_por_m2_total)} €/m²</td></tr>")
            if cost_res.beneficio_bruto_venta is not None:
                cost_rows.append(f"<tr><td>Beneficio bruto (venta)</td><td>{esc(cost_res.beneficio_bruto_venta)} €</td></tr>")
            if cost_res.roi_venta_pct is not None:
                cost_rows.append(f"<tr><td>ROI (venta)</td><td>{esc(cost_res.roi_venta_pct)}%</td></tr>")
            if cost_res.payback_alquiler_meses is not None:
                cost_rows.append(f"<tr><td>Payback (alquiler)</td><td>{esc(cost_res.payback_alquiler_meses)} meses</td></tr>")
            if cost_res.rentabilidad_alquiler_anual_pct is not None:
                cost_rows.append(f"<tr><td>Rentabilidad alq. anual</td><td>{esc(cost_res.rentabilidad_alquiler_anual_pct)}%</td></tr>")
            cost_rows_html = ''.join(cost_rows)
            cost_warnings = ''.join(f"<div class='muted' style='color:#f57f17'>{esc(w)}</div>" for w in cost_res.advertencias)
            cost_limits = ''.join(f"<div class='muted'>{esc(l)}</div>" for l in cost_res.limitaciones)
            cost_source = f"<div class='muted'>Fuente: {esc(cost_res.fuente_costes)}</div>" if cost_res.fuente_costes else ''
            cost_html = (
                "<section id='sec-5c'>"
                "<h2><span class='section-num'>5.2</span>Estimación de costes de conversión</h2>"
                f"<table><thead><tr><th>Concepto</th><th>Valor</th></tr></thead><tbody>{cost_rows_html}</tbody></table>"
                f"{cost_source}{cost_warnings}{cost_limits}"
                "</section>"
            )
    except Exception:
        cost_html = ''
    if not cost_html:
        cost_html = (
            "<section id='sec-5c'>"
            "<h2><span class='section-num'>5.2</span>Estimación de costes de conversión</h2>"
            "<div class='muted'>Pendiente de aportar datos de mercado. "
            "Use el botón \"Estimar costes de conversión\" en el visor para introducir "
            "coste de obra (€/m²), tasas, valor de venta y alquiler esperado, "
            "y regenere el informe para incluir esta sección.</div>"
            "</section>"
        )
    official_html = ''
    if official_context:
        try:
            cat = official_context.get('catastro') or {}
            pl = official_context.get('planeamiento') or {}
            si = official_context.get('siotuga') or {}
            af = official_context.get('afecciones_preliminares') or {}
            cat_rows = ''.join([
                f"<tr><td>Referencia catastral</td><td>{esc(cat.get('refcat') or '—')}</td></tr>",
                f"<tr><td>Dirección catastral</td><td>{esc(cat.get('direccion') or '—')}</td></tr>",
                f"<tr><td>Coordenadas consulta</td><td>{esc(cat.get('query_lon'))}, {esc(cat.get('query_lat'))}</td></tr>" if cat.get('query_lon') is not None and cat.get('query_lat') is not None else '',
                f"<tr><td>Superficie terreno</td><td>{esc(cat.get('superficie_terreno_m2') or '—')} m²</td></tr>" if cat.get('superficie_terreno_m2') else '',
                f"<tr><td>Superficie parcela (Catastro)</td><td>{esc(cat.get('superficie_parcela_m2') or '—')} m²</td></tr>" if cat.get('superficie_parcela_m2') else '',
                f"<tr><td>Superficie construida</td><td>{esc(cat.get('superficie_construida_m2') or '—')} m²</td></tr>" if cat.get('superficie_construida_m2') else '',
                f"<tr><td>Uso principal</td><td>{esc(cat.get('uso_principal') or '—')}</td></tr>" if cat.get('uso_principal') else '',
                f"<tr><td>Año construcción</td><td>{esc(cat.get('anio_construccion') or '—')}</td></tr>" if cat.get('anio_construccion') else '',
                f"<tr><td>Valor catastral</td><td>{esc(cat.get('valor_catastral') or '—')} €</td></tr>" if cat.get('valor_catastral') else '',
                f"<tr><td>Municipio catastral</td><td>{esc(cat.get('municipio_catastral') or '—')}</td></tr>" if cat.get('municipio_catastral') else '',
                f"<tr><td>Consistencia coordenadas</td><td>{esc(cat.get('coord_consistency') or '—')}</td></tr>" if cat.get('coord_consistency') else '',
                f"<tr><td>Consistencia municipio</td><td>{esc(cat.get('municipio_consistency') or '—')}</td></tr>" if cat.get('municipio_consistency') else '',
                f"<tr><td>Edificios en parcela (Catastro INSPIRE BU)</td><td>{esc(cat.get('edificios_oficiales'))}</td></tr>" if cat.get('edificios_oficiales') else '',
                f"<tr><td>Plantas (Catastro INSPIRE BU)</td><td>{esc(cat.get('plantas_oficiales'))}</td></tr>" if cat.get('plantas_oficiales') else '',
            ])
            # Desglose de usos del inmueble (Catastro DNPRC)
            usos_rows = ''
            usos_det = cat.get('usos_detalle') or {}
            if usos_det:
                usos_rows = ''.join(
                    f"<tr><td>{esc(u)}</td><td>{esc(round(v, 1))} m²</td></tr>"
                    for u, v in sorted(usos_det.items(), key=lambda x: -x[1])
                )
                usos_html = (
                    "<div class='muted' style='margin-top:8px'><b>Desglose de usos catastrales:</b></div>"
                    f"<table><thead><tr><th>Uso</th><th>Superficie</th></tr></thead><tbody>{usos_rows}</tbody></table>"
                )
            else:
                usos_html = ''
            # Unidades no residenciales (candidatas a conversión)
            unidades_html = ''
            unidades = cat.get('unidades_comerciales') or []
            if unidades:
                unidades_rows = ''.join(
                    f"<tr><td>{esc(u.get('car') or '—')}</td><td>{esc(u.get('uso') or '—')}</td>"
                    f"<td>{esc(u.get('sfc'))} m²</td><td>{esc(u.get('planta') or '—')}</td><td>{esc(u.get('puerta') or '—')}</td></tr>"
                    for u in unidades
                )
                unidades_html = (
                    f"<div class='muted' style='margin-top:8px'><b>Unidades no residenciales ({len(unidades)}):</b>"
                    f" Superficie total no residencial: <strong>{esc(cat.get('superficie_comercial_m2'))} m²</strong></div>"
                    "<table><thead><tr><th>Sub-ref</th><th>Uso</th><th>Superficie</th><th>Planta</th><th>Puerta</th></tr></thead>"
                    f"<tbody>{unidades_rows}</tbody></table>"
                    "<div class='muted' style='margin-top:4px'>Estas unidades son candidatas a cambio de uso a vivienda según su uso catastral actual.</div>"
                )
            inv_rows = pl.get('rows') or []
            planeamiento_items = ''.join(
                f"<li>{esc(r.get('CONCELLO') or r.get('Concello') or r.get('municipio') or '')} · {esc(r.get('FIGURA') or r.get('Figura') or r.get('figura') or 'Planeamiento')} · {esc(r.get('ESTADO') or r.get('Estado') or r.get('estado') or '—')}</li>"
                for r in inv_rows[:5]
            ) or '<li>Sin filas de inventario municipal disponibles</li>'
            afecciones_items = ''.join(f"<li>{esc(x)}</li>" for x in (af.get('alerts') or [])) or '<li>Sin alertas preliminares detectadas</li>'
            coberturas_items = ''.join(f"<li>{esc(x)}</li>" for x in (af.get('land_cover_labels') or [])) or '<li>Sin coberturas resumidas</li>'
            # Enlaces a fuentes oficiales con contexto específico
            official_links = (official_context or {}).get('official_links') or []
            if official_links:
                fuentes_links = ''.join([
                    f"<li><a href=\"{esc(link.get('url') or '')}\" target=\"_blank\" rel=\"noopener\">{esc(link.get('name') or '')}: {esc(link.get('label') or '')}</a></li>"
                    for link in official_links
                ])
            else:
                # Fallback si no hay official_links
                qlon = cat.get('query_lon')
                qlat = cat.get('query_lat')
                if qlon is not None and qlat is not None:
                    catastro_link = (
                        f"https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCListaBienes.aspx"
                        f"?pest=coordenadas&latitud={qlat}&longitud={qlon}"
                        f"&tipoCoordenadas=2&TipUR=Coor&from=OVCBusqueda&final="
                    )
                    catastro_label = f"Catastro — Ver parcela ({qlon:.4f}, {qlat:.4f})"
                else:
                    catastro_link = "https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCBusqueda.aspx"
                    catastro_label = "Catastro — Buscador de inmuebles"
                siotuga_link = "https://siotuga.xunta.gal/siotuga/inventario?lang=es_ES"
                siotuga_label = f"SIOTUGA — Inventario de planeamiento de {muni or 'Galicia'}"
                if qlon is not None and qlat is not None:
                    siose_link = (
                        f"https://servicios.idee.es/wms-inspire/ocupacion-suelo"
                        f"?service=WMS&request=GetFeatureInfo&version=1.3.0"
                        f"&layers=LC.LandCoverSurfaces&query_layers=LC.LandCoverSurfaces"
                        f"&crs=CRS:84&bbox={qlon-0.001},{qlat-0.001},{qlon+0.001},{qlat+0.001}"
                        f"&width=101&height=101&i=50&j=50&info_format=text/html"
                    )
                    siose_label = "SIOSE — Ver ocupación del suelo en esta parcela"
                else:
                    siose_link = "https://servicios.idee.es/wms-inspire/ocupacion-suelo?service=WMS&request=GetCapabilities&version=1.3.0"
                    siose_label = "SIOSE — Servicio de ocupación del suelo (IDEE/INSPIRE)"
                fuentes_links = ''.join([
                    f"<li><a href=\"{catastro_link}\" target=\"_blank\" rel=\"noopener\">{esc(catastro_label)}</a></li>",
                    f"<li><a href=\"{siotuga_link}\" target=\"_blank\" rel=\"noopener\">{esc(siotuga_label)}</a></li>",
                    f"<li><a href=\"{siose_link}\" target=\"_blank\" rel=\"noopener\">{esc(siose_label)}</a></li>",
                ])
            # Clasificación SIOTUGA (WFS)
            clas = (official_context or {}).get('clasificacion_siotuga') or {}
            clas_rows = ''
            if clas.get('clasificacion_ley') or clas.get('clasificacion_plan'):
                clas_rows += f"<tr><td>Clasificación del suelo (SIOTUGA)</td><td>{esc(clas.get('clasificacion_ley_label') or clas.get('clasificacion_ley') or '—')}</td></tr>"
                if clas.get('id_recinto'):
                    clas_rows += f"<tr><td>ID de recinto</td><td>{esc(clas['id_recinto'])}</td></tr>"
                if clas.get('denominacion_zona'):
                    clas_rows += f"<tr><td>Denominación</td><td>{esc(clas['denominacion_zona'])}</td></tr>"
                if clas.get('uso_zona'):
                    clas_rows += f"<tr><td>Uso permitido</td><td>{esc(clas['uso_zona'])}</td></tr>"
                if clas.get('edificabilidad_ficha') is not None:
                    clas_rows += f"<tr><td>Edificabilidad (ficha)</td><td>{esc(clas['edificabilidad_ficha'])}</td></tr>"
                if clas.get('sup_ficha_m2'):
                    clas_rows += f"<tr><td>Superficie de ficha</td><td>{esc(round(clas['sup_ficha_m2'], 0))} m²</td></tr>"
                if clas.get('observaciones_zona'):
                    clas_rows += f"<tr><td>Observaciones</td><td>{esc(clas['observaciones_zona'])}</td></tr>"
                if clas.get('area_zona_m2'):
                    _az = round(float(clas['area_zona_m2']))
                    _az_txt = f"{_az/1e6:,.2f} km²".replace(',', ' ') if _az >= 1e6 else f"{_az:,} m²".replace(',', ' ')
                    clas_rows += f"<tr><td>Área de la zona</td><td>{_az_txt}</td></tr>"
            official_html = (
                "<section>"
                f"<div class='muted' style='margin-bottom:8px'>Calidad de datos: <strong>{esc(official_context.get('data_quality') or '—')}</strong></div>"
                "<table><tbody>"
                f"<tr><td>Catastro disponible</td><td>{esc(cat.get('available'))}</td></tr>"
                f"<tr><td>Planeamiento inventario</td><td>{esc(pl.get('count') or 0)} registros</td></tr>"
                f"<tr><td>Contexto SIOTUGA</td><td>{esc(si.get('note') or '—')}</td></tr>"
                f"<tr><td>Afecciones preliminares</td><td>{esc(af.get('available'))}</td></tr>"
                f"{cat_rows}"
                f"{clas_rows}"
                "</tbody></table>"
                f"{usos_html}"
                f"{unidades_html}"
                "<div class='muted' style='margin-top:8px'>"
                "Referencia rápida de inventario/planeamiento municipal:</div>"
                f"<ul>{planeamiento_items}</ul>"
                "<div class='muted' style='margin-top:8px'>Coberturas SIOSE próximas:</div>"
                f"<ul>{coberturas_items}</ul>"
                "<div class='muted' style='margin-top:8px'>Afecciones preliminares a revisar:</div>"
                f"<ul>{afecciones_items}</ul>"
                f"<div class='muted' style='margin-top:8px'>{esc(af.get('disclaimer') or '')}</div>"
                "<div class='muted' style='margin-top:10px'>Fuentes oficiales consultadas:</div>"
                f"<ul>{fuentes_links}</ul>"
                "</section>"
            )
        except Exception:
            official_html = ''
    provenance_html = ''
    try:
        prov = (official_context or {}).get('provenance') or {}
        if prov:
            prov_rows = ''.join([
                f"<tr><td>Fecha de consulta</td><td>{esc(prov.get('query_timestamp') or '—')}</td></tr>",
                f"<tr><td>Versión de la API</td><td>{esc(prov.get('api_version') or '—')}</td></tr>",
            ])
            sources_items = ''
            for s in (prov.get('sources') or []):
                name = esc(s.get('name') or '—')
                url = s.get('url') or ''
                stype = esc(s.get('type') or '—')
                if url:
                    sources_items += f"<li>{name} ({stype}) — <a href=\"{esc(url)}\" target=\"_blank\" rel=\"noopener\">{esc(url)}</a></li>"
                else:
                    sources_items += f"<li>{name} ({stype})</li>"
            dps = (official_context or {}).get('data_points') or {}
            dps_rows = ''
            if dps:
                labels = {'official': 'Oficial', 'measured': 'Medido',
                          'estimated': 'Estimado', 'unavailable': 'No disponible'}
                for field, dp in dps.items():
                    q = dp.get('data_quality') or 'unavailable'
                    val = dp.get('value')
                    unit = dp.get('unit') or ''
                    dps_rows += (
                        f"<tr><td>{esc(field)}</td>"
                        f"<td>{esc(val if val is not None else '—')} {esc(unit)}</td>"
                        f"<td>{esc(labels.get(q, q))}</td>"
                        f"<td>{esc(dp.get('source') or '—')}{' · ' + esc(dp['source_ref']) if dp.get('source_ref') else ''}</td></tr>"
                    )
                dps_rows = (
                    "<div class='muted' style='margin-top:10px'>Trazabilidad por dato:</div>"
                    "<table><thead><tr><th>Dato</th><th>Valor</th><th>Calidad</th><th>Fuente</th></tr></thead>"
                    f"<tbody>{dps_rows}</tbody></table>"
                )
            provenance_html = (
                "<section>"
                "<table><tbody>"
                f"{prov_rows}"
                "</tbody></table>"
                "<div class='muted' style='margin-top:8px'>Fuentes consultadas y su tipo:</div>"
                f"<ul>{sources_items}</ul>"
                f"{dps_rows}"
                "<div class='muted' style='margin-top:8px'>"
                "Los datos oficiales se consultan en tiempo real. La disponibilidad depende del servicio externo en el momento de la consulta.</div>"
                "</section>"
            )
    except Exception:
        provenance_html = ''
    html = f"""
<!doctype html>
<html lang=es>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{ttl}</title>
  <style>
    :root{{
      --fg:#eaeaea; --bg:#111; --card:#1a1a1a; --line:#2e2e2e; --muted:#b0b0b0; --accent:{esc(brand_color) if brand_color else '#607d8b'};
    }}
    body{{font-family:"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg);margin:24px;line-height:1.45;}}
    .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 24px;max-width:980px;margin:0 auto;}}
    h1{{margin:0 0 8px 0;font-size:24px;font-weight:650;letter-spacing:.2px;}}
    h2{{margin:18px 0 8px 0;font-size:18px;font-weight:600;}}
    h3{{margin:16px 0 8px 0;font-size:16px;font-weight:600;}}
    .badge{{display:inline-block;padding:4px 12px;border-radius:18px;border:1px solid {color};color:{color};font-weight:600;}}
    h2, h3{{ border-left:4px solid var(--accent); padding-left:8px; }}
    .meta{{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-top:2px}}
    table{{width:100%;border-collapse:collapse;margin-top:10px;}}
    th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;font-size:14px;vertical-align:top;}}
    th{{color:var(--muted);font-weight:600;}}
    ul{{margin:6px 0 0 20px;}}
    .muted{{opacity:0.85;font-size:13px;}}
    .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px;}}
    .toolbar{{position:sticky;top:0;display:flex;gap:8px;margin-bottom:14px}}
    .toolbar button{{padding:6px 10px;border:1px solid #4a4a4a;background:#1f1f1f;color:#eee;border-radius:6px;cursor:pointer}}
    .toolbar button:hover{{background:#2a2a2a}}
    footer{{margin-top:18px;color:var(--muted);font-size:12px}}
    .cover{{text-align:center;padding:40px 20px 30px;border-bottom:2px solid var(--accent);margin-bottom:24px}}
    .cover h1{{font-size:28px;margin:0 0 8px;border:none;padding:0}}
    .cover .subtitle{{font-size:15px;color:var(--muted);margin:4px 0}}
    .cover .badge-large{{display:inline-block;padding:8px 20px;border-radius:24px;border:2px solid {color};color:{color};font-weight:700;font-size:16px;margin:12px 0}}
    .toc{{background:rgba(255,255,255,0.03);border:1px solid var(--line);border-radius:8px;padding:16px 20px;margin-bottom:20px}}
    .toc h2{{margin-top:0;font-size:15px;border:none;padding:0}}
    .toc ol{{margin:6px 0 0 18px;padding:0}}
    .toc li{{margin:4px 0;font-size:13px}}
    .toc a{{color:var(--accent);text-decoration:none}}
    .toc a:hover{{text-decoration:underline}}
    .section-num{{display:inline-block;background:var(--accent);color:#fff;border-radius:4px;padding:2px 8px;font-size:12px;font-weight:700;margin-right:8px}}
    @media print{{
      body{{background:#fff;color:#000;margin:0;font-family:"Georgia", "Times New Roman", Times, serif;}}
      .card{{border:none;border-radius:0;padding:0 2mm;}}
      .toolbar{{display:none}}
      a[href]::after{{content:"";}}
      h1{{font-size:22px}}
      h2{{font-size:16px}}
      h3{{font-size:14px}}
      .cover{{page-break-after:always;border-bottom:2px solid #333}}
      .toc{{page-break-after:always}}
      @page{{margin:14mm}}
    }}
  </style>
  <meta name="format-detection" content="telephone=no"/>
  <meta name="color-scheme" content="dark light"/>
</head>
<body>
  <div class="toolbar">
    <button onclick="window.print()">Descargar PDF</button>
    <button onclick="window.close()">Cerrar</button>
  </div>
  <div class="card">
    <div class="cover">
      {logo_html}
      <h1>{ttl}</h1>
      <div class="subtitle">Informe de viabilidad urbanística preliminar</div>
      <div class="subtitle">Normativa Galicia 3D · {esc(gen_date)}</div>
      <div class="badge-large">{v or '—'}</div>
      {loc_txt}
      {client_proj}
      {area_txt}
    </div>
    <div class="toc">
      <h2>Índice</h2>
      <ol>
        <li><a href="#sec-1">Resumen ejecutivo</a></li>
        {f'<li><a href="#sec-2">Composición cartográfica</a></li>' if carto_html else ''}
        {f'<li><a href="#sec-3">Cuadro de superficies</a></li>' if surface_html else ''}
        {f'<li><a href="#sec-3a">Datos del edificio (OSM)</a></li>' if building_html else ''}
        {f'<li><a href="#sec-3aa">Altura medida (IDEE/LiDAR)</a></li>' if measured_html else ''}
        {f'<li><a href="#sec-3b">Diagnóstico comparativo</a></li>' if diagnostic_html else ''}
        {f'<li><a href="#sec-3d">Ordenanzas PGOM</a></li>' if ordenanzas_html else ''}
        {f'<li><a href="#sec-3c">Verificación de habitabilidad</a></li>' if habitability_html else ''}
        {f'<li><a href="#sec-4">Estimación económica preliminar</a></li>' if economic_html else ''}
        {f'<li><a href="#sec-5">Análisis de sombras</a></li>' if shadow_html else ''}
        {f'<li><a href="#sec-5b">Soleamiento por orientación</a></li>' if solar_html else ''}
        {f'<li><a href="#sec-5c">Estimación de costes de conversión</a></li>' if cost_html else ''}
        {f'<li><a href="#sec-6">Datos oficiales y contexto</a></li>' if official_html else ''}
        <li><a href="#sec-7">Parámetros efectivos</a></li>
        <li><a href="#sec-8">Ficha técnica</a></li>
        <li><a href="#sec-9">Viabilidad y motivos</a></li>
        {f'<li><a href="#sec-10">Observaciones</a></li>' if notes_html else ''}
        <li><a href="#sec-11">Firma</a></li>
      </ol>
    </div>
    <section id="sec-1">
      <h2><span class="section-num">1</span>Resumen ejecutivo</h2>
      {resumen_html}
    </section>
    {snap_html}
    <section id="sec-2">
      <h2><span class="section-num">2</span>Composición cartográfica</h2>
      {carto_html or '<div class="muted">Sin geometría para mostrar.</div>'}
    </section>
    <section id="sec-3">
      <h2><span class="section-num">3</span>Cuadro de superficies</h2>
      {surface_html or '<div class="muted">Sin datos de superficie disponibles.</div>'}
    </section>
    {building_html}
    {measured_html}
    <section id="sec-3b">
      <h2><span class="section-num">3.1</span>Diagnóstico comparativo edificio vs subzona</h2>
      {diagnostic_html or '<div class="muted">Sin datos de subzona o edificio para el diagnóstico.</div>'}
    </section>
    {ordenanzas_html}
    {habitability_html}
    <section id="sec-4">
      <h2><span class="section-num">4</span>Estimación económica preliminar</h2>
      {economic_html or '<div class="muted">Sin datos suficientes para la estimación.</div>'}
    </section>
    <section id="sec-5">
      <h2><span class="section-num">5</span>Análisis de sombras</h2>
      {shadow_html or '<div class="muted">Sin datos de altura o geometría para el análisis de sombras.</div>'}
    </section>
    {solar_html}
    {cost_html}
    <section id="sec-6">
      <h2><span class="section-num">6</span>Datos oficiales y contexto</h2>
      {official_html or '<div class="muted">Sin contexto oficial disponible.</div>'}
    </section>
    <section id="sec-6b">
      <h2><span class="section-num">6.1</span>Proveniencia de los datos</h2>
      {provenance_html or '<div class="muted">Sin metadatos de proveniencia.</div>'}
    </section>
    <section id="sec-7">
      <h2><span class="section-num">7</span>Parámetros efectivos</h2>
      <table>
        <thead><tr><th>Parámetro</th><th>Valor</th></tr></thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </section>
    <section id="sec-8">
      <h2><span class="section-num">8</span>Ficha técnica</h2>
      <table>
        <tbody>
          {ficha_rows}
          {src_row}
        </tbody>
      </table>
    </section>
    <section id="sec-9" class="grid2">
      <div>
        <h2><span class="section-num">9</span>Viabilidad</h2>
        <div class="muted">Resultado: {v or '—'}</div>
      </div>
      <div>
        <h2>Motivos</h2>
        <ul>{reasons or '<li>—</li>'}</ul>
      </div>
    </section>
    <section id="sec-10">
      {notes_html}
    </section>
    <section id="sec-11" style="margin-top:14px;">
      <h2><span class="section-num">11</span>Firma</h2>
      {sig_html}
    </section>
    <footer style="margin-top:14px;">
      Este informe es orientativo y no sustituye a la verificación oficial del planeamiento vigente. Revise siempre la normativa y planos urbanísticos aplicables.
    </footer>
  </div>

</body>
</html>
"""
    return html
