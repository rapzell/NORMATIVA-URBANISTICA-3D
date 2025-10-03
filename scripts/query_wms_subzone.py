import sys
import json
import math
import urllib.parse
import urllib.request

API_BASE = "http://127.0.0.1:8000"


def build_bbox_from_point(x: float, y: float, buffer_m: float = 1.0, srs: str = "EPSG:3857"):
    # Small bbox around point for GetFeatureInfo
    return f"{x-buffer_m},{y-buffer_m},{x+buffer_m},{y+buffer_m}"


def lonlat_to_mercator(lon: float, lat: float):
    # WebMercator EPSG:3857
    # Source: spherical mercator projection
    r_major = 6378137.0
    x = r_major * math.radians(lon)
    # clamp latitude for numerical stability
    lat = max(min(lat, 89.9), -89.9)
    y = r_major * math.log(math.tan(math.pi/4.0 + math.radians(lat)/2.0))
    return x, y


def query_wms_info(base_url: str, layers: str, lon: float, lat: float, srs: str = "EPSG:4326", info_format: str = "application/json"):
    if srs.upper() == "EPSG:4326":
        x_merc, y_merc = lonlat_to_mercator(lon, lat)
        bbox = build_bbox_from_point(x_merc, y_merc, buffer_m=2.0, srs="EPSG:3857")
        params = {
            "base": base_url,
            "layers": layers,
            "bbox": bbox,
            "width": 256,
            "height": 256,
            "x": 128,
            "y": 128,
            "version": "1.1.1",
            "srs": "EPSG:3857",
            "info_format": info_format,
        }
    else:
        # Assume coords already in requested SRS; if not 3857, reuse given
        bbox = build_bbox_from_point(lon, lat, buffer_m=2.0, srs=srs)
        params = {
            "base": base_url,
            "layers": layers,
            "bbox": bbox,
            "width": 256,
            "height": 256,
            "x": 128,
            "y": 128,
            "version": "1.1.1",
            "srs": srs,
            "info_format": info_format,
        }
    url = f"{API_BASE}/proxy/wmsinfo?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent":"NormativaGalicia/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "application/json")
        if "json" in ctype:
            data = json.loads(raw.decode("utf-8", "ignore"))
        else:
            # fallback: return raw
            data = {"raw": raw.decode("utf-8", "ignore")}
    return data


def main():
    if len(sys.argv) < 5:
        print("usage: query_wms_subzone.py <WMS_BASE_URL> <LAYER_NAME> <lon> <lat> [SRS]")
        print("example PGOM13:")
        print("  python scripts/query_wms_subzone.py 'https://ide.coruna.gal/arcgis/services/pgom13/MapServer/WMSServer' 'pgom13:Ordenanzas' -8.411 43.361 EPSG:4326")
        sys.exit(2)
    base = sys.argv[1]
    layers = sys.argv[2]
    lon = float(sys.argv[3])
    lat = float(sys.argv[4])
    srs = sys.argv[5] if len(sys.argv) > 5 else "EPSG:4326"
    out = query_wms_info(base, layers, lon, lat, srs)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
