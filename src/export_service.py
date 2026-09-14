from src.rules_engine import get_plan_params_dynamic
from src.volume import VolumeParams, compute_building_envelope

SUPPORTED_VOLUME_EXPORT_FORMATS = ('cityjson', 'gltf', 'glb', 'ifc')


def normalize_volume_export_format(format: str | None) -> str:
    fmt = (format or 'cityjson').strip().lower()
    if fmt not in SUPPORTED_VOLUME_EXPORT_FORMATS:
        raise ValueError("Formato no soportado: use 'cityjson', 'gltf', 'glb' o 'ifc'")
    return fmt


def build_volume_export_feature(req, fmt: str, strict: bool = False) -> dict | None:
    altura = req.altura_maxima_m
    retranqueo = req.retranqueo_min_m or 0.0
    if altura is None:
        if req.municipio:
            plan = get_plan_params_dynamic(req.municipio, req.subzona)
            if plan.altura_maxima_m is None:
                raise ValueError("El plan municipal no devuelve altura máxima")
            altura = plan.altura_maxima_m
            if req.retranqueo_min_m is None and plan.retranqueo_min_m is not None:
                retranqueo = plan.retranqueo_min_m
            pf = getattr(plan, 'setback_front_m', None)
            ps = getattr(plan, 'setback_side_m', None)
            pb = getattr(plan, 'setback_back_m', None)
            pfd = getattr(plan, 'front_direction_default', None)
            effective_front_direction = req.front_direction
            has_plan_dir_setbacks = (pf is not None) or (ps is not None) or (pb is not None)
            if (effective_front_direction is None and req.street_axis is None and bool(req.use_plan_front_default) and pfd and has_plan_dir_setbacks):
                effective_front_direction = pfd
            if effective_front_direction is not None or req.street_axis is not None:
                setback_front = req.setback_front_m if req.setback_front_m is not None else pf
                setback_side = req.setback_side_m if req.setback_side_m is not None else ps
                setback_back = req.setback_back_m if req.setback_back_m is not None else pb
            else:
                setback_front = req.setback_front_m
                setback_side = req.setback_side_m
                setback_back = req.setback_back_m
        else:
            raise ValueError("altura_maxima_m requerida si no se especifica municipio")
    else:
        setback_front = req.setback_front_m
        setback_side = req.setback_side_m
        setback_back = req.setback_back_m

    feature = None
    try:
        has_any_setbacks = bool(retranqueo and float(retranqueo) > 0) or any(
            v is not None and float(v) > 0 for v in (setback_front, setback_side, setback_back)
        )
        if (not strict) and fmt in ('gltf', 'glb') and (not has_any_setbacks) and (not req.use_plan_front_default) and isinstance(req.geometry, dict):
            g = req.geometry
            if (g.get('type') == 'Polygon') and isinstance(g.get('coordinates'), list):
                coords = g.get('coordinates')
                if len(coords) == 1 and len(coords[0]) >= 4:
                    feature = {
                        'type': 'Feature',
                        'geometry': g,
                        'properties': {
                            'height_m': float(altura or 0.0),
                            'area_m2': None,
                        }
                    }
        if feature is None:
            feature = compute_building_envelope(
                req.geometry,
                VolumeParams(
                    altura_maxima_m=altura,
                    retranqueo_min_m=retranqueo,
                    setback_front_m=setback_front,
                    setback_side_m=setback_side,
                    setback_back_m=setback_back,
                    front_direction=req.front_direction,
                ),
                street_axis=req.street_axis,
                front_direction_source=None,
                crs=getattr(req, 'crs', None),
            )
    except Exception:
        if (not strict) and fmt == 'cityjson' and isinstance(req.geometry, dict) and req.geometry.get('type') in ('Polygon', 'MultiPolygon'):
            feature = {
                'type': 'Feature',
                'geometry': req.geometry,
                'properties': {
                    'height_m': float(altura or 0.0),
                    'area_m2': None,
                }
            }
        else:
            raise
    return feature


def is_exhausted_feature(feature: dict | None) -> bool:
    try:
        if not feature:
            return True
        props = feature.get('properties') or {}
        area = props.get('area_m2')
        if area is None:
            return False
        return float(area) <= 1e-8
    except Exception:
        return False


