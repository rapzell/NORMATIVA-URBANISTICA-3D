import argparse
import csv
import os
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import re

# Columns expected by the CSV provider. Extra columns (e.g., source, notes) are allowed and ignored.
HEADERS = [
    "municipio",
    "subzona",
    "altura_maxima_m",
    "retranqueo_min_m",
    "setback_front_m",
    "setback_side_m",
    "setback_back_m",
    "front_direction_default",
    "ocupacion_max",
    "edificabilidad_max_m2_m2",
    # metadata (ignored by provider but useful for auditing)
    "source",
    "source_refs",
    "precedence",
    "notes",
]

# Seed entries based on the user's confirmed examples (manual extraction for now)
SEED_ROWS = [
    {
        "municipio": "Vigo",
        "subzona": "O3_grado_alto",
        "altura_maxima_m": 26,
        "retranqueo_min_m": 0,
        "setback_front_m": 0,
        "setback_side_m": 3,
        "setback_back_m": 3,
        "front_direction_default": "",
        "ocupacion_max": 0.80,
        "edificabilidad_max_m2_m2": 2.50,
        "source": "Normativa_Urbanistica-(Castelan) VIGO.pdf p.307-310 (Ordenanza 3)",
        "notes": "Frente alineado a calle; laterales y fondo 3m; grado alto",
    },
    {
        "municipio": "Vigo",
        "subzona": "O7_grado1",
        "altura_maxima_m": 15,
        "retranqueo_min_m": 0,
        "setback_front_m": "",
        "setback_side_m": 3,
        "setback_back_m": 3,
        "front_direction_default": "",
        "ocupacion_max": 0.50,
        "edificabilidad_max_m2_m2": 1.00,
        "source": "Normativa_Urbanistica-(Castelan) VIGO.pdf p.356-358 (Ordenanza 7)",
        "notes": "Grado 1º",
    },
    {
        "municipio": "Boiro",
        "subzona": "Residencial_general",
        "altura_maxima_m": 10,
        "retranqueo_min_m": 0,
        "setback_front_m": "",
        "setback_side_m": "",
        "setback_back_m": "",
        "front_direction_default": "",
        "ocupacion_max": 0.50,
        "edificabilidad_max_m2_m2": "",
        "source": "Texto PXOM Boiro.pdf cap. 10.2.5",
        "notes": "General residencial ~3 plantas",
    },
    {
        "municipio": "Boiro",
        "subzona": "Residencial_baja",
        "altura_maxima_m": 7,
        "retranqueo_min_m": 0,
        "setback_front_m": 5,
        "setback_side_m": 3,
        "setback_back_m": 2,
        "front_direction_default": "",
        "ocupacion_max": 0.50,
        "edificabilidad_max_m2_m2": 0.80,
        "source": "Texto PXOM Boiro.pdf p.119-120",
        "notes": "Baja densidad",
    },
]


def ensure_sources_exist(project_root: Path) -> None:
    """Warn if expected PDFs are missing in datos/."""
    expected = [
        project_root / "datos" / "Normativa_Urbanistica-(Castelan) VIGO.pdf",
        project_root / "datos" / "Texto PXOM Boiro.pdf",
    ]
    missing = [str(p) for p in expected if not p.exists()]
    if missing:
        print("[WARN] Archivos PDF no encontrados (continuo igualmente):")
        for m in missing:
            print(" -", m)


def try_read_pdf_info(pdf_path: Path) -> dict:
    """Try to read basic info from a PDF (pages, text length) using optional deps.
    Returns a dict with keys: exists(bool), pages(Optional[int]), text_len(Optional[int]), lib(str).
    """
    info = {"exists": pdf_path.exists(), "pages": None, "text_len": None, "lib": None}
    if not pdf_path.exists():
        return info
    # Try pdfplumber first
    try:
        import pdfplumber  # type: ignore
        info["lib"] = "pdfplumber"
        text_total = 0
        with pdfplumber.open(str(pdf_path)) as pdf:
            info["pages"] = len(pdf.pages)
            # sample first 5 pages to estimate text availability
            for i, page in enumerate(pdf.pages[:5]):
                t = page.extract_text() or ""
                text_total += len(t)
        info["text_len"] = text_total
        return info
    except Exception:
        pass
    # Fallback to PyPDF2
    try:
        import PyPDF2  # type: ignore
        info["lib"] = "PyPDF2"
        text_total = 0
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            info["pages"] = len(reader.pages)
            for i, page in enumerate(reader.pages[:5]):
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                text_total += len(t)
        info["text_len"] = text_total
        return info
    except Exception:
        pass
    info["lib"] = "none"
    return info


