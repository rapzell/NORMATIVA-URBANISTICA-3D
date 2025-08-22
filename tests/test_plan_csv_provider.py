import os
from src.rules_engine import ZoneInput, analizar_zonificacion


def setup_module(module):
    # Forzar proveedor CSV con el sample
    os.environ['PLAN_PROVIDER'] = 'csv'
    os.environ['PLAN_CSV_PATH'] = 'datos/planes_municipales_sample.csv'


def teardown_module(module):
    # Restaurar a mock por defecto
    os.environ.pop('PLAN_PROVIDER', None)
    os.environ.pop('PLAN_CSV_PATH', None)


def test_csv_provider_vigo_default_row():
    inp = ZoneInput(zona="urbano", uso_previsto="residencial", municipio="Vigo")
    res = analizar_zonificacion(inp)
    assert res.altura_maxima_m == 16.0
    assert res.retranqueo_min_m == 3.0


def test_csv_provider_vigo_rz2():
    inp = ZoneInput(zona="urbano", uso_previsto="residencial", municipio="Vigo", subzona="RZ-2")
    res = analizar_zonificacion(inp)
    assert res.altura_maxima_m == 12.0
    assert res.retranqueo_min_m == 3.0