def extrude_polygon_to_cityjson(feature: dict) -> dict:
    """Convierte un Feature 2D (Polygon/MultiPolygon, con o sin huecos) a CityJSON.
    - Cada polígono se extruye como un Solid independiente.
    - Top/Bottom incluyen huecos si existen; paredes para anillos exteriores e interiores.
    """
    if not feature or not isinstance(feature, dict):
        raise ValueError("feature inválido")
    geom = feature.get('geometry') or {}
    gtype = geom.get('type')
    h = float((feature.get('properties') or {}).get('height_m') or 0.0)
    if h <= 0:
        raise ValueError("height_m debe ser > 0")

    vert_index: dict[tuple[float, float, float], int] = {}
    vertices: list[list[float]] = []

    def _vid(x: float, y: float, z: float) -> int:
        key = (float(x), float(y), float(z))
        idx = vert_index.get(key)
        if idx is not None:
            return idx
        vertices.append([float(x), float(y), float(z)])
        idx = len(vertices) - 1
        vert_index[key] = idx
        return idx

    def _ensure_closed(ring) -> list[list[float]]:
        ring = [list(pt) for pt in ring]
        if len(ring) < 4:
            raise ValueError("Anillo inválido")
        if ring[0] != ring[-1]:
            return ring + [ring[0]]
        return ring

    def _process_polygon(poly_coords) -> dict:
        if not poly_coords or not isinstance(poly_coords, (list, tuple)):
            raise ValueError("Coordenadas de polígono inválidas")
        rings = [
            _ensure_closed(r) for r in poly_coords
        ]
        top_loops: list[list[int]] = []
        bottom_loops: list[list[int]] = []
        for ring in rings:
            top_loop: list[int] = []
            bottom_loop: list[int] = []
            for (x, y) in ring[:-1]:
                bottom_loop.append(_vid(x, y, 0.0))
                top_loop.append(_vid(x, y, h))
            top_loops.append(top_loop)
            bottom_loops.append(bottom_loop)
        surfaces: list[list[list[int]]] = []
        surfaces.append(top_loops)
        surfaces.append([list(reversed(loop)) for loop in bottom_loops])
        for b_loop, t_loop in zip(bottom_loops, top_loops):
            n = len(t_loop)
            for i in range(n):
                i2 = (i + 1) % n
                v0 = b_loop[i]
                v1 = b_loop[i2]
                v2 = t_loop[i2]
                v3 = t_loop[i]
                surfaces.append([[v0, v1, v2, v3]])
        wall_count = sum(len(tl) for tl in top_loops)
        wall_count = 0
        for t_loop in top_loops:
            wall_count += len(t_loop)
        semantics = {
            "surfaces": (
                [{"type": "RoofSurface"}, {"type": "GroundSurface"}] +
                ([{"type": "WallSurface"}] * wall_count)
            )
        }
        return {
            "type": "Solid",
            "lod": 2,
            "boundaries": [[s for s in surfaces]],
            "semantics": semantics,
        }

    geometries: list[dict] = []
    if gtype == 'Polygon':
        coords = geom.get('coordinates')
        geometries.append(_process_polygon(coords))
    elif gtype == 'MultiPolygon':
        for poly in (geom.get('coordinates') or []):
            geometries.append(_process_polygon(poly))
    else:
        raise ValueError("Tipo de geometría no soportado para CityJSON (use Polygon o MultiPolygon)")

    return {
        "type": "CityJSON",
        "version": "1.0",
        "vertices": vertices,
        "CityObjects": {
            "building-1": {
                "type": "Building",
                "geometry": geometries,
                "attributes": {
                    "height_m": h,
                    "area_m2": (feature.get('properties') or {}).get('area_m2')
                }
            }
        }
    }


