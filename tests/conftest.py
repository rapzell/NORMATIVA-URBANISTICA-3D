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
