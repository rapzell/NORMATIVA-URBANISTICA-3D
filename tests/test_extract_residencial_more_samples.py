from scripts.extract_residencial_from_text import extract_from_text

FRAG_U93 = (
    "Ordenanza U9.3. Grandes superficies comerciales y otros terciarios. "
    "1. Parámetros y condiciones de ordenación. ... La ocupación máxima sobre rasante viene fijada por las condiciones de retranqueo y posición de la edificación aquí señaladas. "
    "En cualquiera caso, se limita al 70% de la superficie de parcela. ... La edificabilidad máxima permitida será de 0.80 m2/m2 sobre parcela edificable. "
    "Se fija un retranqueo mínimo de la edificación de 5,00 m a la alineación y colindantes. ... De forma genérica se establece una altura máxima de 18,00 m."
)

FRAG_U94 = (
    "Ordenanza U9.4. Grandes superficies industriales. 1. Parámetros y condiciones de ordenación. ... "
    "La ocupación máxima sobre rasante se establece en el 90% de la superficie de parcela. ... "
    "La edificabilidad máxima permitida será de 2,00 m2/m2 sobre parcela edificable. ... "
    "se establece una altura máxima de 25,00 m."
)

def test_extract_u93_fragment():
    out = extract_from_text(FRAG_U93)
    assert out.get('subzona'), out
    assert abs(float(out.get('ocupacion_max', 0.0)) - 0.7) < 1e-6
    assert abs(float(out.get('edificabilidad_max_m2_m2', 0.0)) - 0.80) < 1e-6
    # altura podría no detectarse por coma decimal, pero esperamos 18.00
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 18.0) < 1e-6
    # retranqueo mínimo 5.00 m puede o no detectarse según patrón; no es obligatorio en este test


def test_extract_u94_fragment():
    out = extract_from_text(FRAG_U94)
    assert out.get('subzona'), out
    assert abs(float(out.get('ocupacion_max', 0.0)) - 0.9) < 1e-6
    # Asegura que no se captura el 100% (bajo rasante) como ocupación sobre rasante
    assert float(out.get('ocupacion_max', 0.0)) != 1.0
    assert abs(float(out.get('edificabilidad_max_m2_m2', 0.0)) - 2.00) < 1e-6
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 25.0) < 1e-6


# Casos residenciales adicionales (sintéticos) con redacciones variadas
FRAG_U63 = (
    "Ordenanza U6.3. Residencial extensiva. 1. Parámetros y condiciones. "
    "La edificabilidad máxima será de 0,60 m2/m2. Se fija una ocupación máxima del 40% de la parcela. "
    "Asimismo, se establece una altura autorizada de 7,00 m, medida hasta la cornisa."
)

FRAG_U64 = (
    "Ordenanza U6.4. Residencial. 1. Parámetros. "
    "Ocupación máxima del 70%. Edificabilidad máxima permitida de 1,00 m2/m2. "
    "Altura máxima de la edificación: 3,50 m."
)

FRAG_U7 = (
    "Ordenanza U7. Residencial. 1. Parámetros. "
    "Se establece una edificabilidad máxima de 0,15 m2/m2 y una ocupación máxima del 10% sobre parcela edificable. "
    "Altura máxima de la edificación 15 m."
)

FRAG_U10 = (
    "Ordenanza U10. Residencial intensiva. 1. Parámetros. "
    "La ocupación máxima se fija en el 25% y la edificabilidad máxima permitida será de 0,10 m2/m2. "
    "Altura hasta cubierta de 25 m."
)

FRAG_NR1 = (
    "Ordenanza NR1. Núcleo rural tradicional. 1. Parámetros. "
    "La ocupación máxima será del 30% de la superficie de parcela. Edificabilidad máxima: 0,50 m2/m2. "
    "Altura de cornisa máxima de 9,00 m."
)


def test_extract_u63_fragment():
    out = extract_from_text(FRAG_U63)
    assert out.get('subzona'), out
    assert abs(float(out.get('ocupacion_max', 0.0)) - 0.4) < 1e-6
    assert abs(float(out.get('edificabilidad_max_m2_m2', 0.0)) - 0.60) < 1e-6
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 7.0) < 1e-6


def test_extract_u64_fragment():
    out = extract_from_text(FRAG_U64)
    assert out.get('subzona'), out
    assert abs(float(out.get('ocupacion_max', 0.0)) - 0.7) < 1e-6
    assert abs(float(out.get('edificabilidad_max_m2_m2', 0.0)) - 1.00) < 1e-6
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 3.5) < 1e-6


def test_extract_u7_fragment():
    out = extract_from_text(FRAG_U7)
    assert out.get('subzona'), out
    assert abs(float(out.get('ocupacion_max', 0.0)) - 0.1) < 1e-6
    assert abs(float(out.get('edificabilidad_max_m2_m2', 0.0)) - 0.15) < 1e-6
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 15.0) < 1e-6


def test_extract_u10_fragment():
    out = extract_from_text(FRAG_U10)
    assert out.get('subzona'), out
    assert abs(float(out.get('ocupacion_max', 0.0)) - 0.25) < 1e-6
    assert abs(float(out.get('edificabilidad_max_m2_m2', 0.0)) - 0.10) < 1e-6
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 25.0) < 1e-6


def test_extract_nr1_fragment():
    out = extract_from_text(FRAG_NR1)
    assert out.get('subzona'), out
    assert abs(float(out.get('ocupacion_max', 0.0)) - 0.3) < 1e-6
    assert abs(float(out.get('edificabilidad_max_m2_m2', 0.0)) - 0.50) < 1e-6
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 9.0) < 1e-6


# Frases equivalentes por plantas típicas en Vigo
FRAG_EQ_U7 = (
    "Ordenanza U7. Residencial. 1. Parámetros. "
    "La altura de la edificación será de bajo y una planta equivalente a 7,00 metros."
)

FRAG_EQ_U10 = (
    "Ordenanza U10. Residencial intensiva. 1. Parámetros. "
    "La altura de la edificación será de bajo y dos plantas o 12 metros."
)


def test_extract_equivalente_por_plantas_u7():
    out = extract_from_text(FRAG_EQ_U7)
    assert out.get('subzona'), out
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 7.0) < 1e-6


def test_extract_equivalente_por_plantas_u10():
    out = extract_from_text(FRAG_EQ_U10)
    assert out.get('subzona'), out
    assert abs(float(out.get('altura_maxima_m', 0.0)) - 12.0) < 1e-6
