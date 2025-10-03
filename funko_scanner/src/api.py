import os
import webbrowser
from typing import Any, Dict, Optional

import requests


def lookup_upc(upc: str) -> Optional[Dict[str, Any]]:
    """
    Consulta la API de UPCitemdb (trial) o alternativas si están configuradas.

    Prioridad:
    1) UPCitemdb trial (sin API key, 100 req/día): https://api.upcitemdb.com/prod/trial/lookup?upc={upc}
    2) UPCDatabase (si estableces UPCDATABASE_API_KEY): https://api.upcdatabase.org/product/{upc}?apikey=KEY
    """
    upc = (upc or "").strip()
    if not upc:
        return None

    # Opción 1: UPCitemdb trial
    url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={upc}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data
        else:
            print(f"UPCitemdb respondió {r.status_code}. Intentando alternativas si existen...")
    except Exception as ex:
        print(f"Error consultando UPCitemdb: {ex}")

    # Opción 2: UPCDatabase con API key
    api_key = os.getenv("UPCDATABASE_API_KEY")
    if api_key:
        url2 = f"https://api.upcdatabase.org/product/{upc}?apikey={api_key}"
        try:
            r2 = requests.get(url2, timeout=15)
            if r2.status_code == 200:
                data2 = r2.json()
                # Normalizar de forma básica a la estructura de UPCitemdb
                if data2.get("success") is True:
                    title = data2.get("title") or data2.get("description") or "Producto"
                    brand = data2.get("brand") or ""
                    images = []
                    if data2.get("images"):
                        images = data2["images"]
                    normalized = {
                        "code": "OK",
                        "total": 1,
                        "items": [
                            {
                                "title": title,
                                "description": data2.get("description") or "",
                                "brand": brand,
                                "images": images,
                            }
                        ],
                    }
                    return normalized
                else:
                    print("UPCDatabase no encontró el producto o no tuvo éxito.")
            else:
                print(f"UPCDatabase respondió {r2.status_code}")
        except Exception as ex:
            print(f"Error consultando UPCDatabase: {ex}")

    return None


def pretty_print_item(item: Dict[str, Any]) -> None:
    print("\n=== Detalles del Producto ===")
    print(f"Nombre: {item.get('title') or 'N/D'}")
    print(f"Descripción: {item.get('description') or 'N/D'}")
    print(f"Marca: {item.get('brand') or 'N/D'}")
    images = item.get("images") or []
    if images:
        print(f"Imagen: {images[0]}")
    else:
        print("Imagen: No disponible")


def open_image_url(url: str) -> None:
    """Abre la URL de imagen en el navegador por defecto."""
    if not url:
        return
    webbrowser.open(url)
