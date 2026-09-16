"""Servicio de subzonas espaciales para integracion GIS con GeoLibre.

Carga el dataset piloto de subzonas en GeoJSON y permite consultarlo
por municipio o devolverlo completo. Esto es la base de la Fase 2 del
roadmap de integracion con GeoLibre.
"""
from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_OVERPASS_CACHE: dict[tuple[str, int], dict[str, Any]] = {}
_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
_OVERPASS_DISK_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos", "cache", "osm_buildings"
)
_OVERPASS_DISK_TTL_S = 7 * 24 * 3600  # 7 días


def _overpass_disk_path(muni_key: str, limit: int) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in muni_key)
    return os.path.join(_OVERPASS_DISK_CACHE_DIR, f"{safe}_{int(limit)}.json")


def _overpass_disk_read(muni_key: str, limit: int) -> dict[str, Any] | None:
    path = _overpass_disk_path(muni_key, limit)
    try:
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > _OVERPASS_DISK_TTL_S:
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            return data
    except Exception:
        return None
    return None


def _overpass_disk_write(muni_key: str, limit: int, data: dict[str, Any]) -> None:
    try:
        os.makedirs(_OVERPASS_DISK_CACHE_DIR, exist_ok=True)
        path = _overpass_disk_path(muni_key, limit)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        pass

