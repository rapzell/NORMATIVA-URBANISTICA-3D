import types

from scripts.extract_rules_vigo_boiro import parse_vigo, parse_boiro


def test_parse_vigo_basic_text():
    # Minimal synthetic text containing Ordenanza markers and numbers
    text = (
        "Ordenanza 3. Altura máxima: 26 m. Ocupación máxima 80%. Laterales 3 m. Posterior 3 m.\n"
        "Ordenanza 7. Altura máxima: 15 m. Ocupación máxima 50%."
    )
    rows = parse_vigo(text, pages=[text])
    # Expect at least one row (O3) and probably O7
    assert any(r.get("subzona") == "O3_grado_alto" for r in rows)
    assert any(r.get("municipio") == "Vigo" for r in rows)
    # Check metadata presence
    for r in rows:
        assert r.get("source") is not None
        assert r.get("precedence") == "municipal_over_autonomic"
        assert isinstance(r.get("source_refs"), list)


def test_parse_boiro_basic_text():
    text = (
        "Residencial baja: frente 5 m, lateral 3 m, fondo 2 m. Altura 7 m. Ocupación 50%. Edificabilidad 0,8.\n"
        "Residencial general: Altura 10 m, Ocupación 50%."
    )
    rows = parse_boiro(text, pages=[text])
    assert any(r.get("subzona") == "Residencial_baja" for r in rows)
    assert any(r.get("municipio") == "Boiro" for r in rows)
    for r in rows:
        assert r.get("source") is not None
        assert r.get("precedence") == "municipal_over_autonomic"
        assert isinstance(r.get("source_refs"), list)
