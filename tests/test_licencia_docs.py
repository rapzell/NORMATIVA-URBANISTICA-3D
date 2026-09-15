from fastapi.testclient import TestClient

from app.main import app
from src.licencia_docs import LicenciaInput, render_licencia_html

client = TestClient(app)


def _payload_with_habitability():
    return {
        "municipio": "Vigo",
        "ref_catastral": "3057003NG2725N",
        "direccion_catastral": "RU MARQUES DE ALCEDO 13 VIGO",
        "superficie_parcela_m2": 120.5,
        "clasificacion_suelo": "Suelo urbano consolidado",
        "instrumento_planeamiento": "PXOM Vigo 2025",
        "fecha_aprobacion": "2025-05-01",
        "params_urbanisticos": {"altura_maxima_m": 12, "ocupacion_max": 0.7},
        "tipo_operacion": "cambio_uso_local_a_vivienda",
        "habitabilidad": {
            "municipio": "Vigo",
            "altura_libre_m": 2.4,
            "programa_declarado_completo": True,
            "piezas": [
                {"nombre": "E", "tipo": "estancia_mayor", "superficie_util_m2": 25, "ancho_minimo_m": 2.7, "lado_cuadrado_inscribible_m": 3.3, "superficie_acristalada_m2": 3.125, "superficie_ventilacion_m2": 1.05, "relacion_exterior": True},
                {"nombre": "C", "tipo": "cocina", "superficie_util_m2": 5, "ancho_minimo_m": 1.8, "superficie_acristalada_m2": 0.625, "superficie_ventilacion_m2": 0.21, "relacion_exterior": True},
                {"nombre": "B", "tipo": "bano", "superficie_util_m2": 5, "ancho_minimo_m": 1.6},
                {"nombre": "L", "tipo": "lavadero", "superficie_util_m2": 1.5},
                {"nombre": "T", "tipo": "tendedero", "superficie_util_m2": 1.5},
                {"nombre": "A", "tipo": "almacenamiento", "superficie_util_m2": 1},
            ],
        },
        "superficies": {"superficie_util_m2": 45, "superficie_construida_m2": 55},
    }


def test_render_includes_inmueble_and_habitabilidad():
    html = render_licencia_html(LicenciaInput(**_payload_with_habitability()))
    assert "Datos del inmueble" in html
    assert "3057003NG2725N" in html
    assert "RU MARQUES DE ALCEDO 13 VIGO" in html
    assert "Justificación del cumplimiento del Decreto 128/2023" in html
    assert "Cumple las reglas comprobables" in html
    assert "Anexo I, A.3.1.1.d" in html
    assert "Cuadro de superficies" in html
    assert "45 m²" in html
    assert "sedecatastro.es" in html


def test_render_marks_missing_municipal_ordinance():
    payload = _payload_with_habitability()
    payload.pop("fuente_ordenanza_municipal", None)
    html = render_licencia_html(payload)
    assert "Pendiente" in html
    assert "ordenanza municipal de cambio de uso" in html


def test_render_works_with_minimal_data():
    html = render_licencia_html({"municipio": "A Coruña"})
    assert "Documentación de licencia" in html
    assert "A Coruña" in html
    assert "—" in html


def test_render_escapes_user_input():
    html = render_licencia_html({"municipio": "<script>x</script>", "ref_catastral": "';--"})
    assert "<script>x</script>" not in html
    assert "lt;script" in html and "gt;" in html


def test_api_returns_html_document():
    response = client.post("/licencia/documentacion", json=_payload_with_habitability())
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Datos del inmueble" in response.text
    assert "3057003NG2725N" in response.text


def test_api_accepts_minimal_payload():
    response = client.post("/licencia/documentacion", json={"municipio": "Vigo"})
    assert response.status_code == 200
    assert "Documentación de licencia" in response.text
