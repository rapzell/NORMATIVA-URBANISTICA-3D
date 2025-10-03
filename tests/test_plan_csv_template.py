import os
import contextlib
from src.rules_engine import ZoneInput, analizar_zonificacion


def setup_module(module):
    os.environ['PLAN_PROVIDER'] = 'csv'
    os.environ['PLAN_CSV_PATH'] = 'documentacion/plan_municipal_residencial_template.csv'


def teardown_module(module):
    with contextlib.suppress(Exception):
        os.environ.pop('PLAN_PROVIDER')
    with contextlib.suppress(Exception):
        os.environ.pop('PLAN_CSV_PATH')


def test_csv_template_vigo_r1():
    inp = ZoneInput(zona="urbano", uso_previsto="residencial", municipio="Vigo", subzona="R-1")
    res = analizar_zonificacion(inp)
    assert float(res.altura_maxima_m) == 12.0
    assert float(res.retranqueo_min_m) == 3.0


def test_csv_template_vigo_r2():
    inp = ZoneInput(zona="urbano", uso_previsto="residencial", municipio="Vigo", subzona="R-2")
    res = analizar_zonificacion(inp)
    assert float(res.altura_maxima_m) == 16.0
    assert float(res.retranqueo_min_m) == 4.0


def test_csv_template_santiago_nr_trad():
    inp = ZoneInput(zona="nucleo", uso_previsto="residencial", municipio="Santiago", subzona="NR-TRAD")
    res = analizar_zonificacion(inp)
    assert float(res.altura_maxima_m) == 9.0
    assert float(res.retranqueo_min_m) == 3.0
