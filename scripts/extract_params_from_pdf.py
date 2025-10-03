import sys, json, re
from pathlib import Path

# Add project root to sys.path so `src` can be imported when running as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse extraction logic
try:
    from src.text_extractor import extract_from_text
except Exception as e:
    print(json.dumps({"error": f"cannot import extract_from_text: {e}"}))
    sys.exit(1)

def read_pdf_text(pdf_path: Path):
    try:
        import pdfplumber
    except Exception as e:
        return None, f"pdfplumber not available: {e}"
    if not pdf_path.exists():
        return None, f"file not found: {pdf_path}"
    texts = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    txt = page.extract_text() or ""
                except Exception:
                    txt = ""
                texts.append({"page": i, "text": txt})
    except Exception as e:
        return None, f"error reading pdf: {e}"
    return texts, None


def aggregate_params(texts):
    agg = {
        "altura_maxima_m": None,
        "retranqueo_min_m": None,
        "setback_front_m": None,
        "setback_side_m": None,
        "setback_back_m": None,
        "ocupacion_max": None,
        "edificabilidad_max_m2_m2": None,
    }
    hits = []
    for obj in texts:
        txt = obj.get("text") or ""
        if not txt:
            continue
        data = extract_from_text(txt)
        if data:
            hits.append({"page": obj.get("page"), **data})
        # altura: mantener máximo
        if "altura_maxima_m" in data and data["altura_maxima_m"] is not None:
            try:
                v = float(data["altura_maxima_m"])
                if agg["altura_maxima_m"] is None or v > float(agg["altura_maxima_m"]):
                    agg["altura_maxima_m"] = v
            except Exception:
                pass
        # retranqueo mínimo: conservar el primero si no está, o el menor (más restrictivo)
        if "retranqueo_min_m" in data and data["retranqueo_min_m"] is not None:
            try:
                v = float(data["retranqueo_min_m"])
                if agg["retranqueo_min_m"] is None or v < float(agg["retranqueo_min_m"]):
                    agg["retranqueo_min_m"] = v
            except Exception:
                pass
        # setbacks direccionales: conservar el mayor si hay varios
        for k in ("setback_front_m","setback_side_m","setback_back_m"):
            if k in data and data[k] is not None:
                try:
                    v = float(data[k])
                    if agg[k] is None or v > float(agg[k]):
                        agg[k] = v
                except Exception:
                    pass
        # ocupación: conservar el mayor
        if "ocupacion_max" in data and data["ocupacion_max"] is not None:
            try:
                v = float(data["ocupacion_max"])
                if agg["ocupacion_max"] is None or v > float(agg["ocupacion_max"]):
                    agg["ocupacion_max"] = v
            except Exception:
                pass
        # edificabilidad: conservar el mayor
        if "edificabilidad_max_m2_m2" in data and data["edificabilidad_max_m2_m2"] is not None:
            try:
                v = float(data["edificabilidad_max_m2_m2"])
                if agg["edificabilidad_max_m2_m2"] is None or v > float(agg["edificabilidad_max_m2_m2"]):
                    agg["edificabilidad_max_m2_m2"] = v
            except Exception:
                pass
    return agg, hits


def filter_pages(texts, contains: list[str] | None):
    if not contains:
        return texts
    out = []
    lowers = [c.lower() for c in contains if isinstance(c, str) and c]
    for obj in texts:
        txt = (obj.get("text") or "").lower()
        if any(k in txt for k in lowers):
            out.append(obj)
    return out


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: python extract_params_from_pdf.py <pdf_path> [municipio] [subzona] [filter1,filter2,...]"}))
        sys.exit(1)
    pdf = Path(sys.argv[1])
    municipio = sys.argv[2] if len(sys.argv) >= 3 else None
    subzona = sys.argv[3] if len(sys.argv) >= 4 else None
    texts, err = read_pdf_text(pdf)
    if err:
        print(json.dumps({"error": err}))
        sys.exit(2)
    # Optional filters via 4th arg as comma-separated substrings
    filters = None
    if len(sys.argv) >= 5 and sys.argv[4]:
        filters = [s.strip() for s in sys.argv[4].split(',') if s.strip()]
    if filters:
        texts = filter_pages(texts, filters)
    agg, hits = aggregate_params(texts)
    out = {
        "municipio": municipio,
        "subzona": subzona,
        "pdf": str(pdf),
        "params": agg,
        "filters": filters,
        "sample_hits": hits[:10],
    }
    print(json.dumps(out, ensure_ascii=False))

if __name__ == "__main__":
    main()
