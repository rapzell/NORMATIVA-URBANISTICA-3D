import argparse
import json
import re
from typing import Optional

ZONES = ["urbano_consolidado","urbano","urbanizable","nucleo","rustico"]

KEYWORDS = {
    "urbano_consolidado": [r"urbano\s+consolidado", r"condici[oó]n\s+de\s+solar"],
    "urbano": [r"suelo\s+urbano", r"trama\s+urbana", r"servicios\s+urban[ií]sticos"],
    "urbanizable": [r"suelo\s+urbanizable", r"sectores\s+de\s+planeamiento", r"programa(ci[oó]n)?\s+de\s+actuaciones"],
    "nucleo": [r"n[uú]cleo\s+rural", r"asentamiento\s+tradicional"],
    "rustico": [r"suelo\s+r[uú]stic", r"protecci[oó]n\s+ambiental", r"usos\s+agr[ií]colas|ganaderos|forestales"],
}

COMPILED = {k: [re.compile(pat, re.I) for pat in pats] for k, pats in KEYWORDS.items()}


def classify_zone(text: str) -> Optional[str]:
    txt = text or ""
    for zone in ["urbano_consolidado","urbano","urbanizable","nucleo","rustico"]:
        pats = COMPILED.get(zone, [])
        for pat in pats:
            if pat.search(txt):
                return zone
    return None


def main():
    ap = argparse.ArgumentParser(description="Clasificador de zona (reglas simples)")
    ap.add_argument("--text", help="Texto directo a clasificar")
    ap.add_argument("--file", help="Ruta a fichero de texto (opcional)")
    args = ap.parse_args()

    content = args.text
    if args.file and not content:
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()
    if not content:
        print(json.dumps({"zone": None}))
        return
    z = classify_zone(content)
    print(json.dumps({"zone": z}))


if __name__ == "__main__":
    main()
