from src.rules_engine import ZoneInput, analizar_zonificacion


def test_plan_params_vigo_default():
    inp = ZoneInput(zona="urbano", uso_previsto="residencial", municipio="Vigo")
    res = analizar_zonificacion(inp)
    # Debería aplicar parámetros de mock VIGO por defecto
    assert res.altura_maxima_m == 15.0
    assert res.retranqueo_min_m == 3.0
    assert any("Parámetros municipales (Vigo" in obs for obs in res.observaciones)


def test_plan_params_vigo_rz2():
    inp = ZoneInput(zona="urbano", uso_previsto="residencial", municipio="Vigo", subzona="RZ-2")
    res = analizar_zonificacion(inp)
    assert res.altura_maxima_m == 12.0
    assert res.retranqueo_min_m == 3.0
    assert any("RZ-2" in obs for obs in res.observaciones)


def test_plan_params_coruna():
    inp = ZoneInput(zona="urbano", uso_previsto="residencial", municipio="A Coruña")
    res = analizar_zonificacion(inp)
    assert res.altura_maxima_m == 13.5
    assert res.retranqueo_min_m == 3.0
    assert any("A Coruña" in obs or "A Coru" in obs for obs in res.observaciones)