def write_csv(csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for row in SEED_ROWS:
            row_out = dict(row)
            # serialize list metadata
            if isinstance(row_out.get("source_refs"), list):
                row_out["source_refs"] = "; ".join(map(str, row_out["source_refs"]))
            writer.writerow(row_out)
    print(f"[OK] CSV escrito: {csv_path}")


def _normalize_number(s: str) -> Optional[float]:
    """Normalize number strings like '26 m', '2,5', '80%' to float in SI unit.
    - meters stay as is
    - percent becomes 0-1 fraction
    """
    if s is None:
        return None
    s2 = s.strip().lower().replace("\u00a0", " ")
    s2 = s2.replace(",", ".")
    try:
        if s2.endswith("%"):
            return float(re.sub(r"[^0-9.]+", "", s2)) / 100.0
        # strip units like m
        s2 = re.sub(r"[^0-9.]+", "", s2)
        return float(s2) if s2 != "" else None
    except Exception:
        return None


def _extract_text(pdf_path: Path, max_pages: int = 40) -> str:
    """Extract text from the first N pages using optional deps. Returns empty on failure."""
    if not pdf_path.exists():
        return ""
    # Try pdfplumber
    try:
        import pdfplumber  # type: ignore
        texts: List[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:max_pages]:
                texts.append(page.extract_text() or "")
        return "\n".join(texts)
    except Exception:
        pass
    # Fallback PyPDF2
    try:
        import PyPDF2  # type: ignore
        texts: List[str] = []
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages[:max_pages]:
                try:
                    texts.append(page.extract_text() or "")
                except Exception:
                    continue
        return "\n".join(texts)
    except Exception:
        return ""


def _extract_text_pages(pdf_path: Path, max_pages: int = 200) -> List[str]:
    """Return list of page texts (len<=max_pages). Empty list on failure."""
    if not pdf_path.exists():
        return []
    # Try pdfplumber
    try:
        import pdfplumber  # type: ignore
        texts: List[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages[:max_pages]:
                texts.append((page.extract_text() or ""))
        return texts
    except Exception:
        pass
    # Fallback PyPDF2
    try:
        import PyPDF2  # type: ignore
        texts: List[str] = []
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages[:max_pages]:
                try:
                    texts.append(page.extract_text() or "")
                except Exception:
                    texts.append("")
        return texts
    except Exception:
        return []


def parse_vigo(text: str, pages: Optional[List[str]] = None) -> List[Dict]:
    """Very rough regex-based extraction for Vigo O3/O7 sample values.
    Returns rows to override seeds if matches found.
    """
    rows: List[Dict] = []
    t = text.lower()
    # O3 (Ordenanza 3) patterns
    o3_pages: List[int] = []
    if pages:
        for i, ptxt in enumerate(pages, start=1):
            if re.search(r"ordenanza\s*3|\bo3\b|o\.\s*3", ptxt.lower()):
                o3_pages.append(i)
    if "ordenanza 3" in t or "o. 3" in t:
        # height ~26 m
        h = None
        m = re.search(r"altura\s*maxim[a\u00e1]\s*[:\-]?\s*(\d+[\.,]?\d*)\s*m", t)
        if m:
            h = _normalize_number(m.group(1))
        # occupancy ~80%
        occ = None
        m2 = re.search(r"ocupaci[\u00f3o]n\s*max\w*\s*[:\-]?\s*(\d+[\.,]?\d*)\s*%", t)
        if m2:
            occ = _normalize_number(m2.group(1) + "%")
        # side/back ~3 m
        sb = ss = None
        m3 = re.search(r"(laterales?|lado\s*lateral)[^\n]{0,40}?(\d+[\.,]?\d*)\s*m", t)
        if m3:
            ss = _normalize_number(m3.group(2))
        m4 = re.search(r"(fondo|posterior)[^\n]{0,40}?(\d+[\.,]?\d*)\s*m", t)
        if m4:
            sb = _normalize_number(m4.group(2))
        row = {
            "municipio": "Vigo",
            "subzona": "O3_grado_alto",
            "altura_maxima_m": h if h else 26,
            "retranqueo_min_m": 0,
            "setback_front_m": 0,
            "setback_side_m": ss if ss else 3,
            "setback_back_m": sb if sb else 3,
            "front_direction_default": "",
            "ocupacion_max": occ if occ is not None else 0.80,
            "edificabilidad_max_m2_m2": 2.50,
            "source": "VIGO Tomo III",
            "source_refs": [
                (f"p.{min(o3_pages)}-p.{max(o3_pages)}" if o3_pages else "p.xx")
            ],
            "precedence": "municipal_over_autonomic",
            "notes": "extraído regex (aprox)",
        }
        rows.append(row)
    # O7 (Ordenanza 7)
    o7_pages: List[int] = []
    if pages:
        for i, ptxt in enumerate(pages, start=1):
            if re.search(r"ordenanza\s*7|\bo7\b|o\.\s*7", ptxt.lower()):
                o7_pages.append(i)
    if "ordenanza 7" in t or re.search(r"\bo7\b", t):
        h = None
        m = re.search(r"ordenanza\s*7[\s\S]{0,300}?altura\s*maxim[a\u00e1]\s*[:\-]?\s*(\d+[\.,]?\d*)\s*m", t)
        if m:
            h = _normalize_number(m.group(1))
        occ = None
        m2 = re.search(r"ordenanza\s*7[\s\S]{0,400}?ocupaci[\u00f3o]n\s*max\w*\s*[:\-]?\s*(\d+[\.,]?\d*)\s*%", t)
        if m2:
            occ = _normalize_number(m2.group(1) + "%")
        row = {
            "municipio": "Vigo",
            "subzona": "O7_grado1",
            "altura_maxima_m": h if h else 15,
            "retranqueo_min_m": 0,
            "setback_front_m": "",
            "setback_side_m": 3,
            "setback_back_m": 3,
            "front_direction_default": "",
            "ocupacion_max": occ if occ is not None else 0.50,
            "edificabilidad_max_m2_m2": 1.00,
            "source": "VIGO Tomo III",
            "source_refs": [
                (f"p.{min(o7_pages)}-p.{max(o7_pages)}" if o7_pages else "p.xx")
            ],
            "precedence": "municipal_over_autonomic",
            "notes": "extraído regex (aprox)",
        }
        rows.append(row)
    return rows


def parse_boiro(text: str, pages: Optional[List[str]] = None) -> List[Dict]:
    rows: List[Dict] = []
    t = text.lower()
    any_pages: List[int] = []
    if pages:
        for i, ptxt in enumerate(pages, start=1):
            if re.search(r"residencial|ordenanza", ptxt.lower()):
                any_pages.append(i)
    # General residencial ~ 10 m / 50%
    if re.search(r"(general|residencial)[\s\S]{0,200}?altura[\s\S]{0,40}?(\d+[\.,]?\d*)\s*m", t):
        m = re.search(r"altura[\s\S]{0,40}?(\d+[\.,]?\d*)\s*m", t)
        h = _normalize_number(m.group(1)) if m else None
        rows.append({
            "municipio": "Boiro",
            "subzona": "Residencial_general",
            "altura_maxima_m": h if h else 10,
            "retranqueo_min_m": 0,
            "setback_front_m": "",
            "setback_side_m": "",
            "setback_back_m": "",
            "front_direction_default": "",
            "ocupacion_max": 0.50,
            "edificabilidad_max_m2_m2": "",
            "source": "PXOM Boiro",
            "source_refs": [
                (f"p.{min(any_pages)}-p.{max(any_pages)}" if any_pages else "p.xx")
            ],
            "precedence": "municipal_over_autonomic",
            "notes": "extraído regex (aprox)",
        })
    # Residencial baja: 7m, front 5, side 3, back 2, occ 50%, edi 0.8
    if re.search(r"(residencial\s*baja|ordenanza\s*3)", t):
        # front/side/back
        front = re.search(r"frente[^\n]{0,40}?(\d+[\.,]?\d*)\s*m", t)
        side = re.search(r"(lateral|lado\s*lateral)[^\n]{0,40}?(\d+[\.,]?\d*)\s*m", t)
        back = re.search(r"(fondo|posterior)[^\n]{0,40}?(\d+[\.,]?\d*)\s*m", t)
        rows.append({
            "municipio": "Boiro",
            "subzona": "Residencial_baja",
            "altura_maxima_m": 7,
            "retranqueo_min_m": 0,
            "setback_front_m": _normalize_number(front.group(1)) if front else 5,
            "setback_side_m": _normalize_number(side.group(2)) if side else 3,
            "setback_back_m": _normalize_number(back.group(2)) if back else 2,
            "front_direction_default": "",
            "ocupacion_max": 0.50,
            "edificabilidad_max_m2_m2": 0.80,
            "source": "PXOM Boiro",
            "source_refs": [
                (f"p.{min(any_pages)}-p.{max(any_pages)}" if any_pages else "p.xx")
            ],
            "precedence": "municipal_over_autonomic",
            "notes": "extraído regex (aprox)",
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Extrae (plantilla) reglas residenciales Vigo/Boiro a CSV")
    parser.add_argument(
        "--out",
        default=str(Path("datos") / "planes_vigo_boiro.csv"),
        help="Ruta de salida del CSV (por defecto: datos/planes_vigo_boiro.csv)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Intento best-effort de leer PDFs y reportar información básica (no sobreescribe semillas)",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Intentar extraer valores (regex heurística) y sobreescribir semillas donde haya coincidencias",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    ensure_sources_exist(project_root)

    if args.auto:
        vigo_pdf = project_root / "datos" / "Normativa_Urbanistica-(Castelan) VIGO.pdf"
        boiro_pdf = project_root / "datos" / "Texto PXOM Boiro.pdf"
        for label, p in (("Vigo", vigo_pdf), ("Boiro", boiro_pdf)):
            info = try_read_pdf_info(p)
            print(f"[INFO] {label} PDF: exists={info['exists']} lib={info['lib']} pages={info['pages']} text_sample_len={info['text_len']}")
        print("[INFO] Modo --auto aún no parsea valores: usa las semillas confirmadas. Próximas versiones añadirán extracción por ordenanza/capítulos con normalización de unidades.")
    if args.parse:
        vigo_pdf = project_root / "datos" / "Normativa_Urbanistica-(Castelan) VIGO.pdf"
        boiro_pdf = project_root / "datos" / "Texto PXOM Boiro.pdf"
        vigo_text = _extract_text(vigo_pdf)
        boiro_text = _extract_text(boiro_pdf)
        vigo_pages = _extract_text_pages(vigo_pdf)
        boiro_pages = _extract_text_pages(boiro_pdf)
        overrides: List[Dict] = []
        if vigo_text:
            overrides.extend(parse_vigo(vigo_text, vigo_pages))
        if boiro_text:
            overrides.extend(parse_boiro(boiro_text, boiro_pages))
        print(f"[INFO] Overrides extraídos: {len(overrides)}")
        # Merge: by (municipio, subzona)
        def key(r: Dict):
            return (r.get("municipio", "").lower().strip(), (r.get("subzona") or "").lower().strip())
        base = {key(r): r for r in SEED_ROWS}
        for o in overrides:
            base[key(o)] = o
        # Rewrite SEED_ROWS in-place for write_csv below
        SEED_ROWS[:] = list(base.values())

    csv_path = Path(args.out)
    write_csv(csv_path)

    print("\nSiguiente paso (PowerShell):")
    print("$env:PLAN_PROVIDER='csv'; $env:PLAN_CSV_PATH='" + str(csv_path) + "'")
    print("uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
