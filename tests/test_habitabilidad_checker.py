from fastapi.testclient import TestClient

from app.main import app
from src.habitabilidad_checker import HabitabilityInput, check_habitability


client = TestClient(app)


def _complete_one_room_payload():
    return {
        "municipio": "Vigo",
        "tipo_operacion": "cambio_uso_local_a_vivienda",
        "altura_libre_m": 2.4,
        "programa_declarado_completo": True,
        "piezas": [
            {"nombre": "Estancia principal", "tipo": "estancia_mayor", "superficie_util_m2": 25, "ancho_minimo_m": 2.7, "lado_cuadrado_inscribible_m": 3.3, "superficie_acristalada_m2": 3.125, "superficie_ventilacion_m2": 1.05, "relacion_exterior": True},
            {"nombre": "Cocina", "tipo": "cocina", "superficie_util_m2": 5, "ancho_minimo_m": 1.8, "superficie_acristalada_m2": 0.625, "superficie_ventilacion_m2": 0.21, "relacion_exterior": True},
            {"nombre": "Baño", "tipo": "bano", "superficie_util_m2": 5, "ancho_minimo_m": 1.6},
            {"nombre": "Lavadero", "tipo": "lavadero", "superficie_util_m2": 1.5},
            {"nombre": "Tendedero", "tipo": "tendedero", "superficie_util_m2": 1.5},
            {"nombre": "Almacenamiento", "tipo": "almacenamiento", "superficie_util_m2": 1},
        ],
    }


def test_complete_one_room_dwelling_passes():
    result = check_habitability(HabitabilityInput.model_validate(_complete_one_room_payload()))
    assert result.estado_global == "cumple"
    assert result.cumple is True
    assert result.incumplimientos == []
    assert result.no_verificables == []


def test_change_of_use_height_minimum_is_2_40_m():
    payload = _complete_one_room_payload()
    payload["altura_libre_m"] = 2.39
    result = check_habitability(payload)
    height = next(check for check in result.comprobaciones if check.codigo == "altura_libre")
    assert height.estado == "no_cumple"
    assert height.requisito == "≥ 2.4 m"
    assert height.referencia == "Anexo I, A.3.1.1.d"
    assert result.estado_global == "no_cumple"


def test_incomplete_data_is_not_silently_failed():
    result = check_habitability({"municipio": "Vigo", "piezas": []})
    assert result.estado_global == "no_verificable"
    assert result.cumple is None
    assert "Altura libre mínima" in result.no_verificables
    assert result.incumplimientos == []


def test_declared_complete_program_reports_missing_services():
    result = check_habitability({
        "altura_libre_m": 2.4,
        "programa_declarado_completo": True,
        "piezas": [{"nombre": "Estancia", "tipo": "estancia_mayor", "superficie_util_m2": 25}],
    })
    assert result.estado_global == "no_cumple"
    assert "Presencia de cocina" in result.incumplimientos
    assert "Presencia de bano" in result.incumplimientos


def test_two_room_table_uses_16_and_12_square_metres():
    payload = _complete_one_room_payload()
    payload["piezas"][0].update({"superficie_util_m2": 16, "superficie_acristalada_m2": 2, "superficie_ventilacion_m2": 0.67})
    payload["piezas"].insert(1, {"nombre": "Dormitorio", "tipo": "estancia", "superficie_util_m2": 12, "ancho_minimo_m": 2.6, "lado_cuadrado_inscribible_m": 2.6, "superficie_acristalada_m2": 1.5, "superficie_ventilacion_m2": 0.5, "relacion_exterior": True})
    payload["piezas"][2].update({"superficie_util_m2": 7, "superficie_acristalada_m2": 0.875, "superficie_ventilacion_m2": 0.3})
    payload["piezas"][-1]["superficie_util_m2"] = 2
    result = check_habitability(payload)
    area_checks = {check.codigo: check for check in result.comprobaciones}
    assert area_checks["superficie_e1"].requisito == "≥ 16 m²"
    assert area_checks["superficie_e2"].requisito == "≥ 12 m²"
    assert result.estado_global == "cumple"


def test_api_returns_traceable_checks_and_official_sources():
    response = client.post("/habitabilidad/verificar", json=_complete_one_room_payload())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["estado_global"] == "cumple"
    assert data["version_reglas"] == "2024-09-12"
    assert len(data["fuentes"]) == 3
    assert all(source["url"].startswith("https://") for source in data["fuentes"])
    assert all(check["referencia"] for check in data["comprobaciones"])


def test_api_rejects_negative_dimensions():
    response = client.post("/habitabilidad/verificar", json={"altura_libre_m": -1, "piezas": []})
    assert response.status_code == 422


def test_assess_report_includes_habitability_section():
    from types import SimpleNamespace
    from src.report_service import render_assess_report_html

    result = SimpleNamespace(
        viability="condicionado",
        reasons=["Prechequeo"],
        params_effective={},
        geometry_summary=None,
        feature=None,
    )
    html = render_assess_report_html({"municipio": "Vigo", "habitabilidad": _complete_one_room_payload()}, result)
    assert "Verificación de habitabilidad" in html
    assert "Cumple las reglas comprobables" in html
    assert "Anexo I, A.3.1.1.d" in html
    assert "Decreto 128/2023 (DOG 176" in html
