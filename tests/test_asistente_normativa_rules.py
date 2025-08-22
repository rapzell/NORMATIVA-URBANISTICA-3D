import sys
import os
import types

# Ensure project src is importable
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.asistente_normativa import generar_respuesta


class DummyLLM:
    def generate(self, *args, **kwargs):
        return ""


def test_infraestructuras_en_rustico_responde_afirmativo_art_32():
    pregunta = "¿Se permiten infraestructuras en suelo rústico según la Ley 2/2016?"
    # No necesitamos chunks para el caso especial; se devuelve canónico
    resp = generar_respuesta(pregunta, chunks_relevantes=[], llm=DummyLLM())
    low = resp.lower()
    assert "infraestructuras" in low
    assert "se permiten" in low or "permiten" in low
    assert "artículo 32" in low


def test_comparacion_nucleo_rural_vs_urbano_consolidado():
    pregunta = "¿En qué se diferencia un núcleo rural de un suelo urbano consolidado?"
    resp = generar_respuesta(pregunta, chunks_relevantes=[], llm=DummyLLM())
    low = resp.lower()
    assert "núcleo rural" in low or "nucleo rural" in low
    assert "urbano consolidado" in low
    assert "artículo 13" in low
    assert "artículo 17" in low


def test_comparacion_urbanizable_vs_nucleo_rural():
    pregunta = "¿Cuál es la diferencia entre suelo urbanizable y suelo de núcleo rural?"
    resp = generar_respuesta(pregunta, chunks_relevantes=[], llm=DummyLLM())
    low = resp.lower()
    assert "urbanizable" in low
    assert ("núcleo rural" in low) or ("nucleo rural" in low)
    assert "artículo 27" in low
    assert "artículo 13" in low