def extrude_polygon_to_gltf(feature: dict) -> dict:
    """Convierte el Feature 2D en un GLTF 2.0 embebido (data URI) sin dependencias externas.
    Limitaciones: Polygon sin huecos.
    """
    geom = feature.get('geometry') or {}
    if geom.get('type') != 'Polygon':
        raise ValueError("Solo se soporta Polygon sin huecos para exportación GLTF")
    coords = geom.get('coordinates') or []
    if len(coords) == 0 or len(coords) > 1:
        raise ValueError("No se soportan huecos ni geometrías vacías en GLTF")
    ring = coords[0]
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        raise ValueError("Anillo inválido")
    h = float((feature.get('properties') or {}).get('height_m') or 0.0)
    if h <= 0:
        raise ValueError("height_m debe ser > 0")
    bottom = [(float(x), float(y), 0.0) for (x, y) in ring]
    top = [(float(x), float(y), h) for (x, y) in ring]
    vertices = bottom + top
    n = len(ring)
    indices: list[int] = []
    top_off = n
    for i in range(1, n - 1):
        indices.extend([top_off, top_off + i, top_off + i + 1])
    for i in range(1, n - 1):
        indices += [0, i + 1, i]
    for i in range(n):
        i2 = (i + 1) % n
        b0 = i
        b1 = i2
        t1 = top_off + i2
        t0 = top_off + i
        indices += [b0, b1, t1, b0, t1, t0]
    import struct, base64
    pos_bytes = struct.pack('<' + 'f' * (len(vertices) * 3), *[c for v in vertices for c in v])

    def _pad4(b: bytes) -> bytes:
        pad = (4 - (len(b) % 4)) % 4
        return b + (b'\x00' * pad)

    pos_bytes = _pad4(pos_bytes)
    idx_bytes = struct.pack('<' + 'I' * len(indices), *indices)
    idx_bytes = _pad4(idx_bytes)
    buf = pos_bytes + idx_bytes
    uri = 'data:application/octet-stream;base64,' + base64.b64encode(buf).decode('ascii')
    pos_view = {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962}
    idx_view = {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(idx_bytes), "target": 34963}
    xs = [v[0] for v in vertices]; ys = [v[1] for v in vertices]; zs = [v[2] for v in vertices]
    minv = [min(xs), min(ys), min(zs)]
    maxv = [max(xs), max(ys), max(zs)]
    pos_acc = {"bufferView": 0, "componentType": 5126, "count": len(vertices), "type": "VEC3", "min": minv, "max": maxv}
    idx_acc = {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"}
    return {
        "asset": {"version": "2.0", "generator": "Asistente Normativa Galicia"},
        "buffers": [{"byteLength": len(buf), "uri": uri}],
        "bufferViews": [pos_view, idx_view],
        "accessors": [pos_acc, idx_acc],
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0},
                "indices": 1
            }]
        }],
        "nodes": [{"mesh": 0, "name": "building"}],
        "scenes": [{"nodes": [0]}],
        "scene": 0
    }


def gltf_to_glb_bytes(gltf: dict) -> bytes:
    """Convierte un GLTF 2.0 (JSON) con buffer embebido (data URI base64) a GLB binario.
    Requisitos: un único buffer con "uri" data: y sin recursos externos.
    """
    import base64 as _b64
    import json as _json
    import struct as _struct

    buffers = gltf.get('buffers') or []
    if len(buffers) != 1:
        raise ValueError("Se requiere un único buffer embebido")
    uri = buffers[0].get('uri')
    if not uri or not uri.startswith('data:'):
        raise ValueError("Buffer debe estar embebido como data URI")
    try:
        b64 = uri.split(',', 1)[1]
        bin_data = _b64.b64decode(b64)
    except Exception as e:
        raise ValueError(f"URI embebido inválido: {e}")
    buffers[0].pop('uri', None)
    buffers[0]['byteLength'] = len(bin_data)

    json_bytes = _json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    def _pad4(b: bytes) -> bytes:
        rem = (4 - (len(b) % 4)) % 4
        return b + (b' ' * rem)
    json_chunk = _pad4(json_bytes)
    bin_chunk = _pad4(bin_data)

    magic = 0x46546C67
    version = 2
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    header = _struct.pack('<III', magic, version, total_length)

    JSON_TYPE = 0x4E4F534A
    BIN_TYPE = 0x004E4942
    json_header = _struct.pack('<II', len(json_chunk), JSON_TYPE)
    bin_header = _struct.pack('<II', len(bin_chunk), BIN_TYPE)

    return header + json_header + json_chunk + bin_header + bin_chunk


