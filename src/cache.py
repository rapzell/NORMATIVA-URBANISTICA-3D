"""Capa de caché unificada en disco + HTTP con reintentos.

Todas las llamadas a APIs externas (Catastro, SIOTUGA, Overpass, SIOSE,
Overture) deben pasar por aquí:

- ``disk_get(source, key, ttl_s)`` / ``disk_set(source, key, value)``
  guardan JSON en ``datos/cache/{source}/{key}.json`` con sello temporal.
- ``http_get(url, timeout, retries, backoff)`` hace GET con reintentos
  y backoff exponencial; SIOTUGA y Catastro fallan de forma intermitente.

Los nombres de ``source`` usados: ``osm_buildings``, ``siotuga``,
``catastro``, ``siose``, ``lidar``, ``overture``.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CACHE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos", "cache"
)

DEFAULT_TTL_S = 7 * 24 * 3600  # 7 días, mínimo recomendado por la guía de datos

USER_AGENT = "NormativaGalicia/1.0"


def _safe_key(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(key))[:180]


def disk_path(source: str, key: str) -> str:
    return os.path.join(CACHE_ROOT, _safe_key(source), _safe_key(key) + ".json")


def disk_get(source: str, key: str, ttl_s: int = DEFAULT_TTL_S) -> Any | None:
    """Lee un valor cacheado si existe y no ha expirado."""
    path = disk_path(source, key)
    try:
        if not os.path.exists(path):
            return None
        if ttl_s is not None and time.time() - os.path.getmtime(path) > ttl_s:
            return None
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("data")
    except Exception:
        return None


def disk_set(source: str, key: str, value: Any) -> None:
    """Escribe un valor en caché de forma atómica (tmp + rename)."""
    try:
        path = disk_path(source, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"_cached_at": time.time(), "data": value}, f,
                      ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        pass


def cached(source: str, key: str, ttl_s: int, producer: Callable[[], Any]) -> Any:
    """Devuelve el valor cacheado o lo produce, guardándolo."""
    data = disk_get(source, key, ttl_s)
    if data is not None:
        return data
    data = producer()
    if data is not None:
        disk_set(source, key, data)
    return data


def http_get(url: str, timeout: int = 15, retries: int = 2,
             backoff: float = 1.5, headers: dict | None = None) -> bytes:
    """GET con reintentos y backoff exponencial. Devuelve bytes crudos.

    Lanza la última excepción si todos los intentos fallan. Los códigos
    4xx no se reintentan (no son transitorios); 429 y 5xx sí.
    """
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=hdrs)
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except HTTPError as e:
            last_exc = e
            if 400 <= e.code < 500 and e.code != 429:
                raise
        except (URLError, TimeoutError, OSError) as e:
            last_exc = e
        if attempt < retries:
            time.sleep(backoff ** attempt)
    assert last_exc is not None
    raise last_exc
