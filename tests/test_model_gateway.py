import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import model_gateway


def test_generate_with_fallback_usa_cadena_de_respaldo(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("MODEL_FALLBACK_CHAIN", "groq,local")
    llamadas = []

    def fake_provider_attempt(provider, prompt, timeout):
        llamadas.append(provider)
        if provider == "openrouter":
            raise RuntimeError("boom")
        if provider == "groq":
            return "x" * 80
        raise AssertionError(f"Proveedor inesperado: {provider}")

    monkeypatch.setattr(model_gateway, "_provider_attempt", fake_provider_attempt)
    monkeypatch.setattr(model_gateway.time, "sleep", lambda *_args, **_kwargs: None)

    respuesta = model_gateway.generate_with_fallback("hola", llm_local=None)

    assert respuesta == "x" * 80
    assert llamadas == ["openrouter", "openrouter", "groq"]


def test_generate_with_fallback_respuesta_corta_cae_a_local(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("MODEL_FALLBACK_CHAIN", "")
    monkeypatch.setenv("MODEL_MIN_RESPONSE_CHARS", "8")
    llamadas = []

    def fake_provider_attempt(provider, prompt, timeout):
        llamadas.append(provider)
        return "hola"

    def fake_local_fallback(prompt, llm_local, timeout):
        return "respuesta local suficientemente larga para pasar el umbral"

    monkeypatch.setattr(model_gateway, "_provider_attempt", fake_provider_attempt)
    monkeypatch.setattr(model_gateway, "_local_fallback", fake_local_fallback)
    monkeypatch.setattr(model_gateway.time, "sleep", lambda *_args, **_kwargs: None)

    respuesta = model_gateway.generate_with_fallback("hola", llm_local=None)

    assert respuesta.startswith("respuesta local")
    assert llamadas == ["openrouter", "openrouter"]


def test_generate_with_fallback_acepta_respuesta_breve_si_supera_umbral(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("MODEL_FALLBACK_CHAIN", "")
    monkeypatch.setenv("MODEL_MIN_RESPONSE_CHARS", "4")
    llamadas = []

    def fake_provider_attempt(provider, prompt, timeout):
        llamadas.append(provider)
        return "Hola"

    monkeypatch.setattr(model_gateway, "_provider_attempt", fake_provider_attempt)
    monkeypatch.setattr(model_gateway.time, "sleep", lambda *_args, **_kwargs: None)

    respuesta = model_gateway.generate_with_fallback("hola", llm_local=None)

    assert respuesta == "Hola"
    assert llamadas == ["openrouter"]


def test_generate_with_fallback_modo_local_directo(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "local")
    monkeypatch.delenv("MODEL_FALLBACK_CHAIN", raising=False)

    called = {"provider": 0, "local": 0}

    def fake_provider_attempt(provider, prompt, timeout):
        called["provider"] += 1
        return "no debería llamarse"

    def fake_local_fallback(prompt, llm_local, timeout):
        called["local"] += 1
        return "respuesta local"

    monkeypatch.setattr(model_gateway, "_provider_attempt", fake_provider_attempt)
    monkeypatch.setattr(model_gateway, "_local_fallback", fake_local_fallback)

    respuesta = model_gateway.generate_with_fallback("hola", llm_local=object())

    assert respuesta == "respuesta local"
    assert called == {"provider": 0, "local": 1}


def test_get_provider_config_openrouter_prioriza_model_name_y_api_key(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "meta-llama/llama-3.3-70b-instruct:free")
    monkeypatch.setenv("MODEL_API_KEY", "clave-demo")
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)

    cfg = model_gateway._get_provider_config("openrouter")

    assert cfg["provider"] == "openrouter"
    assert cfg["base_url"] == "https://openrouter.ai/api/v1"
    assert cfg["model_name"] == "meta-llama/llama-3.3-70b-instruct:free"
    assert cfg["api_key"] == "clave-demo"


def test_iter_provider_attempts_deduplica_y_preserva_orden(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "groq")
    monkeypatch.setenv("MODEL_FALLBACK_CHAIN", "gemini,groq,local,gemini")

    attempts = model_gateway._iter_provider_attempts()

    assert attempts == ["groq", "gemini", "local"]
