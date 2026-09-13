import os
import pytest

def pytest_sessionstart(session):
    # Fijar proveedor antes de la recolección de tests/imports
    os.environ['PLAN_PROVIDER'] = 'mock'
    os.environ.pop('PLAN_CSV_PATH', None)

@pytest.fixture(scope="session", autouse=True)
def _force_mock_plan_provider():
    # Asegurar que se mantiene durante la sesión
    os.environ['PLAN_PROVIDER'] = 'mock'
    os.environ.pop('PLAN_CSV_PATH', None)
    yield
    # Restaurar (opcional)
    os.environ.pop('PLAN_PROVIDER', None)
    os.environ.pop('PLAN_CSV_PATH', None)

@pytest.fixture(autouse=True)
def _reset_plan_provider_cache():
    """Guardar y restaurar el estado del proveedor de planes entre tests.

    Tests como test_limiting_factor_plan cambian PLAN_PROVIDER a 'csv'
    via /admin/apply-plan-csv-text. Sin este reset, el estado contamina
    tests posteriores que esperan el proveedor mock.
    """
    # Guardar estado antes del test
    old_provider = os.environ.get('PLAN_PROVIDER')
    old_csv_path = os.environ.get('PLAN_CSV_PATH')
    yield
    # Después de cada test: restaurar env y limpiar cache
    if old_provider is not None:
        os.environ['PLAN_PROVIDER'] = old_provider
    else:
        os.environ.pop('PLAN_PROVIDER', None)
    if old_csv_path is not None:
        os.environ['PLAN_CSV_PATH'] = old_csv_path
    else:
        os.environ.pop('PLAN_CSV_PATH', None)
    try:
        from src.plans_service import _PLAN_PROVIDER_CACHE
        _PLAN_PROVIDER_CACHE.update({"provider": None, "kind": None})
    except Exception:
        pass
