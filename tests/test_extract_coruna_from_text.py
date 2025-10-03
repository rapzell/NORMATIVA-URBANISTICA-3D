import re
from src.text_extractor import extract_from_text

def test_coruna_subzona_21_with_range_height_and_params():
    txt = (
        "Subzona 2.1: Calle semi-intensiva – Montealto, La Torre y Atocha.\n"
        "Ocupación máxima 30% en fondos edificables.\n"
        "Edificabilidad 1 m2/m2.\n"
        "La altura regulada por ábaco será 7–9 m según frente de calle.\n"
    )
    out = extract_from_text(txt)
    assert out.get('subzona') == '2.1'
    assert out.get('ocupacion_max') is not None and abs(float(out['ocupacion_max']) - 0.30) < 1e-6
    assert out.get('edificabilidad_max_m2_m2') is not None and abs(float(out['edificabilidad_max_m2_m2']) - 1.0) < 1e-6
    # Altura por rango: debe tomar el máximo (9)
    assert out.get('altura_maxima_m') is not None and abs(float(out['altura_maxima_m']) - 9.0) < 1e-6


def test_coruna_subzona_31_block_open_ignores_below_grade_occupancy():
    txt = (
        "Subzona 3.1: Bloque abierto con espacio libre de parcela.\n"
        "Se permite ocupación 100% bajo rasante para garajes.\n"
        "Edificabilidad máxima de 1 m²/m².\n"
    )
    out = extract_from_text(txt)
    assert out.get('subzona') == '3.1'
    # La heurística debe descartar 100% bajo rasante como ocupación máxima sobre rasante
    assert 'ocupacion_max' not in out or out.get('ocupacion_max') is None
    assert out.get('edificabilidad_max_m2_m2') is not None and abs(float(out['edificabilidad_max_m2_m2']) - 1.0) < 1e-6