MUNICIPIO_CENTERS = {
    "vigo": {"center": [-8.722, 42.232], "delta": 0.02},
    "a coruna": {"center": [-8.400, 43.370], "delta": 0.02},
    "coruna": {"center": [-8.400, 43.370], "delta": 0.02},
    "santiago": {"center": [-8.540, 42.880], "delta": 0.02},
    "santiago de compostela": {"center": [-8.540, 42.880], "delta": 0.02},
    "pontevedra": {"center": [-8.644, 42.434], "delta": 0.015},
    "lugo": {"center": [-7.556, 43.009], "delta": 0.015},
    "ourense": {"center": [-7.864, 42.336], "delta": 0.015},
    "orense": {"center": [-7.864, 42.336], "delta": 0.015},
    "ferrol": {"center": [-8.234, 43.486], "delta": 0.015},
    "naron": {"center": [-8.190, 43.496], "delta": 0.015},
    "vilagarcia de arousa": {"center": [-8.766, 42.594], "delta": 0.012},
    "vilagarcia": {"center": [-8.766, 42.594], "delta": 0.012},
    "marin": {"center": [-8.697, 42.394], "delta": 0.012},
    "redondela": {"center": [-8.610, 42.283], "delta": 0.012},
    "porrino": {"center": [-8.634, 42.162], "delta": 0.012},
    "porriño": {"center": [-8.634, 42.162], "delta": 0.012},
    "tui": {"center": [-8.644, 42.048], "delta": 0.012},
    "tuy": {"center": [-8.644, 42.048], "delta": 0.012},
    "sanxenxo": {"center": [-8.806, 42.400], "delta": 0.012},
    "boiro": {"center": [-8.894, 42.645], "delta": 0.012},
    "carballo": {"center": [-8.693, 43.212], "delta": 0.012},
    "arteixo": {"center": [-8.507, 43.305], "delta": 0.012},
    "oleiros": {"center": [-8.325, 43.347], "delta": 0.012},
    "cambre": {"center": [-8.349, 43.294], "delta": 0.012},
    "culleredo": {"center": [-8.388, 43.288], "delta": 0.012},
    "ribeira": {"center": [-8.995, 42.556], "delta": 0.012},
    "monforte de lemos": {"center": [-7.514, 42.519], "delta": 0.012},
    "sarria": {"center": [-7.412, 42.777], "delta": 0.012},
    "vilalba": {"center": [-7.684, 43.296], "delta": 0.012},
    "baiona": {"center": [-8.850, 42.117], "delta": 0.012},
    "cangas": {"center": [-8.784, 42.265], "delta": 0.012},
    "cangas do morrazo": {"center": [-8.784, 42.265], "delta": 0.012},
    "caldas de reis": {"center": [-8.643, 42.604], "delta": 0.012},
    "a estrada": {"center": [-8.487, 42.689], "delta": 0.012},
    "verin": {"center": [-7.437, 41.940], "delta": 0.012},
    "verín": {"center": [-7.437, 41.940], "delta": 0.012},
    "o barco de valdeorras": {"center": [-6.991, 42.415], "delta": 0.012},
    "as pontes de garcia rodriguez": {"center": [-7.852, 43.453], "delta": 0.012},
    "as pontes": {"center": [-7.852, 43.453], "delta": 0.012},
    "ortigueira": {"center": [-7.851, 43.689], "delta": 0.012},
    "viveiro": {"center": [-7.596, 43.662], "delta": 0.012},
    "ribadeo": {"center": [-7.041, 43.537], "delta": 0.012},
    "burela": {"center": [-7.362, 43.659], "delta": 0.012},
    "foz": {"center": [-7.259, 43.569], "delta": 0.012},
    "a pobra do caraminal": {"center": [-8.938, 42.596], "delta": 0.012},
    "ria de arosa": {"center": [-8.750, 42.580], "delta": 0.015},
    "catoira": {"center": [-8.719, 42.667], "delta": 0.010},
    "valga": {"center": [-8.650, 42.704], "delta": 0.010},
    "a lama": {"center": [-8.426, 42.405], "delta": 0.010},
    "mos": {"center": [-8.633, 42.196], "delta": 0.010},
    "o grove": {"center": [-8.870, 42.496], "delta": 0.010},
    "oia": {"center": [-8.874, 42.001], "delta": 0.010},
    "soutomaior": {"center": [-8.601, 42.346], "delta": 0.010},
    "moaña": {"center": [-8.733, 42.282], "delta": 0.010},
    "donaire": {"center": [-8.414, 42.384], "delta": 0.010},
    "padrón": {"center": [-8.663, 42.739], "delta": 0.010},
    "noya": {"center": [-8.887, 42.784], "delta": 0.010},
    "noia": {"center": [-8.887, 42.784], "delta": 0.010},
    "muros": {"center": [-9.059, 42.776], "delta": 0.010},
    "fisterra": {"center": [-9.263, 42.908], "delta": 0.010},
    "finisterre": {"center": [-9.263, 42.908], "delta": 0.010},
    "cedeira": {"center": [-8.061, 43.659], "delta": 0.010},
    "carino": {"center": [-7.876, 43.729], "delta": 0.010},
    "o vicedo": {"center": [-7.665, 43.734], "delta": 0.010},
    "xove": {"center": [-7.513, 43.685], "delta": 0.010},
    "a pontenova": {"center": [-7.189, 43.336], "delta": 0.010},
    "burela": {"center": [-7.362, 43.659], "delta": 0.010},
    "guntin": {"center": [-7.645, 43.033], "delta": 0.010},
    "palas de rei": {"center": [-7.868, 42.873], "delta": 0.010},
    "melide": {"center": [-8.015, 42.914], "delta": 0.010},
    "arzua": {"center": [-8.157, 42.927], "delta": 0.010},
    "orzua": {"center": [-8.157, 42.927], "delta": 0.010},
    "boqueixon": {"center": [-8.376, 42.836], "delta": 0.010},
    "touro": {"center": [-8.286, 42.864], "delta": 0.010},
    "vedra": {"center": [-8.460, 42.779], "delta": 0.010},
    "teo": {"center": [-8.545, 42.759], "delta": 0.010},
    "ames": {"center": [-8.645, 42.857], "delta": 0.010},
    "santiago de compostela": {"center": [-8.540, 42.880], "delta": 0.02},
    "bertamirans": {"center": [-8.623, 42.863], "delta": 0.008},
    "o pino": {"center": [-8.356, 42.915], "delta": 0.010},
    "oropesa": {"center": [-8.383, 42.975], "delta": 0.010},
    "ordes": {"center": [-8.408, 43.076], "delta": 0.010},
    "mesia": {"center": [-8.250, 43.070], "delta": 0.010},
    "frades": {"center": [-8.283, 43.030], "delta": 0.010},
    "arzua": {"center": [-8.157, 42.927], "delta": 0.010},
    "touro": {"center": [-8.286, 42.864], "delta": 0.010},
    "vilasantar": {"center": [-8.107, 43.046], "delta": 0.010},
    "sobrado": {"center": [-8.047, 43.035], "delta": 0.010},
    "boimorto": {"center": [-8.131, 43.088], "delta": 0.010},
    "curtis": {"center": [-8.013, 43.115], "delta": 0.010},
    "guitiriz": {"center": [-7.895, 43.184], "delta": 0.010},
    "vilalba": {"center": [-7.684, 43.296], "delta": 0.012},
    "begonte": {"center": [-7.699, 43.169], "delta": 0.010},
    "cospeito": {"center": [-7.556, 43.235], "delta": 0.010},
    "castro de rei": {"center": [-7.505, 43.207], "delta": 0.010},
    "xermade": {"center": [-7.762, 43.324], "delta": 0.010},
    "muras": {"center": [-7.721, 43.436], "delta": 0.010},
    "a pontenova": {"center": [-7.189, 43.336], "delta": 0.010},
    "trabada": {"center": [-7.192, 43.458], "delta": 0.010},
    "foz": {"center": [-7.259, 43.569], "delta": 0.012},
    "barreiros": {"center": [-7.241, 43.534], "delta": 0.010},
    "lourenza": {"center": [-7.271, 43.478], "delta": 0.010},
    "mondonedo": {"center": [-7.363, 43.428], "delta": 0.010},
    "a pastoriza": {"center": [-7.303, 43.333], "delta": 0.010},
    "abadin": {"center": [-7.478, 43.334], "delta": 0.010},
    "alfoz": {"center": [-7.419, 43.530], "delta": 0.010},
    "valadouro": {"center": [-7.418, 43.507], "delta": 0.010},
    "o valadouro": {"center": [-7.418, 43.507], "delta": 0.010},
    "ourol": {"center": [-7.589, 43.535], "delta": 0.010},
    "xove": {"center": [-7.513, 43.685], "delta": 0.010},
    "viveiro": {"center": [-7.596, 43.662], "delta": 0.012},
    "o vicedo": {"center": [-7.665, 43.734], "delta": 0.010},
    "carino": {"center": [-7.876, 43.729], "delta": 0.010},
    "cedeira": {"center": [-8.061, 43.659], "delta": 0.010},
    "valdovino": {"center": [-8.160, 43.604], "delta": 0.010},
    "valdoviño": {"center": [-8.160, 43.604], "delta": 0.010},
    "moeche": {"center": [-8.001, 43.521], "delta": 0.010},
    "cerdido": {"center": [-8.005, 43.596], "delta": 0.010},
    "as somozas": {"center": [-8.029, 43.520], "delta": 0.010},
    "san sadurnino": {"center": [-8.069, 43.546], "delta": 0.010},
    "san saturnino": {"center": [-8.069, 43.546], "delta": 0.010},
    "a capela": {"center": [-8.075, 43.431], "delta": 0.010},
    "as pontes de garcia rodriguez": {"center": [-7.852, 43.453], "delta": 0.012},
    "monfero": {"center": [-8.063, 43.315], "delta": 0.010},
    "pontedeume": {"center": [-8.175, 43.399], "delta": 0.010},
    "cabanas": {"center": [-8.171, 43.446], "delta": 0.010},
    "ares": {"center": [-8.242, 43.414], "delta": 0.010},
    "mugardos": {"center": [-8.255, 43.464], "delta": 0.010},
    "ferrol": {"center": [-8.234, 43.486], "delta": 0.015},
    "naron": {"center": [-8.190, 43.496], "delta": 0.015},
    "fene": {"center": [-8.219, 43.460], "delta": 0.010},
    "neda": {"center": [-8.207, 43.501], "delta": 0.010},
    "culleredo": {"center": [-8.388, 43.288], "delta": 0.012},
    "cambre": {"center": [-8.349, 43.294], "delta": 0.012},
    "oleiros": {"center": [-8.325, 43.347], "delta": 0.012},
    "sada": {"center": [-8.257, 43.354], "delta": 0.010},
    "bergondo": {"center": [-8.231, 43.334], "delta": 0.010},
    "betanzos": {"center": [-8.218, 43.280], "delta": 0.012},
    "coiros": {"center": [-8.164, 43.247], "delta": 0.010},
    "paderne": {"center": [-8.177, 43.245], "delta": 0.010},
    "o porrino": {"center": [-8.634, 42.162], "delta": 0.012},
    "o porriño": {"center": [-8.634, 42.162], "delta": 0.012},
    "mos": {"center": [-8.633, 42.196], "delta": 0.010},
    "soutomaior": {"center": [-8.601, 42.346], "delta": 0.010},
    "vilaboa": {"center": [-8.643, 42.336], "delta": 0.010},
    "cuntis": {"center": [-8.567, 42.634], "delta": 0.010},
    "morana": {"center": [-8.585, 42.626], "delta": 0.010},
    "moraña": {"center": [-8.585, 42.626], "delta": 0.010},
    "caldas de reis": {"center": [-8.643, 42.604], "delta": 0.012},
    "portas": {"center": [-8.657, 42.653], "delta": 0.010},
    "pontecesures": {"center": [-8.660, 42.722], "delta": 0.010},
    "valga": {"center": [-8.650, 42.704], "delta": 0.010},
    "padrón": {"center": [-8.663, 42.739], "delta": 0.010},
    "dodro": {"center": [-8.720, 42.720], "delta": 0.010},
    "rois": {"center": [-8.685, 42.750], "delta": 0.010},
    "padron": {"center": [-8.663, 42.739], "delta": 0.010},
    "illa de arousa": {"center": [-8.868, 42.553], "delta": 0.010},
    "a illa de arousa": {"center": [-8.868, 42.553], "delta": 0.010},
    "cambados": {"center": [-8.815, 42.513], "delta": 0.010},
    "o grove": {"center": [-8.870, 42.496], "delta": 0.010},
    "meano": {"center": [-8.788, 42.463], "delta": 0.010},
    "meaño": {"center": [-8.788, 42.463], "delta": 0.010},
    "sanxenxo": {"center": [-8.806, 42.400], "delta": 0.012},
    "poio": {"center": [-8.711, 42.449], "delta": 0.010},
    "pontevedra": {"center": [-8.644, 42.434], "delta": 0.015},
    "campo lameiro": {"center": [-8.543, 42.542], "delta": 0.010},
    "barro": {"center": [-8.654, 42.525], "delta": 0.010},
    "vilaboa": {"center": [-8.643, 42.336], "delta": 0.010},
    "marin": {"center": [-8.697, 42.394], "delta": 0.012},
    "bueu": {"center": [-8.784, 42.324], "delta": 0.010},
    "cangas": {"center": [-8.784, 42.265], "delta": 0.012},
    "moaña": {"center": [-8.733, 42.282], "delta": 0.010},
    "redondela": {"center": [-8.610, 42.283], "delta": 0.012},
    "pazos de borben": {"center": [-8.570, 42.274], "delta": 0.010},
    "forcarei": {"center": [-8.347, 42.592], "delta": 0.010},
    "silleda": {"center": [-8.247, 42.696], "delta": 0.010},
    "lalin": {"center": [-8.112, 42.660], "delta": 0.010},
    "lalín": {"center": [-8.112, 42.660], "delta": 0.010},
    "a estrada": {"center": [-8.487, 42.689], "delta": 0.012},
    "cerceda": {"center": [-8.470, 42.710], "delta": 0.010},
    "oroso": {"center": [-8.454, 42.997], "delta": 0.010},
    "ordoño": {"center": [-8.454, 42.997], "delta": 0.010},
    "tordoia": {"center": [-8.550, 42.993], "delta": 0.010},
    "santiago": {"center": [-8.540, 42.880], "delta": 0.02},
    "santiago de compostela": {"center": [-8.540, 42.880], "delta": 0.02},
    "teo": {"center": [-8.545, 42.759], "delta": 0.010},
    "ames": {"center": [-8.645, 42.857], "delta": 0.010},
    "brion": {"center": [-8.677, 42.868], "delta": 0.010},
    "negreira": {"center": [-8.740, 42.911], "delta": 0.010},
    "a banha": {"center": [-8.836, 42.973], "delta": 0.010},
    "a baña": {"center": [-8.836, 42.973], "delta": 0.010},
    "santa comba": {"center": [-8.811, 43.032], "delta": 0.010},
    "mazaricos": {"center": [-8.994, 42.936], "delta": 0.010},
    "outes": {"center": [-8.899, 42.857], "delta": 0.010},
    "muros": {"center": [-9.059, 42.776], "delta": 0.010},
    "carnota": {"center": [-9.089, 42.823], "delta": 0.010},
    "fisterra": {"center": [-9.263, 42.908], "delta": 0.010},
    "cee": {"center": [-9.190, 42.953], "delta": 0.010},
    "corcubion": {"center": [-9.196, 42.944], "delta": 0.010},
    "dumbría": {"center": [-9.103, 43.008], "delta": 0.010},
    "muxia": {"center": [-9.153, 43.021], "delta": 0.010},
    "muxía": {"center": [-9.153, 43.021], "delta": 0.010},
    "vimianzo": {"center": [-9.024, 43.112], "delta": 0.010},
    "camariñas": {"center": [-9.187, 43.127], "delta": 0.010},
    "camarinas": {"center": [-9.187, 43.127], "delta": 0.010},
    "zara": {"center": [-9.231, 43.185], "delta": 0.010},
    "laxe": {"center": [-9.005, 43.231], "delta": 0.010},
    "cabana de bergantinos": {"center": [-8.988, 43.202], "delta": 0.010},
    "ponteceso": {"center": [-8.940, 43.245], "delta": 0.010},
    "corme": {"center": [-8.959, 43.264], "delta": 0.010},
    "caamano": {"center": [-8.979, 43.340], "delta": 0.010},
    "a laracha": {"center": [-8.584, 43.250], "delta": 0.010},
    "carballo": {"center": [-8.693, 43.212], "delta": 0.012},
    "malpica": {"center": [-8.812, 43.323], "delta": 0.010},
    "malpica de bergantiños": {"center": [-8.812, 43.323], "delta": 0.010},
    "corme": {"center": [-8.959, 43.264], "delta": 0.010},
    "puentedeume": {"center": [-8.175, 43.399], "delta": 0.010},
    "pontedeume": {"center": [-8.175, 43.399], "delta": 0.010},
    "mino": {"center": [-8.281, 43.349], "delta": 0.010},
    "miño": {"center": [-8.281, 43.349], "delta": 0.010},
    "vilarmaior": {"center": [-8.144, 43.354], "delta": 0.010},
    "irixoa": {"center": [-8.096, 43.319], "delta": 0.010},
    "monfero": {"center": [-8.063, 43.315], "delta": 0.010},
    "betanzos": {"center": [-8.218, 43.280], "delta": 0.012},
    "coiros": {"center": [-8.164, 43.247], "delta": 0.010},
    "paderne": {"center": [-8.177, 43.245], "delta": 0.010},
    "o porrino": {"center": [-8.634, 42.162], "delta": 0.012},
    "mos": {"center": [-8.633, 42.196], "delta": 0.010},
    "vilaboa": {"center": [-8.643, 42.336], "delta": 0.010},
    "soutomaior": {"center": [-8.601, 42.346], "delta": 0.010},
    "gondomar": {"center": [-8.767, 42.111], "delta": 0.010},
    "nigran": {"center": [-8.807, 42.136], "delta": 0.010},
    "nigrán": {"center": [-8.807, 42.136], "delta": 0.010},
    "baiona": {"center": [-8.850, 42.117], "delta": 0.012},
    "oia": {"center": [-8.874, 42.001], "delta": 0.010},
    "a guarda": {"center": [-8.875, 41.902], "delta": 0.010},
    "a guardia": {"center": [-8.875, 41.902], "delta": 0.010},
    "o rosario": {"center": [-8.823, 41.959], "delta": 0.010},
    "o rosal": {"center": [-8.823, 41.959], "delta": 0.010},
    "tomino": {"center": [-8.754, 41.987], "delta": 0.010},
    "tomiño": {"center": [-8.754, 41.987], "delta": 0.010},
    "tui": {"center": [-8.644, 42.048], "delta": 0.012},
    "tuy": {"center": [-8.644, 42.048], "delta": 0.012},
    "salvaterra": {"center": [-8.500, 42.079], "delta": 0.010},
    "salvaterra de miño": {"center": [-8.500, 42.079], "delta": 0.010},
    "as neves": {"center": [-8.415, 42.088], "delta": 0.010},
    "arbo": {"center": [-8.317, 42.111], "delta": 0.010},
    "crecente": {"center": [-8.223, 42.153], "delta": 0.010},
    "melon": {"center": [-8.220, 42.259], "delta": 0.010},
    "melón": {"center": [-8.220, 42.259], "delta": 0.010},
    "ribadavia": {"center": [-8.144, 42.288], "delta": 0.010},
    "cortegada": {"center": [-8.168, 42.209], "delta": 0.010},
    "cartelle": {"center": [-8.074, 42.251], "delta": 0.010},
    "armentera": {"center": [-8.189, 42.182], "delta": 0.010},
    "a armenteira": {"center": [-8.189, 42.182], "delta": 0.010},
    "meis": {"center": [-8.708, 42.506], "delta": 0.010},
    "ribadumia": {"center": [-8.759, 42.514], "delta": 0.010},
    "vilagarcia": {"center": [-8.766, 42.594], "delta": 0.012},
    "vilagarcia de arousa": {"center": [-8.766, 42.594], "delta": 0.012},
    "vilanova de arousa": {"center": [-8.823, 42.571], "delta": 0.010},
    "catoira": {"center": [-8.719, 42.667], "delta": 0.010},
    "ria de arosa": {"center": [-8.750, 42.580], "delta": 0.015},
    "o salnes": {"center": [-8.750, 42.580], "delta": 0.015},
    "o deza": {"center": [-8.400, 42.600], "delta": 0.015},
    "verin": {"center": [-7.437, 41.940], "delta": 0.012},
    "verín": {"center": [-7.437, 41.940], "delta": 0.012},
    "o barco de valdeorras": {"center": [-6.991, 42.415], "delta": 0.012},
    "a rua": {"center": [-7.110, 42.389], "delta": 0.010},
    "petin": {"center": [-7.126, 42.389], "delta": 0.010},
    "petín": {"center": [-7.126, 42.389], "delta": 0.010},
    "a veiga": {"center": [-7.027, 42.250], "delta": 0.010},
    "larouco": {"center": [-7.154, 42.352], "delta": 0.010},
    "vilardevos": {"center": [-7.367, 41.935], "delta": 0.010},
    "vilar de santos": {"center": [-7.247, 42.107], "delta": 0.010},
    "rairiz de veiga": {"center": [-7.162, 42.078], "delta": 0.010},
    "xunqueira de ambia": {"center": [-7.362, 42.083], "delta": 0.010},
    "xunqueira de espadanedo": {"center": [-7.701, 42.332], "delta": 0.010},
    "allariz": {"center": [-7.800, 42.190], "delta": 0.010},
    "celanova": {"center": [-8.015, 42.153], "delta": 0.010},
    "quinstantino": {"center": [-7.976, 42.141], "delta": 0.010},
    "quinta de leirado": {"center": [-7.976, 42.141], "delta": 0.010},
    "ramiras": {"center": [-7.977, 42.180], "delta": 0.010},
    "ramirás": {"center": [-7.977, 42.180], "delta": 0.010},
    "boboras": {"center": [-8.143, 42.435], "delta": 0.010},
    "boborás": {"center": [-8.143, 42.435], "delta": 0.010},
    "beariz": {"center": [-8.272, 42.468], "delta": 0.010},
    "o carballiño": {"center": [-8.077, 42.431], "delta": 0.012},
    "o carballino": {"center": [-8.077, 42.431], "delta": 0.012},
    "san amaro": {"center": [-8.072, 42.417], "delta": 0.010},
    "punxin": {"center": [-8.097, 42.394], "delta": 0.010},
    "punxín": {"center": [-8.097, 42.394], "delta": 0.010},
    "maside": {"center": [-8.023, 42.412], "delta": 0.010},
    "san cristovo de cea": {"center": [-7.992, 42.472], "delta": 0.010},
    "vilamarin": {"center": [-8.087, 42.465], "delta": 0.010},
    "vilamarín": {"center": [-8.087, 42.465], "delta": 0.010},
    "a merca": {"center": [-7.903, 42.196], "delta": 0.010},
    "montederramo": {"center": [-7.506, 42.279], "delta": 0.010},
    "larco": {"center": [-7.390, 42.407], "delta": 0.010},
    "o barco": {"center": [-6.991, 42.415], "delta": 0.012},
    "o barco de valdeorras": {"center": [-6.991, 42.415], "delta": 0.012},
    "rubia": {"center": [-6.946, 42.420], "delta": 0.010},
    "rubiá": {"center": [-6.946, 42.420], "delta": 0.010},
    "vilamartin": {"center": [-7.117, 42.361], "delta": 0.010},
    "vilamartín de valdeorras": {"center": [-7.117, 42.361], "delta": 0.010},
    "quintela": {"center": [-7.181, 42.303], "delta": 0.010},
    "entrimo": {"center": [-8.170, 41.943], "delta": 0.010},
    "lobios": {"center": [-8.107, 41.890], "delta": 0.010},
    "muinos": {"center": [-8.156, 41.917], "delta": 0.010},
    "muiños": {"center": [-8.156, 41.917], "delta": 0.010},
    "calvos de randin": {"center": [-8.087, 41.934], "delta": 0.010},
    "ximonde": {"center": [-8.014, 41.994], "delta": 0.010},
    "xinzo": {"center": [-7.757, 42.009], "delta": 0.010},
    "xinzo de limia": {"center": [-7.757, 42.009], "delta": 0.010},
    "sandianes": {"center": [-7.803, 42.024], "delta": 0.010},
    "sandiás": {"center": [-7.803, 42.024], "delta": 0.010},
    "trasmiras": {"center": [-7.648, 42.023], "delta": 0.010},
    "oira": {"center": [-7.465, 42.054], "delta": 0.010},
    "laza": {"center": [-7.456, 42.061], "delta": 0.010},
    "castrelo do val": {"center": [-7.383, 42.097], "delta": 0.010},
    "verin": {"center": [-7.437, 41.940], "delta": 0.012},
    "villarino de conso": {"center": [-7.310, 42.177], "delta": 0.010},
    "vilarino de conso": {"center": [-7.310, 42.177], "delta": 0.010},
    "o bolo": {"center": [-7.101, 42.306], "delta": 0.010},
    "manzaneda": {"center": [-7.227, 42.308], "delta": 0.010},
    "a pobra de trives": {"center": [-7.252, 42.340], "delta": 0.010},
    "a veiga": {"center": [-7.027, 42.250], "delta": 0.010},
    "o barco de valdeorras": {"center": [-6.991, 42.415], "delta": 0.012},
    "a rua": {"center": [-7.110, 42.389], "delta": 0.010},
    "petin": {"center": [-7.126, 42.389], "delta": 0.010},
    "petín": {"center": [-7.126, 42.389], "delta": 0.010},
    "larouco": {"center": [-7.154, 42.352], "delta": 0.010},
    "a veiga": {"center": [-7.027, 42.250], "delta": 0.010},
    "conzo": {"center": [-6.872, 42.417], "delta": 0.010},
    "carballeda": {"center": [-6.963, 42.449], "delta": 0.010},
    "carballeda de avia": {"center": [-8.164, 42.324], "delta": 0.010},
    "pontevedra": {"center": [-8.644, 42.434], "delta": 0.015},
    "marin": {"center": [-8.697, 42.394], "delta": 0.012},
    "marín": {"center": [-8.697, 42.394], "delta": 0.012},
    "poio": {"center": [-8.711, 42.449], "delta": 0.010},
    "meano": {"center": [-8.788, 42.463], "delta": 0.010},
    "meaño": {"center": [-8.788, 42.463], "delta": 0.010},
    "sanxenxo": {"center": [-8.806, 42.400], "delta": 0.012},
    "o grove": {"center": [-8.870, 42.496], "delta": 0.010},
    "cambados": {"center": [-8.815, 42.513], "delta": 0.010},
    "illa de arousa": {"center": [-8.868, 42.553], "delta": 0.010},
    "a illa de arousa": {"center": [-8.868, 42.553], "delta": 0.010},
    "vilanova de arousa": {"center": [-8.823, 42.571], "delta": 0.010},
    "vilagarcia": {"center": [-8.766, 42.594], "delta": 0.012},
    "vilagarcia de arousa": {"center": [-8.766, 42.594], "delta": 0.012},
    "catoira": {"center": [-8.719, 42.667], "delta": 0.010},
    "valga": {"center": [-8.650, 42.704], "delta": 0.010},
    "pontecesures": {"center": [-8.660, 42.722], "delta": 0.010},
    "padron": {"center": [-8.663, 42.739], "delta": 0.010},
    "padrón": {"center": [-8.663, 42.739], "delta": 0.010},
    "rois": {"center": [-8.685, 42.750], "delta": 0.010},
    "dodro": {"center": [-8.720, 42.720], "delta": 0.010},
    "boqueixon": {"center": [-8.376, 42.836], "delta": 0.010},
    "touro": {"center": [-8.286, 42.864], "delta": 0.010},
    "vedra": {"center": [-8.460, 42.779], "delta": 0.010},
    "a estrada": {"center": [-8.487, 42.689], "delta": 0.012},
    "cerceda": {"center": [-8.470, 42.710], "delta": 0.010},
    "campo lameiro": {"center": [-8.543, 42.542], "delta": 0.010},
    "barro": {"center": [-8.654, 42.525], "delta": 0.010},
    "cuntis": {"center": [-8.567, 42.634], "delta": 0.010},
    "morana": {"center": [-8.585, 42.626], "delta": 0.010},
    "moraña": {"center": [-8.585, 42.626], "delta": 0.010},
    "caldas de reis": {"center": [-8.643, 42.604], "delta": 0.012},
    "portas": {"center": [-8.657, 42.653], "delta": 0.010},
    "vilaboa": {"center": [-8.643, 42.336], "delta": 0.010},
    "soutomaior": {"center": [-8.601, 42.346], "delta": 0.010},
    "pazos de borben": {"center": [-8.570, 42.274], "delta": 0.010},
    "forcarei": {"center": [-8.347, 42.592], "delta": 0.010},
    "silleda": {"center": [-8.247, 42.696], "delta": 0.010},
    "lalin": {"center": [-8.112, 42.660], "delta": 0.010},
    "lalín": {"center": [-8.112, 42.660], "delta": 0.010},
    "agullada": {"center": [-8.169, 42.488], "delta": 0.010},
    "a agullada": {"center": [-8.169, 42.488], "delta": 0.010},
    "rodeiro": {"center": [-8.541, 42.640], "delta": 0.010},
    "vila de cruces": {"center": [-8.190, 42.838], "delta": 0.010},
    "silleda": {"center": [-8.247, 42.696], "delta": 0.010},
    "a estrada": {"center": [-8.487, 42.689], "delta": 0.012},
    "lalín": {"center": [-8.112, 42.660], "delta": 0.010},
    "monterroso": {"center": [-7.834, 42.791], "delta": 0.010},
    "palas de rei": {"center": [-7.868, 42.873], "delta": 0.010},
    "melide": {"center": [-8.015, 42.914], "delta": 0.010},
    "arzua": {"center": [-8.157, 42.927], "delta": 0.010},
    "orzua": {"center": [-8.157, 42.927], "delta": 0.010},
    "santiso": {"center": [-8.045, 42.877], "delta": 0.010},
    "toques": {"center": [-7.956, 42.884], "delta": 0.010},
    "sobrado": {"center": [-8.047, 43.035], "delta": 0.010},
    "vilasantar": {"center": [-8.107, 43.046], "delta": 0.010},
    "boimorto": {"center": [-8.131, 43.088], "delta": 0.010},
    "curtis": {"center": [-8.013, 43.115], "delta": 0.010},
    "mesia": {"center": [-8.250, 43.070], "delta": 0.010},
    "mesía": {"center": [-8.250, 43.070], "delta": 0.010},
    "frades": {"center": [-8.283, 43.030], "delta": 0.010},
    "oropesa": {"center": [-8.383, 42.975], "delta": 0.010},
    "ordes": {"center": [-8.408, 43.076], "delta": 0.010},
    "ordoño": {"center": [-8.454, 42.997], "delta": 0.010},
    "oroso": {"center": [-8.454, 42.997], "delta": 0.010},
    "tordoia": {"center": [-8.550, 42.993], "delta": 0.010},
    "santiago": {"center": [-8.540, 42.880], "delta": 0.02},
    "santiago de compostela": {"center": [-8.540, 42.880], "delta": 0.02},
    "teo": {"center": [-8.545, 42.759], "delta": 0.010},
    "ames": {"center": [-8.645, 42.857], "delta": 0.010},
    "brion": {"center": [-8.677, 42.868], "delta": 0.010},
    "negreira": {"center": [-8.740, 42.911], "delta": 0.010},
    "a baña": {"center": [-8.836, 42.973], "delta": 0.010},
    "santa comba": {"center": [-8.811, 43.032], "delta": 0.010},
    "mazaricos": {"center": [-8.994, 42.936], "delta": 0.010},
    "outes": {"center": [-8.899, 42.857], "delta": 0.010},
    "muros": {"center": [-9.059, 42.776], "delta": 0.010},
    "carnota": {"center": [-9.089, 42.823], "delta": 0.010},
    "fisterra": {"center": [-9.263, 42.908], "delta": 0.010},
    "finisterre": {"center": [-9.263, 42.908], "delta": 0.010},
    "cee": {"center": [-9.190, 42.953], "delta": 0.010},
    "corcubion": {"center": [-9.196, 42.944], "delta": 0.010},
    "corcubión": {"center": [-9.196, 42.944], "delta": 0.010},
    "dumbría": {"center": [-9.103, 43.008], "delta": 0.010},
    "muxia": {"center": [-9.153, 43.021], "delta": 0.010},
    "muxía": {"center": [-9.153, 43.021], "delta": 0.010},
    "vimianzo": {"center": [-9.024, 43.112], "delta": 0.010},
    "camariñas": {"center": [-9.187, 43.127], "delta": 0.010},
    "camarinas": {"center": [-9.187, 43.127], "delta": 0.010},
    "zara": {"center": [-9.231, 43.185], "delta": 0.010},
    "laxe": {"center": [-9.005, 43.231], "delta": 0.010},
    "cabana de bergantinos": {"center": [-8.988, 43.202], "delta": 0.010},
    "cabana de bergantiños": {"center": [-8.988, 43.202], "delta": 0.010},
    "ponteceso": {"center": [-8.940, 43.245], "delta": 0.010},
    "corme": {"center": [-8.959, 43.264], "delta": 0.010},
    "caamano": {"center": [-8.979, 43.340], "delta": 0.010},
    "caamaño": {"center": [-8.979, 43.340], "delta": 0.010},
    "a laracha": {"center": [-8.584, 43.250], "delta": 0.010},
    "carballo": {"center": [-8.693, 43.212], "delta": 0.012},
    "malpica": {"center": [-8.812, 43.323], "delta": 0.010},
    "malpica de bergantinos": {"center": [-8.812, 43.323], "delta": 0.010},
    "malpica de bergantiños": {"center": [-8.812, 43.323], "delta": 0.010},
    "coristanco": {"center": [-8.741, 43.189], "delta": 0.010},
    "a laracha": {"center": [-8.584, 43.250], "delta": 0.010},
    "arteixo": {"center": [-8.507, 43.305], "delta": 0.012},
    "laracha": {"center": [-8.584, 43.250], "delta": 0.010},
    "a laracha": {"center": [-8.584, 43.250], "delta": 0.010},
    "carral": {"center": [-8.355, 43.230], "delta": 0.010},
    "culleredo": {"center": [-8.388, 43.288], "delta": 0.012},
    "cambre": {"center": [-8.349, 43.294], "delta": 0.012},
    "oleiros": {"center": [-8.325, 43.347], "delta": 0.012},
    "sada": {"center": [-8.257, 43.354], "delta": 0.010},
    "bergondo": {"center": [-8.231, 43.334], "delta": 0.010},
    "betanzos": {"center": [-8.218, 43.280], "delta": 0.012},
    "coiros": {"center": [-8.164, 43.247], "delta": 0.010},
    "coirós": {"center": [-8.164, 43.247], "delta": 0.010},
    "paderne": {"center": [-8.177, 43.245], "delta": 0.010},
    "mino": {"center": [-8.281, 43.349], "delta": 0.010},
    "miño": {"center": [-8.281, 43.349], "delta": 0.010},
    "vilarmaior": {"center": [-8.144, 43.354], "delta": 0.010},
    "irixoa": {"center": [-8.096, 43.319], "delta": 0.010},
    "monfero": {"center": [-8.063, 43.315], "delta": 0.010},
    "pontedeume": {"center": [-8.175, 43.399], "delta": 0.010},
    "cabanas": {"center": [-8.171, 43.446], "delta": 0.010},
    "cabanas de bergantiños": {"center": [-8.171, 43.446], "delta": 0.010},
    "ares": {"center": [-8.242, 43.414], "delta": 0.010},
    "mugardos": {"center": [-8.255, 43.464], "delta": 0.010},
    "ferrol": {"center": [-8.234, 43.486], "delta": 0.015},
    "naron": {"center": [-8.190, 43.496], "delta": 0.015},
    "narón": {"center": [-8.190, 43.496], "delta": 0.015},
    "fene": {"center": [-8.219, 43.460], "delta": 0.010},
    "neda": {"center": [-8.207, 43.501], "delta": 0.010},
    "san sadurnino": {"center": [-8.069, 43.546], "delta": 0.010},
    "san saturnino": {"center": [-8.069, 43.546], "delta": 0.010},
    "a capela": {"center": [-8.075, 43.431], "delta": 0.010},
    "moeche": {"center": [-8.001, 43.521], "delta": 0.010},
    "cerdido": {"center": [-8.005, 43.596], "delta": 0.010},
    "as somozas": {"center": [-8.029, 43.520], "delta": 0.010},
    "valdovino": {"center": [-8.160, 43.604], "delta": 0.010},
    "valdoviño": {"center": [-8.160, 43.604], "delta": 0.010},
    "cedeira": {"center": [-8.061, 43.659], "delta": 0.010},
    "carino": {"center": [-7.876, 43.729], "delta": 0.010},
    "ortigueira": {"center": [-7.851, 43.689], "delta": 0.012},
    "mañón": {"center": [-7.697, 43.775], "delta": 0.010},
    "manon": {"center": [-7.697, 43.775], "delta": 0.010},
    "o vicedo": {"center": [-7.665, 43.734], "delta": 0.010},
    "viveiro": {"center": [-7.596, 43.662], "delta": 0.012},
    "xove": {"center": [-7.513, 43.685], "delta": 0.010},
    "ourol": {"center": [-7.589, 43.535], "delta": 0.010},
    "muras": {"center": [-7.721, 43.436], "delta": 0.010},
    "xermade": {"center": [-7.762, 43.324], "delta": 0.010},
    "vilalba": {"center": [-7.684, 43.296], "delta": 0.012},
    "guntin": {"center": [-7.645, 43.033], "delta": 0.010},
    "guntín": {"center": [-7.645, 43.033], "delta": 0.010},
    "lugo": {"center": [-7.556, 43.009], "delta": 0.015},
    "castro de rei": {"center": [-7.505, 43.207], "delta": 0.010},
    "cospeito": {"center": [-7.556, 43.235], "delta": 0.010},
    "begonte": {"center": [-7.699, 43.169], "delta": 0.010},
    "gutiriz": {"center": [-7.895, 43.184], "delta": 0.010},
    "guitiriz": {"center": [-7.895, 43.184], "delta": 0.010},
    "mondonedo": {"center": [-7.363, 43.428], "delta": 0.010},
    "mondoñedo": {"center": [-7.363, 43.428], "delta": 0.010},
    "a pastoriza": {"center": [-7.303, 43.333], "delta": 0.010},
    "abadin": {"center": [-7.478, 43.334], "delta": 0.010},
    "abadín": {"center": [-7.478, 43.334], "delta": 0.010},
    "alfoz": {"center": [-7.419, 43.530], "delta": 0.010},
    "valadouro": {"center": [-7.418, 43.507], "delta": 0.010},
    "o valadouro": {"center": [-7.418, 43.507], "delta": 0.010},
    "trabada": {"center": [-7.192, 43.458], "delta": 0.010},
    "a pontenova": {"center": [-7.189, 43.336], "delta": 0.010},
    "barreiros": {"center": [-7.241, 43.534], "delta": 0.010},
    "lourenza": {"center": [-7.271, 43.478], "delta": 0.010},
    "lourenzá": {"center": [-7.271, 43.478], "delta": 0.010},
    "foz": {"center": [-7.259, 43.569], "delta": 0.012},
    "burela": {"center": [-7.362, 43.659], "delta": 0.012},
    "ribadeo": {"center": [-7.041, 43.537], "delta": 0.012},
    "vega de valcarce": {"center": [-7.043, 43.219], "delta": 0.010},
    "a vega de valcarce": {"center": [-7.043, 43.219], "delta": 0.010},
    "castropol": {"center": [-7.031, 43.527], "delta": 0.010},
    "vega de espinareda": {"center": [-6.959, 42.724], "delta": 0.010},
    "a vega de espinareda": {"center": [-6.959, 42.724], "delta": 0.010},
    "fabero": {"center": [-6.681, 42.794], "delta": 0.010},
    "berlanga del bierzo": {"center": [-6.801, 42.725], "delta": 0.010},
    "torre del bierzo": {"center": [-6.831, 42.666], "delta": 0.010},
    "molinaseca": {"center": [-6.520, 42.538], "delta": 0.010},
    "ponferrada": {"center": [-6.596, 42.550], "delta": 0.012},
    "sarria": {"center": [-7.412, 42.777], "delta": 0.012},
    "paradela": {"center": [-7.567, 42.749], "delta": 0.010},
    "portomarin": {"center": [-7.612, 42.807], "delta": 0.010},
    "portomarín": {"center": [-7.612, 42.807], "delta": 0.010},
    "o saviñao": {"center": [-7.654, 42.652], "delta": 0.010},
    "o savinao": {"center": [-7.654, 42.652], "delta": 0.010},
    "chantada": {"center": [-7.769, 42.608], "delta": 0.010},
    "taboada": {"center": [-7.819, 42.715], "delta": 0.010},
    "antigua": {"center": [-7.842, 42.675], "delta": 0.010},
    "antigua de o carballiño": {"center": [-7.842, 42.675], "delta": 0.010},
    "lleiro": {"center": [-7.868, 42.712], "delta": 0.010},
    "pons": {"center": [-7.876, 42.676], "delta": 0.010},
    "o pons": {"center": [-7.876, 42.676], "delta": 0.010},
    "samos": {"center": [-7.324, 42.731], "delta": 0.010},
    "o incio": {"center": [-7.312, 42.647], "delta": 0.010},
    "lancara": {"center": [-7.327, 42.862], "delta": 0.010},
    "láncara": {"center": [-7.327, 42.862], "delta": 0.010},
    "boveda": {"center": [-7.482, 42.610], "delta": 0.010},
    "bóveda": {"center": [-7.482, 42.610], "delta": 0.010},
    "baralla": {"center": [-7.254, 42.893], "delta": 0.010},
    "a fonsagrada": {"center": [-7.069, 43.135], "delta": 0.010},
    "baleira": {"center": [-7.236, 43.001], "delta": 0.010},
    "negueira de muniz": {"center": [-6.894, 43.126], "delta": 0.010},
    "negueira de muñiz": {"center": [-6.894, 43.126], "delta": 0.010},
    "as nogais": {"center": [-7.110, 42.807], "delta": 0.010},
    "navia de suarna": {"center": [-7.002, 42.968], "delta": 0.010},
    "cervantes": {"center": [-6.937, 42.863], "delta": 0.010},
    "folgoso do courel": {"center": [-7.188, 42.589], "delta": 0.010},
    "o courel": {"center": [-7.188, 42.589], "delta": 0.010},
    "quiroga": {"center": [-7.272, 42.478], "delta": 0.010},
    "sober": {"center": [-7.586, 42.462], "delta": 0.010},
    "monforte de lemos": {"center": [-7.514, 42.519], "delta": 0.012},
    "pantón": {"center": [-7.597, 42.540], "delta": 0.010},
    "panton": {"center": [-7.597, 42.540], "delta": 0.010},
    "a pobra do brollon": {"center": [-7.390, 42.557], "delta": 0.010},
    "a pobra do brollón": {"center": [-7.390, 42.557], "delta": 0.010},
    "sarria": {"center": [-7.412, 42.777], "delta": 0.012},
    "paradela": {"center": [-7.567, 42.749], "delta": 0.010},
    "portomarin": {"center": [-7.612, 42.807], "delta": 0.010},
    "portomarín": {"center": [-7.612, 42.807], "delta": 0.010},
    "o saviñao": {"center": [-7.654, 42.652], "delta": 0.010},
    "o savinao": {"center": [-7.654, 42.652], "delta": 0.010},
    "chantada": {"center": [-7.769, 42.608], "delta": 0.010},
    "taboada": {"center": [-7.819, 42.715], "delta": 0.010},
    "antigua": {"center": [-7.842, 42.675], "delta": 0.010},
    "lleiro": {"center": [-7.868, 42.712], "delta": 0.010},
    "pons": {"center": [-7.876, 42.676], "delta": 0.010},
    "o pons": {"center": [-7.876, 42.676], "delta": 0.010},
    "samos": {"center": [-7.324, 42.731], "delta": 0.010},
    "o incio": {"center": [-7.312, 42.647], "delta": 0.010},
    "lancara": {"center": [-7.327, 42.862], "delta": 0.010},
    "láncara": {"center": [-7.327, 42.862], "delta": 0.010},
    "boveda": {"center": [-7.482, 42.610], "delta": 0.010},
    "bóveda": {"center": [-7.482, 42.610], "delta": 0.010},
    "baralla": {"center": [-7.254, 42.893], "delta": 0.010},
    "a fonsagrada": {"center": [-7.069, 43.135], "delta": 0.010},
    "baleira": {"center": [-7.236, 43.001], "delta": 0.010},
    "negueira de muniz": {"center": [-6.894, 43.126], "delta": 0.010},
    "as nogais": {"center": [-7.110, 42.807], "delta": 0.010},
    "navia de suarna": {"center": [-7.002, 42.968], "delta": 0.010},
    "cervantes": {"center": [-6.937, 42.863], "delta": 0.010},
    "folgoso do courel": {"center": [-7.188, 42.589], "delta": 0.010},
    "quiroga": {"center": [-7.272, 42.478], "delta": 0.010},
    "sober": {"center": [-7.586, 42.462], "delta": 0.010},
    "monforte de lemos": {"center": [-7.514, 42.519], "delta": 0.012},
    "pantón": {"center": [-7.597, 42.540], "delta": 0.010},
    "panton": {"center": [-7.597, 42.540], "delta": 0.010},
    "a pobra do brollon": {"center": [-7.390, 42.557], "delta": 0.010},
    "a pobra do brollón": {"center": [-7.390, 42.557], "delta": 0.010},
}

