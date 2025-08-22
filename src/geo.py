from __future__ import annotations
from typing import Any, Dict, Tuple
from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform
from pyproj import Transformer, CRS


def reproject_geojson(geometry: Dict[str, Any], src_crs: str, dst_crs: str) -> Dict[str, Any]:
    """Reproject a GeoJSON geometry dict from src_crs to dst_crs.
    CRS strings like 'EPSG:4326'. Returns a new GeoJSON geometry.
    """
    if not geometry:
        raise ValueError("geometry is required")
    if not src_crs or not dst_crs:
        raise ValueError("src_crs and dst_crs are required")

    if src_crs == dst_crs:
        return geometry

    crs_src = CRS.from_user_input(src_crs)
    crs_dst = CRS.from_user_input(dst_crs)
    transformer = Transformer.from_crs(crs_src, crs_dst, always_xy=True)

    geom = shape(geometry)
    reproj = shp_transform(transformer.transform, geom)
    return mapping(reproj)


def choose_metric_crs_for_galicia(lon: float) -> str:
    """Return an ETRS89 / UTM metric CRS suitable for Galicia by longitude.
    Rough split at -6 deg: west -> EPSG:25829, east -> EPSG:25830.
    """
    return "EPSG:25829" if lon <= -6.0 else "EPSG:25830"


def auto_reproject_to_metric(geometry: Dict[str, Any], src_crs: str) -> Tuple[Dict[str, Any], str]:
    """If src_crs is not metric, reproject geometry to a suitable metric CRS for Galicia.
    Returns (reprojected_geometry, target_crs).
    If src_crs is already a projected metric CRS, returns input geometry and src_crs.
    """
    if not geometry:
        raise ValueError("geometry is required")
    # If src is geographic WGS84, pick UTM zone by centroid lon
    crs_src = CRS.from_user_input(src_crs)
    geom = shape(geometry)
    if crs_src.is_geographic:
        # Ensure lon/lat in WGS84 for centroid decision
        if crs_src.to_epsg() != 4326:
            transformer = Transformer.from_crs(crs_src, CRS.from_epsg(4326), always_xy=True)
            geom_wgs84 = shp_transform(transformer.transform, geom)
        else:
            geom_wgs84 = geom
        lon, lat = geom_wgs84.centroid.x, geom_wgs84.centroid.y
        dst = choose_metric_crs_for_galicia(lon)
        return reproject_geojson(mapping(geom), src_crs, dst), dst
    # Else assume already metric
    return geometry, src_crs
