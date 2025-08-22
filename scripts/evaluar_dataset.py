import os
import json
import argparse
from pathlib import Path
import re
import unicodedata as _uni


# Ensure project root on sys.path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.asistente_normativa import cargar_recursos, buscar_fragmentos, generar_respuesta  # type: ignore

# Helpers expuestos a nivel de módulo para pruebas unitarias
def _norm(txt: str) -> str:
    if not txt:
        return ''
    try:
        t = _uni.normalize('NFKD', txt)
        t = ''.join(ch for ch in t if not _uni.combining(ch))
    except Exception:
        t = txt
    t = t.lower()
    # Mantener letras, dígitos y espacios
    t = re.sub(r"[^a-z0-9áéíóúñü\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _score(resp: str, gold: str) -> float:
    a = set(_norm(resp).split())
    b = set(_norm(gold).split())
    if not a or not b:
        return 0.0
    inter = len(a & b)
    recall = inter / max(1, len(b))
    return recall

def _prf(resp: str, gold: str):
    """Calcula precisión, recall y F1 sobre conjuntos de tokens normalizados."""
    a = set(_norm(resp).split())
    b = set(_norm(gold).split())
    if not a or not b:
        return 0.0, 0.0, 0.0
    inter = len(a & b)
    prec = inter / max(1, len(a))
    rec = inter / max(1, len(b))
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
    return prec, rec, f1

def _art_from(text: str):
    m = re.search(r"art[íi]culo\s*(\d+)", text or '', re.IGNORECASE)
    return int(m.group(1)) if m else None


def main():
    parser = argparse.ArgumentParser(description="Evaluar dataset Ley 2/2016")
    parser.add_argument("--dataset", default=str(ROOT / "datos" / "dataset_ley_2_2016.json"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--csv", default="", help="Ruta opcional para exportar resultados a CSV")
    parser.add_argument("--jsonl", default="", help="Ruta opcional para exportar resultados detallados en JSONL")
    args = parser.parse_args()

    if args.debug:
        os.environ["RETRIEVAL_DEBUG"] = "1"
    print("[Eval] Iniciando evaluación...")

    try:
        recursos = cargar_recursos()
    except Exception as e:
        import traceback
        print("[Eval] ERROR al cargar recursos:", e)
        traceback.print_exc()
        return 1
    if recursos is None:
        print("No se pudieron cargar recursos.")
        return 1
    chunks, index, bi_encoder, cross_encoder, llm = recursos

    try:
        with open(args.dataset, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        import traceback
        print("[Eval] ERROR al cargar dataset:", args.dataset, e)
        traceback.print_exc()
        return 1

    # helpers definidos a nivel de módulo

    total = 0
    passed = 0
    sum_prec = 0.0
    sum_rec = 0.0
    sum_f1 = 0.0
    per_art = {}
    rows = []
    rows_debug = []
    for item in data[: args.limit]:
        pregunta = item.get("pregunta")
        esperada = item.get("respuesta")
        if not pregunta:
            continue
        total += 1
        print("\n=== Caso #{} ===".format(total))
        print("Pregunta:", pregunta)
        try:
            frags = buscar_fragmentos(pregunta, chunks, index, bi_encoder, cross_encoder)
            resp = generar_respuesta(pregunta, frags, llm)
        except Exception as e:
            import traceback
            print("[Eval] ERROR en caso:", e)
            traceback.print_exc()
            continue
        print("Respuesta:", resp)
        if esperada:
            print("Esperada:", esperada)
            prec, rec, f1 = _prf(resp, esperada)
            sc = rec  # mantener 'score' como recall por compatibilidad
            ok = rec >= 0.5
            sum_prec += prec
            sum_rec += rec
            sum_f1 += f1
            print(f"[Eval] precision={prec:.2f} recall={rec:.2f} f1={f1:.2f} -> {'PASS' if ok else 'FAIL'}")
            if ok:
                passed += 1
            art = _art_from(esperada)
            if art is not None:
                per_art.setdefault(art, {"n": 0, "p": 0})
                per_art[art]["n"] += 1
                per_art[art]["p"] += int(ok)
            # Predicted article: first Ley fragment with artículo
            pred_art = None
            for ch in frags:
                md = (ch.get('metadata') or {})
                if (md.get('tipo_fuente','').lower()=='ley'):
                    mda = md.get('articulo') or ''
                    pa = _art_from(str(mda))
                    if pa is not None:
                        pred_art = pa
                        break
            rows.append({
                'idx': total,
                'pregunta': pregunta,
                'respuesta': resp,
                'esperada': esperada,
                'score': f"{sc:.4f}",
                'precision': f"{prec:.4f}",
                'recall': f"{rec:.4f}",
                'f1': f"{f1:.4f}",
                'pass': int(ok),
                'expected_art': art if art is not None else '',
                'predicted_art': pred_art if pred_art is not None else '',
            })
            # Collect debug info for JSONL
            try:
                retrieved = []
                for ch in frags:
                    md = (ch.get('metadata') or {})
                    retrieved.append({
                        'tipo_fuente': (md.get('tipo_fuente') or ''),
                        'articulo': (md.get('articulo') or ''),
                        'titulo': (md.get('titulo') or ''),
                    })
            except Exception:
                retrieved = []
            rows_debug.append({
                'idx': total,
                'pregunta': pregunta,
                'respuesta': resp,
                'esperada': esperada,
                'score': sc,
                'precision': prec,
                'recall': rec,
                'f1': f1,
                'pass': bool(ok),
                'expected_art': art,
                'predicted_art': pred_art,
                'retrieved': retrieved,
            })
    print("\nEvaluación completada: {} casos".format(total))
    if total:
        acc = passed / total
        print(f"[Eval] Accuracy global: {passed}/{total} ({acc:.1%})")
        if passed + (total - passed):
            # Macro-promedios (sobre casos con 'esperada')
            denom = max(1, total)
            print(f"[Eval] Macro-avg precision: {sum_prec/denom:.2f} | recall: {sum_rec/denom:.2f} | F1: {sum_f1/denom:.2f}")
    if per_art:
        print("[Eval] Desglose por artículo:")
        for art in sorted(per_art.keys()):
            n = per_art[art]["n"]
            p = per_art[art]["p"]
            print(f"  - Art. {art}: {p}/{n} ({(p/max(1,n)):.1%})")
    # CSV export
    if args.csv:
        try:
            import csv
            out_path = Path(args.csv)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['idx','pregunta','respuesta','esperada','score','precision','recall','f1','pass','expected_art','predicted_art'])
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)
            print(f"[Eval] CSV guardado en: {out_path}")
        except Exception as e:
            import traceback
            print("[Eval] ERROR al guardar CSV:", e)
            traceback.print_exc()

    # JSONL export
    if args.jsonl:
        try:
            out_path = Path(args.jsonl)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, 'w', encoding='utf-8') as f:
                for r in rows_debug:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"[Eval] JSONL guardado en: {out_path}")
        except Exception as e:
            import traceback
            print("[Eval] ERROR al guardar JSONL:", e)
            traceback.print_exc()


if __name__ == "__main__":
    raise SystemExit(main())
