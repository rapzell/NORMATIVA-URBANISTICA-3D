#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Smoke local cases for the API at http://127.0.0.1:<port>
- Tests /zoning/analyze
- Tests /zoning/assess
- Tests /zoning/assess-report (POST)
- Tests /zoning/volume-export (GLB)

No external dependencies (urllib only). Prints a concise summary and exits with non‑zero code on failure.
"""
from __future__ import annotations
import json
import sys
import time
import urllib.request as ur
import urllib.error as ue
from typing import Dict, Any, Tuple

BASE = f"http://127.0.0.1:{int(sys.argv[1]) if len(sys.argv) > 1 else 8002}"

# Simple polygons (lon/lat) ~ Vigo and A Coruña viewports
CASES = [
    {
        "name": "Vigo_basic",
        "municipio": "Vigo",
        "geom": {
            "type": "Polygon",
            "coordinates": [[
                [-8.7308, 42.2250],
                [-8.7188, 42.2250],
                [-8.7188, 42.23137],
                [-8.7308, 42.23137],
                [-8.7308, 42.2250]
            ]]
        },
        "altura": 12,
        "retranqueo": 3,
    },
    {
        "name": "Coruna_basic",
        "municipio": "A Coruña",
        "geom": {
            "type": "Polygon",
            "coordinates": [[
                [-8.4200, 43.3600],
                [-8.4100, 43.3600],
                [-8.4100, 43.3650],
                [-8.4200, 43.3650],
                [-8.4200, 43.3600]
            ]]
        },
        "altura": 13.5,
        "retranqueo": 3,
    },
]


def _post_json(path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(body).encode("utf-8")
    req = ur.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with ur.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            status = resp.status
            obj = json.loads(raw.decode("utf-8", "ignore")) if raw else {}
            return status, obj
    except ue.HTTPError as e:
        try:
            raw = e.read()
            msg = raw.decode("utf-8", "ignore")
        except Exception:
            msg = str(e)
        return e.code, {"error": msg}
    except Exception as e:
        return 0, {"error": str(e)}


def _post_any(path: str, body: Dict[str, Any]) -> Tuple[int, str]:
    data = json.dumps(body).encode("utf-8")
    req = ur.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with ur.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, raw.decode("utf-8", "ignore") if raw else ""
    except ue.HTTPError as e:
        try:
            raw = e.read()
            msg = raw.decode("utf-8", "ignore")
        except Exception:
            msg = str(e)
        return e.code, msg
    except Exception as e:
        return 0, str(e)


def run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    name = case["name"]
    municipio = case["municipio"]
    geom = case["geom"]
    altura = case["altura"]
    retranqueo = case["retranqueo"]
    summary: Dict[str, Any] = {"case": name}

    # 1) analyze
    st, res = _post_json("/zoning/analyze", {
        "zona": "urbano_consolidado",
        "uso_previsto": "residencial",
        "municipio": municipio,
        "geometry": geom,
    })
    summary["analyze_status"] = st
    summary["analyze_ok"] = (st == 200)

    # 2) assess
    st, assess = _post_json("/zoning/assess", {
        "geometry": geom,
        "altura_maxima_m": altura,
        "retranqueo_min_m": retranqueo,
        "municipio": municipio,
    })
    summary["assess_status"] = st
    summary["assess_viability"] = assess.get("viability") if isinstance(assess, dict) else None
    summary["assess_ok"] = (st == 200 and summary["assess_viability"] in {"apto", "condicionado", "no_apto"})

    # 3) assess-report (POST -> HTML)
    st, rep_text = _post_any("/zoning/assess-report", {
        "body": {
            "geometry": geom,
            "altura_maxima_m": altura,
            "retranqueo_min_m": retranqueo,
            "municipio": municipio,
        },
        "title": f"Smoke {name}",
        "client": "AC8",
        "project": f"{municipio} QA Local",
        "signature": True,
    })
    # The POST returns HTML text; consider success if 200.
    summary["report_status"] = st
    summary["report_ok"] = (st == 200)

    # 4) volume-export (POST GLB) — we check status only
    st, _ = _post_json("/zoning/volume-export", {
        "format": "glb",
        "geometry": geom,
        "altura_maxima_m": altura,
        "retranqueo_min_m": retranqueo,
        "municipio": municipio,
    })
    summary["export_status"] = st
    summary["export_ok"] = (st == 200)

    return summary


def main() -> int:
    print(f"== Smoke local cases @ {BASE} ==")
    t0 = time.time()
    results = [run_case(c) for c in CASES]
    dt = time.time() - t0

    ok = all(r.get("analyze_ok") and r.get("assess_ok") and r.get("report_ok") and r.get("export_ok") for r in results)

    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    print(f"== Elapsed: {dt:.2f}s  overall_ok={ok} ==")

    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
