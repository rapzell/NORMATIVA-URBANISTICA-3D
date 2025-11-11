#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Benchmark de Overpass: mide latencia p50 por mirror en varias ubicaciones.
Uso:
  python scripts/overpass_benchmark.py --runs 5 --timeout 20 --out resultados/overpass_benchmark.csv

Sin dependencias externas (usa urllib). Genera CSV con columnas:
city,mirror,ok,count,failures,p50_ms,p90_ms,avg_ms
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from statistics import median
from pathlib import Path

MIRRORS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass-api.nextzen.org/api/interpreter',
]

# BBOX por ciudad (lat, lon, buffer grados aprox.)
CITIES = {
    'Vigo': (42.2406, -8.7207, 0.01),
    'A Coruna': (43.3623, -8.4115, 0.01),
    'Santiago': (42.8804, -8.5456, 0.01),
    'Ourense': (42.3358, -7.8639, 0.01),
    'Lugo': (43.0099, -7.5560, 0.01),
}

# Consulta mínima: edificios dentro de BBOX (nodes/ways/relations con building)
QUERY_TPL = (
    '[out:json][timeout:25];'
    '('
    'node["building"]({s},{w},{n},{e});'
    'way["building"]({s},{w},{n},{e});'
    'relation["building"]({s},{w},{n},{e});'
    ');'
    'out body qt 50;'
)


def do_request(url: str, query: str, timeout: int) -> tuple[bool, float, int]:
    data = urllib.parse.urlencode({'data': query}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'NG3D/bench'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        dt = (time.time() - t0) * 1000.0
        try:
            obj = json.loads(raw.decode('utf-8', 'ignore')) if raw else {}
            feats = len(obj.get('elements') or [])
        except Exception:
            feats = -1
        return True, dt, feats
    except Exception:
        return False, (time.time() - t0) * 1000.0, -1


def bench_city(city: str, lat: float, lon: float, buf: float, runs: int, timeout: int):
    s, n = lat - buf, lat + buf
    w, e = lon - buf, lon + buf
    q = QUERY_TPL.format(s=s, w=w, n=n, e=e)
    results = []
    for mirror in MIRRORS:
        times = []
        failures = 0
        for _ in range(runs):
            ok, ms, _feats = do_request(mirror, q, timeout)
            if ok:
                times.append(ms)
            else:
                failures += 1
            # Pausa corta para no martillear
            time.sleep(0.5)
        times_sorted = sorted(times)
        p50 = int(median(times_sorted)) if times_sorted else -1
        p90 = int(times_sorted[int(0.9*len(times_sorted))-1]) if len(times_sorted) >= 1 else -1
        avg = int(sum(times_sorted)/len(times_sorted)) if times_sorted else -1
        results.append({
            'city': city,
            'mirror': mirror,
            'ok': len(times) > 0,
            'count': len(times),
            'failures': failures,
            'p50_ms': p50,
            'p90_ms': p90,
            'avg_ms': avg,
        })
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runs', type=int, default=5)
    ap.add_argument('--timeout', type=int, default=25)
    ap.add_argument('--out', type=str, default='resultados/overpass_benchmark.csv')
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for name, (lat, lon, buf) in CITIES.items():
        for r in bench_city(name, lat, lon, buf, args.runs, args.timeout):
            rows.append(r)
            print(f"{r['city']}, {r['mirror']}, ok={r['ok']} n={r['count']} fail={r['failures']} p50={r['p50_ms']} p90={r['p90_ms']} avg={r['avg_ms']} ms")

    # Escribir CSV
    with out_path.open('w', encoding='utf-8') as f:
        f.write('city,mirror,ok,count,failures,p50_ms,p90_ms,avg_ms\n')
        for r in rows:
            f.write(
                f"{r['city']},{r['mirror']},{int(r['ok'])},{r['count']},{r['failures']},{r['p50_ms']},{r['p90_ms']},{r['avg_ms']}\n"
            )
    print(f"\nGuardado: {out_path}")


if __name__ == '__main__':
    main()
