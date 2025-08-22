from src.rules_engine import ZoneInput, analizar_zonificacion


def test_rules_engine_urbanizable_residencial():
    inp = ZoneInput(zona="urbanizable", uso_previsto="residencial")
    res = analizar_zonificacion(inp)
    assert res.zona_normalizada == "urbanizable"
    assert res.apto_residencial is True
    assert any(r.codigo == 'ART27' for r in res.restricciones)


def test_rules_engine_rustico_infraestructuras():
    inp = ZoneInput(zona="rústico", uso_previsto="infraestructuras")
    res = analizar_zonificacion(inp)
    assert res.zona_normalizada == "rustico"
    assert any(r.codigo == 'ART31_32' for r in res.restricciones)


def test_rules_engine_nucleo_rural():
    inp = ZoneInput(zona="núcleo rural", uso_previsto="residencial")
    res = analizar_zonificacion(inp)
    assert res.zona_normalizada == "nucleo_rural"
    assert res.apto_residencial is True
    assert any(r.codigo == 'ART13' for r in res.restricciones)
