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


def render_assess_report_html(body: dict, res: Any, *, logo: Optional[str] = None, title: Optional[str] = None, client: Optional[str] = None, project: Optional[str] = None, snapshot_data_url: Optional[str] = None, brand_color: Optional[str] = None, signature: bool = False, sign_by: Optional[str] = None, sign_place: Optional[str] = None, notes: Optional[str] = None, source_ref: Optional[str] = None) -> str:
    import html as _html
    def esc(x: str) -> str:
        try:
            return _html.escape(x if isinstance(x, str) else str(x))
        except Exception:
            return str(x)
    v = (res.viability or '').upper()
    color = {'APTO':'#2e7d32','CONDICIONADO':'#f57f17','NO APTO':'#c62828'}.get(v, (brand_color or '#37474f'))
    reasons = ''.join(f"<li>{esc(r)}</li>" for r in (res.reasons or []))
    pe = res.params_effective or {}
    rows = ''
    for k in ['altura_maxima_m','retranqueo_min_m','setback_front_m','setback_side_m','setback_back_m','front_direction','front_direction_source']:
        rows += f"<tr><td>{esc(k)}</td><td>{esc(pe.get(k))}</td></tr>"
    area_txt = ''
    try:
        a = (res.geometry_summary or {}).get('area') or (res.geometry_summary or {}).get('area_m2')
        if a is not None:
            area_txt = f"<div class=muted>Área de parcela: {esc(round(float(a), 2))} m²</div>"
    except Exception:
        pass
    muni = (body.get('municipio') or '').strip() if isinstance(body, dict) else ''
    subz = (body.get('subzona') or '').strip() if isinstance(body, dict) else ''
    loc_txt = ''
    if muni or subz:
        loc_txt = f"<div class=muted>Municipio: {esc(muni) or '—'}{(' · Subzona: ' + esc(subz)) if subz else ''}</div>"
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
        muni = esc((res.context or {}).get('municipio') or (body.get('municipio') if isinstance(body, dict) else '') or '')
    except Exception:
        muni = ''
    try:
        subz = esc((res.context or {}).get('subzona') or (body.get('subzona') if isinstance(body, dict) else '') or '')
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
    ficha_rows = ''.join([
        f"<tr><td>Municipio</td><td>{muni or '—'}</td></tr>",
        f"<tr><td>Subzona</td><td>{subz or '—'}</td></tr>",
        f"<tr><td>Proveedor</td><td>{prov_kind}</td></tr>",
        f"<tr><td>Altura máxima (m)</td><td>{_fmt(alt)}</td></tr>",
        f"<tr><td>Retranqueo mínimo (m)</td><td>{_fmt(ret)}</td></tr>",
        f"<tr><td>Ocupación máx</td><td>{_fmt(ocu)}</td></tr>",
        f"<tr><td>Edificabilidad máx</td><td>{_fmt(edi)}</td></tr>",
    ])
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
        envelope_feat = None
        if hasattr(res, 'feature') and res.feature:
            envelope_feat = res.feature
        elif isinstance(res, dict) and res.get('feature'):
            envelope_feat = res.get('feature')
        svg = render_svg_minimap(parcel_geom, envelope_feat)
        if svg and 'Sin geometría' not in svg:
            carto_html = (
                f"<section>\n      <h2>Composición cartográfica</h2>\n"
                f"      <div>{svg}</div>\n"
                f"      <div class='muted' style='margin-top:6px'>"
                f"Vista esquemática de la parcela (azul) y la envolvente edificable (rojo). "
                f"Coordenadas en EPSG:4326.</div>\n    </section>"
            )
    except Exception:
        carto_html = ''
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
    @media print{{
      body{{background:#fff;color:#000;margin:0;font-family:"Georgia", "Times New Roman", Times, serif;}}
      .card{{border:none;border-radius:0;padding:0 2mm;}}
      .toolbar{{display:none}}
      a[href]::after{{content:"";}}
      h1{{font-size:22px}}
      h2{{font-size:16px}}
      h3{{font-size:14px}}
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
    <header style="display:flex;align-items:flex-start;gap:12px;justify-content:space-between">
      <div style="display:flex;align-items:center;gap:12px">{logo_html}<h1 style="margin:0">{ttl}</h1></div>
      <div class="muted">Generado: {esc(gen_date)}</div>
    </header>
    <div class="meta">
      <span class="badge">{v}</span>
      {loc_txt}
      {client_proj}
      {area_txt}
    </div>
    {resumen_html}
    {snap_html}
    {carto_html}
    <section>
      <h2>Parámetros efectivos</h2>
      <table>
        <thead><tr><th>Parámetro</th><th>Valor</th></tr></thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </section>
    <section>
      <h2>Ficha técnica</h2>
      <table>
        <tbody>
          {ficha_rows}
          {src_row}
        </tbody>
      </table>
    </section>
    <section class="grid2">
      <div>
        <h2>Viabilidad</h2>
        <div class="muted">Resultado: {v or '—'}</div>
      </div>
      <div>
        <h2>Motivos</h2>
        <ul>{reasons or '<li>—</li>'}</ul>
      </div>
    </section>
    {notes_html}
    <section style="margin-top:14px;">
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