# Ruta del dataset piloto
_DATOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")
_SUBZONAS_PATH = os.path.join(_DATOS_DIR, "subzonas_piloto.geojson")


@lru_cache(maxsize=1)
def _load_subzones_raw() -> dict[str, Any]:
    """Carga y cachea el GeoJSON de subzonas piloto."""
    if not os.path.exists(_SUBZONAS_PATH):
        return {"type": "FeatureCollection", "features": []}
    with open(_SUBZONAS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_subzones(municipio: str | None = None) -> dict[str, Any]:
    """Devuelve el GeoJSON de subzonas, opcionalmente filtrado por municipio.

    Args:
        municipio: si se proporciona, filtra features cuyo municipio coincide
                   (case-insensitive, sin acentos en la comparacion).

    Returns:
        GeoJSON FeatureCollection con las subzonas que coincidan.
    """
    data = _load_subzones_raw()
    if not municipio:
        return data

    target = _normalize(municipio)
    filtered = [
        feat for feat in data.get("features", [])
        if _normalize(feat.get("properties", {}).get("municipio", "")) == target
    ]
    return {"type": "FeatureCollection", "features": filtered}


def list_municipios_with_subzones() -> list[str]:
    """Devuelve la lista de municipios que tienen subzonas espaciales."""
    data = _load_subzones_raw()
    seen: list[str] = []
    for feat in data.get("features", []):
        m = feat.get("properties", {}).get("municipio")
        if m and m not in seen:
            seen.append(m)
    return seen


def find_subzone_for_point(lon: float, lat: float) -> dict[str, Any] | None:
    """Busca la subzona que contiene el punto (lon, lat) en EPSG:4326.

    Usa shapely si esta disponible; si no, hace un bounding-box match simple.
    Devuelve las propiedades de la subzona o None.
    """
    data = _load_subzones_raw()
    try:
        from shapely.geometry import Point, shape
        pt = Point(lon, lat)
        for feat in data.get("features", []):
            geom = feat.get("geometry")
            if geom and shape(geom).contains(pt):
                return feat.get("properties")
    except Exception:
        # Fallback: bounding-box simple
        for feat in data.get("features", []):
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [[]])
            if not coords or not coords[0]:
                continue
            ring = coords[0]
            xs = [c[0] for c in ring]
            ys = [c[1] for c in ring]
            if min(xs) <= lon <= max(xs) and min(ys) <= lat <= max(ys):
                return feat.get("properties")
    return None