def extrude_polygon_to_ifc(feature: dict) -> str:
    """Convierte un Feature 2D (Polygon) en un archivo IFC 4 STEP mínimo sin dependencias externas.

    Genera un IfcProject > IfcSite > IfcBuilding > IfcBuildingElementProxy con
    geometría de extrusión lineal (IfcExtrudedAreaSolid) a partir del anillo exterior.

    Limitaciones: solo Polygon, solo anillo exterior (sin huecos), coordenadas locales
    centradas en el centroide del polígono.
    """
    if not feature or not isinstance(feature, dict):
        raise ValueError("feature inválido")
    geom = feature.get('geometry') or {}
    if geom.get('type') != 'Polygon':
        raise ValueError("Solo se soporta Polygon para exportación IFC")
    coords = geom.get('coordinates') or []
    if not coords:
        raise ValueError("Coordenadas inválidas")
    ring = coords[0]
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        raise ValueError("Anillo inválido")

    h = float((feature.get('properties') or {}).get('height_m') or 0.0)
    if h <= 0:
        raise ValueError("height_m debe ser > 0")

    # Centroid para coordenadas locales
    cx = sum(float(p[0]) for p in ring) / len(ring)
    cy = sum(float(p[1]) for p in ring) / len(ring)
    local_pts = [(float(p[0]) - cx, float(p[1]) - cy) for p in ring]

    lines: list[str] = []
    eid = 1

    def _next():
        nonlocal eid
        eid += 1
        return eid

    # --- Header ---
    lines.append("ISO-10303-21;")
    lines.append("HEADER;")
    lines.append("FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'), '2;1');")
    lines.append("FILE_NAME('building.ifc', '', ('NormativaGalicia'), ('NormativaGalicia'), 'manual', 'NormativaGalicia', '');")
    lines.append("FILE_SCHEMA(('IFC4'));")
    lines.append("ENDSEC;")
    lines.append("DATA;")

    # --- Units ---
    id_len = _next()
    id_area_unit = _next()
    id_vol_unit = _next()
    lines.append(f"#{id_len} = IFCSIUNIT(*, .LENGTHUNIT., $, .METRE.);")
    lines.append(f"#{id_area_unit} = IFCSIUNIT(*, .AREAUNIT., $, .METRE.);")
    lines.append(f"#{id_vol_unit} = IFCSIUNIT(*, .VOLUMEUNIT., $, .METRE.);")

    id_unit_assignment = _next()
    lines.append(f"#{id_unit_assignment} = IFCUNITASSIGNMENT((#{id_len}, #{id_area_unit}, #{id_vol_unit}));")

    # --- Cartesian point origin ---
    id_origin = _next()
    lines.append(f"#{id_origin} = IFCCARTESIANPOINT((0.0, 0.0, 0.0));")

    # --- Axis2D3D placement ---
    id_axis3d = _next()
    id_place3d = _next()
    lines.append(f"#{id_axis3d} = IFCDIRECTION((0.0, 0.0, 1.0));")
    lines.append(f"#{id_place3d} = IFCAXIS2PLACEMENT3D(#{id_origin}, #{id_axis3d}, $);")

    # --- Geometric representation context ---
    id_ctx = _next()
    lines.append(f"#{id_ctx} = IFCGEOMETRICREPRESENTATIONCONTEXT($, 'Model', 3, 1.0E-5, #{id_place3d}, $);")

    # --- Polygon profile (anillo exterior) ---
    id_pts = []
    for (px, py) in local_pts:
        pid = _next()
        lines.append(f"#{pid} = IFCCARTESIANPOINT(({px:.6f}, {py:.6f}));")
        id_pts.append(pid)
    # Cerrar el polígono repitiendo el primer punto
    id_pts_closed = id_pts + [id_pts[0]]

    id_polyline = _next()
    pts_ref = ', '.join(f'#{p}' for p in id_pts_closed)
    lines.append(f"#{id_polyline} = IFCPOLYLINE(({pts_ref}));")

    id_profile = _next()
    lines.append(f"#{id_profile} = IFCARBITRARYCLOSEDPROFILEDEF(.AREA., 'BuildingProfile', #{id_polyline});")

    # --- Extruded area solid ---
    id_extrude_dir = _next()
    lines.append(f"#{id_extrude_dir} = IFCDIRECTION((0.0, 0.0, 1.0));")

    id_extrude_origin = _next()
    lines.append(f"#{id_extrude_origin} = IFCCARTESIANPOINT((0.0, 0.0, 0.0));")
    id_extrude_axis = _next()
    lines.append(f"#{id_extrude_axis} = IFCDIRECTION((0.0, 0.0, 1.0));")
    id_extrude_ref_dir = _next()
    lines.append(f"#{id_extrude_ref_dir} = IFCDIRECTION((1.0, 0.0, 0.0));")
    id_extrude_place = _next()
    lines.append(f"#{id_extrude_place} = IFCAXIS2PLACEMENT3D(#{id_extrude_origin}, #{id_extrude_axis}, #{id_extrude_ref_dir});")

    id_solid = _next()
    lines.append(f"#{id_solid} = IFCEXTRUDEDAREASOLID(#{id_profile}, #{id_extrude_place}, #{id_extrude_dir}, {h:.6f});")

    # --- Shape representation ---
    id_shape_rep = _next()
    lines.append(f"#{id_shape_rep} = IFCSHAPEREPRESENTATION(#{id_ctx}, 'Body', 'SweptSolid', (#{id_solid}));")

    id_product_def = _next()
    lines.append(f"#{id_product_def} = IFCPRODUCTDEFINITIONSHAPE($, $, (#{id_shape_rep}));")

    # --- Local placement for building element ---
    id_elem_origin = _next()
    lines.append(f"#{id_elem_origin} = IFCCARTESIANPOINT((0.0, 0.0, 0.0));")
    id_elem_axis = _next()
    lines.append(f"#{id_elem_axis} = IFCDIRECTION((0.0, 0.0, 1.0));")
    id_elem_ref = _next()
    lines.append(f"#{id_elem_ref} = IFCDIRECTION((1.0, 0.0, 0.0));")
    id_elem_place = _next()
    lines.append(f"#{id_elem_place} = IFCLOCALPLACEMENT($, IFCAXIS2PLACEMENT3D(#{id_elem_origin}, #{id_elem_axis}, #{id_elem_ref}));")

    # --- Building element proxy ---
    id_proxy = _next()
    lines.append(f"#{id_proxy} = IFCBUILDINGELEMENTPROXY(#{id_proxy}, $, 'Building', $, $, #{id_elem_place}, #{id_product_def}, $, $);")

    # --- Site placement ---
    id_site_place = _next()
    lines.append(f"#{id_site_place} = IFCLOCALPLACEMENT($, IFCAXIS2PLACEMENT3D(#{id_origin}, #{id_axis3d}, $));")

    # --- Site ---
    id_site = _next()
    lines.append(f"#{id_site} = IFCSITE(#{id_site}, 'Site', $, $, #{id_site_place}, $, $, .ELEMENT., $, $, $, $, $);")

    # --- Building placement ---
    id_bld_place = _next()
    lines.append(f"#{id_bld_place} = IFCLOCALPLACEMENT(#{id_site_place}, IFCAXIS2PLACEMENT3D(#{id_origin}, #{id_axis3d}, $));")

    # --- Building ---
    id_bld = _next()
    lines.append(f"#{id_bld} = IFCBUILDING(#{id_bld}, 'Building', $, $, #{id_bld_place}, $, $, .ELEMENT., $, $, $);")

    # --- Rel contained in spatial ---
    id_rel_contained = _next()
    lines.append(f"#{id_rel_contained} = ICRELCONTAINEDINSPATIALSTRUCTURE(#{id_rel_contained}, $, $, (#{id_proxy}), #{id_bld});")

    # --- Rel aggregates site > building ---
    id_rel_agg_site = _next()
    lines.append(f"#{id_rel_agg_site} = IFCRELAGGREGATES(#{id_rel_agg_site}, $, $, #{id_site}, (#{id_bld}));")

    # --- Project ---
    id_proj = _next()
    lines.append(f"#{id_proj} = IFCPROJECT(#{id_proj}, 'Project', $, $, $, $, $, (#{id_ctx}), #{id_unit_assignment});")

    # --- Rel aggregates project > site ---
    id_rel_agg_proj = _next()
    lines.append(f"#{id_rel_agg_proj} = IFCRELAGGREGATES(#{id_rel_agg_proj}, $, $, #{id_proj}, (#{id_site}));")

    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;")

    return '\n'.join(lines) + '\n'