def find_subzone_by_name(municipio: str, subzona: str) -> dict[str, Any] | None:
    """Busca una subzona por municipio y nombre de subzona."""
    data = _load_subzones_raw()
    muni_norm = _normalize(municipio)
    sz_norm = _normalize(subzona)
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        if _normalize(props.get("municipio") or "") == muni_norm and _normalize(props.get("subzona") or "") == sz_norm:
            return props
    return None


def get_osm_buildings_geojson(municipio: str | None = None, *, limit: int = 800) -> dict[str, Any]:
    """Devuelve edificios OSM en GeoJSON listos para extrusión 3D.

    Usa Overpass desde backend para evitar CORS del navegador.
    Si no hay municipio o no existe centro conocido, devuelve FeatureCollection vacía.
    """
    muni_key = _normalize(municipio or "")
    cfg = MUNICIPIO_CENTERS.get(muni_key)
    if not cfg:
        return {"type": "FeatureCollection", "features": []}

    cache_key = (muni_key, int(limit))
    cached = _OVERPASS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    disk_cached = _overpass_disk_read(muni_key, int(limit))
    if disk_cached is not None:
        _OVERPASS_CACHE[cache_key] = disk_cached
        return disk_cached

    lon, lat = cfg["center"]
    delta = float(cfg.get("delta") or 0.01)
    raw = None
    last_error = None
    for factor in (0.15, 0.22):
        qd = delta * factor
        south, west, north, east = lat - qd, lon - qd, lat + qd, lon + qd
        query = (
            "[out:json][timeout:25];"
            f"way['building']({south},{west},{north},{east});"
            "out geom;"
        )

        def _fetch_overpass(overpass_url: str):
            req = Request(
                overpass_url,
                data=urlencode({"data": query}).encode("utf-8"),
                headers={"User-Agent": "NormativaGalicia/1.0", "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))

        from concurrent.futures import ThreadPoolExecutor, as_completed
        pool = ThreadPoolExecutor(max_workers=len(_OVERPASS_URLS))
        futures = [pool.submit(_fetch_overpass, url) for url in _OVERPASS_URLS]
        try:
            for future in as_completed(futures):
                try:
                    raw = future.result()
                    break
                except (HTTPError, URLError, TimeoutError, ValueError) as e:
                    last_error = e
        finally:
            for future in futures:
                future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
        if raw is not None:
            break
    if raw is None:
        raise last_error or RuntimeError("No se pudieron cargar edificios OSM")

    features: list[dict[str, Any]] = []
    for el in (raw.get("elements") or []):
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 4:
            continue
        coords = [[float(p["lon"]), float(p["lat"])] for p in geom if "lon" in p and "lat" in p]
        if len(coords) < 4:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        tags = el.get("tags") or {}
        height_info = _building_height_details(tags)
        height = round(float(height_info["height"]), 2)
        subzone_props = _find_subzone_for_ring(coords, municipio)
        compliance = _classify_building_compliance(height, subzone_props)
        features.append({
            "type": "Feature",
            "properties": {
                "osm_id": el.get("id"),
                "name": tags.get("name") or "",
                "building": tags.get("building") or "yes",
                "height": height,
                "height_source": height_info["source"],
                "height_estimated": height_info["estimated"],
                "levels": tags.get("building:levels") or None,
                "_altura_visual": round(float(height), 2),
                "municipio": (subzone_props or {}).get("municipio") or municipio,
                "subzona": (subzone_props or {}).get("subzona"),
                "altura_maxima_subzona_m": (subzone_props or {}).get("altura_maxima_m"),
                "normative_status": (subzone_props or {}).get("normative_status"),
                "normative_source": (subzone_props or {}).get("fuente"),
                "cumplimiento_altura": compliance["status"],
                "cumplimiento_detalle": compliance["detail"],
                "color_semantica": compliance["color_semantics"],
            },
            "geometry": {"type": "Polygon", "coordinates": [coords]},
        })
        if len(features) >= max(1, int(limit)):
            break
    result = {"type": "FeatureCollection", "features": features}
    _OVERPASS_CACHE[cache_key] = result
    _overpass_disk_write(muni_key, int(limit), result)
    return result


def _find_subzone_for_ring(coords: list[list[float]], municipio: str | None) -> dict[str, Any] | None:
    try:
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        lon = (min(xs) + max(xs)) / 2.0
        lat = (min(ys) + max(ys)) / 2.0
        return find_subzone_for_point(float(lon), float(lat))
    except Exception:
        return None


def _classify_building_compliance(height: float, subzone_props: dict[str, Any] | None) -> dict[str, str]:
    limit = None if not subzone_props else subzone_props.get("altura_maxima_m")
    if limit is None:
        return {
            "status": "sin_dato",
            "detail": "Sin subzona asociada o sin altura máxima conocida",
            "color_semantics": "gris = sin dato normativo",
        }
    try:
        limit_f = float(limit)
        h = float(height)
    except Exception:
        return {
            "status": "sin_dato",
            "detail": "No se pudo comparar la altura del edificio con el límite disponible",
            "color_semantics": "gris = sin dato normativo",
        }
    is_pilot = str((subzone_props or {}).get("normative_status") or "").lower() == "pilot"
    if h <= limit_f:
        margin = round(limit_f - h, 2)
        if is_pilot:
            return {
                "status": "orientativo_dentro",
                "detail": f"Comparación orientativa: {h} m <= {limit_f} m (margen {margin} m). La subzona y su límite son piloto, no acreditan cumplimiento urbanístico.",
                "color_semantics": "amarillo = comparación con datos piloto",
            }
        return {
            "status": "compatible",
            "detail": f"Altura dentro del máximo de subzona ({h} m <= {limit_f} m, margen {margin} m)",
            "color_semantics": "verde = compatible con la altura máxima",
        }
    excess = round(h - limit_f, 2)
    if is_pilot:
        return {
            "status": "orientativo_supera",
            "detail": f"Comparación orientativa: {h} m > {limit_f} m (exceso {excess} m). La subzona y su límite son piloto, no acreditan incumplimiento urbanístico.",
            "color_semantics": "naranja = posible exceso según datos piloto",
        }
    return {
        "status": "supera_altura",
        "detail": f"Altura por encima del máximo de subzona ({h} m > {limit_f} m, exceso {excess} m)",
        "color_semantics": "rojo = supera la altura máxima",
    }


def _building_height_details(tags: dict[str, Any]) -> dict[str, Any]:
    raw_h = tags.get("height")
    if isinstance(raw_h, str):
        try:
            return {"height": max(2.5, float(raw_h.lower().replace("m", "").strip())), "source": "osm_height", "estimated": False}
        except Exception:
            pass
    raw_levels = tags.get("building:levels")
    if isinstance(raw_levels, str):
        try:
            return {"height": max(3.0, float(raw_levels.strip()) * 3.2), "source": "osm_levels", "estimated": True}
        except Exception:
            pass
    btype = str(tags.get("building") or "").strip().lower()
    if btype in {"apartments", "office", "hospital", "hotel"}:
        return {"height": 18.0, "source": "building_type", "estimated": True}
    if btype in {"commercial", "retail", "school", "church"}:
        return {"height": 12.0, "source": "building_type", "estimated": True}
    if btype in {"industrial", "warehouse"}:
        return {"height": 8.0, "source": "building_type", "estimated": True}
    return {"height": 9.0, "source": "default", "estimated": True}


def _estimate_building_height(tags: dict[str, Any]) -> float:
    return float(_building_height_details(tags)["height"])


def _normalize(s: str) -> str:
    """Normaliza un string para comparacion: minusculas, sin acentos."""
    out = s.strip().lower()
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "ñ": "n", "ü": "u",
    }
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out
