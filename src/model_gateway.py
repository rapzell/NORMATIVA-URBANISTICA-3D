import os
import time
import random
import threading
from typing import Dict, List

# Environment-driven configuration
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "local").lower()  # initial read; actual selection is re-read per call
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # legacy default
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")  # legacy default
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")  # legacy default
TIMEOUT_S = float(os.getenv("TIMEOUT_S", "300"))

_OPENAI_COMPAT_PRESETS: Dict[str, Dict[str, str]] = {
    "openai": {"base_url": "", "model_env": "OPENAI_MODEL", "api_key_env": "OPENAI_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model_env": "OPENROUTER_MODEL", "api_key_env": "OPENROUTER_API_KEY", "default_model": "deepseek/deepseek-v4-flash-0731:free"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model_env": "GROQ_MODEL", "api_key_env": "GROQ_API_KEY", "default_model": "llama-3.1-8b-instant"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model_env": "GEMINI_MODEL", "api_key_env": "GEMINI_API_KEY", "default_model": "gemini-2.0-flash"},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "model_env": "MISTRAL_MODEL", "api_key_env": "MISTRAL_API_KEY", "default_model": "mistral-small-latest"},
    "cerebras": {"base_url": "https://api.cerebras.ai/v1", "model_env": "CEREBRAS_MODEL", "api_key_env": "CEREBRAS_API_KEY"},
    "huggingface": {"base_url": "https://api-inference.huggingface.co/v1", "model_env": "MODEL_NAME", "api_key_env": "MODEL_API_KEY"},
    "freellm": {"base_url": "http://localhost:3000/v1", "model_env": "MODEL_NAME", "api_key_env": "MODEL_API_KEY"},
}


# Global lock to serialize local generation calls (ctransformers is not thread-safe on Windows)
_LOCAL_LOCK = threading.Lock()

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _key_from_file(env_name: str) -> str:
    """Clave de respaldo leida de <repo>/api.txt (clave cruda) o
    api.env/.env (lineas KEY=VALUE). La variable de entorno manda.
    Devuelve '' bajo pytest para mantener los tests hermeticos."""
    if os.getenv('PYTEST_CURRENT_TEST'):
        return ''
    for fname in ('api.txt', 'api.env', '.env'):
        try:
            with open(os.path.join(_REPO_ROOT, fname), encoding='utf-8') as fh:
                lines = [l.strip() for l in fh
                         if l.strip() and not l.lstrip().startswith('#')]
        except OSError:
            continue
        for line in lines:
            if '=' in line:
                k, v = line.split('=', 1)
                if k.strip() == env_name:
                    return v.strip()
            elif env_name == 'OPENROUTER_API_KEY' and line.startswith('sk-'):
                return line
    return ''


def _default_provider() -> str:
    explicit = os.getenv("MODEL_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if _key_from_file("OPENROUTER_API_KEY"):
        return "openrouter"
    return "local"


def _get_timeout_s() -> float:
    try:
        return float(os.getenv("TIMEOUT_S", str(TIMEOUT_S)))
    except Exception:
        return TIMEOUT_S


def _get_temperature() -> float:
    try:
        return float(os.getenv("MODEL_TEMPERATURE", os.getenv("OPENAI_TEMPERATURE", "0.2")))
    except Exception:
        return 0.2


def _get_max_tokens() -> int:
    # Los modelos gratuitos con razonamiento consumen tokens pensando;
    # con ~600 la respuesta final llega vacia.
    raw = os.getenv("MODEL_MAX_TOKENS") or os.getenv("OPENAI_MAX_TOKENS") or "8000"
    try:
        return int(raw)
    except Exception:
        return 8000


def _get_provider_config(provider: str) -> Dict[str, str]:
    normalized = (provider or "").strip().lower()
    preset = dict(_OPENAI_COMPAT_PRESETS.get(normalized, {}))
    model_env = preset.get("model_env", "MODEL_NAME")
    api_key_env = preset.get("api_key_env", "MODEL_API_KEY")

    if normalized == "openai":
        model_name = os.getenv("MODEL_NAME") or os.getenv("OPENAI_MODEL", OPENAI_MODEL)
        api_key = os.getenv("MODEL_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("MODEL_BASE_URL") or os.getenv("OPENAI_BASE_URL", preset.get("base_url", ""))
    else:
        model_name = (os.getenv(model_env) or os.getenv("MODEL_NAME", "")
                      or preset.get("default_model", ""))
        api_key = (os.getenv("MODEL_API_KEY") or os.getenv(api_key_env, "")
                   or _key_from_file(api_key_env))
        base_url = os.getenv("MODEL_BASE_URL") or preset.get("base_url", "")

    return {
        "provider": normalized,
        "base_url": base_url.strip(),
        "model_name": model_name.strip(),
        "api_key": api_key.strip(),
    }



def _call_openai_compatible(prompt: str, provider: str, timeout: float) -> str:
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError(f"openai_sdk_missing: {e}")

    cfg = _get_provider_config(provider)
    model_name = cfg["model_name"]
    if not model_name:
        raise RuntimeError(f"{provider}_model_missing")

    client_kwargs = {}
    if cfg["api_key"]:
        client_kwargs["api_key"] = cfg["api_key"]
    if cfg["base_url"]:
        client_kwargs["base_url"] = cfg["base_url"]

    try:
        client = OpenAI(**client_kwargs)
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=_get_temperature(),
            max_tokens=_get_max_tokens(),
            timeout=timeout,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        raise RuntimeError(f"{provider}_error: {e}")



def _call_openai(prompt: str, timeout: float) -> str:
    return _call_openai_compatible(prompt, "openai", timeout)



def _call_ollama(prompt: str, timeout: float) -> str:
    try:
        import requests  # type: ignore
    except Exception as e:
        raise RuntimeError(f"ollama_requests_missing: {e}")
    host = os.getenv("OLLAMA_HOST", OLLAMA_HOST)
    model_name = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL)
    url = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.2")),
            "top_p": float(os.getenv("OLLAMA_TOP_P", "0.85")),
            "top_k": int(os.getenv("OLLAMA_TOP_K", "30")),
            "repeat_penalty": float(os.getenv("OLLAMA_REP_PENALTY", "1.1")),
            "num_predict": int(os.getenv("OLLAMA_MAX_NEW_TOKENS", "220")),
            "stop": [
                "</s>", "\n\n", "Fuentes:", "**Fuentes", "Pregunta:", "Preguntas relacionadas:"
            ],
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        txt = (data.get("response") or "").strip()
        if not txt:
            raise RuntimeError("ollama_empty_response")
        return txt
    except Exception as e:
        raise RuntimeError(f"ollama_error: {e}")



def _call_local(llm, prompt: str) -> str:
    # ctransformers models are callable. Conservative decoding to reduce repetition and length.
    import os as _os
    max_new_tokens = int(_os.getenv("LOCAL_MAX_NEW_TOKENS", "150"))
    temperature = float(_os.getenv("LOCAL_TEMPERATURE", "0.2"))
    top_p = float(_os.getenv("LOCAL_TOP_P", "0.85"))
    top_k = int(_os.getenv("LOCAL_TOP_K", "30"))
    repetition_penalty = float(_os.getenv("LOCAL_REP_PENALTY", "1.15"))
    # Stop tokens por defecto para cortar respuestas largas o nuevas preguntas
    default_stops = [
        "</s>",
        "\n\n",
        "Fuentes:",
        "**Fuentes",
        "Pregunta:",
        "Preguntas relacionadas:",
    ]
    stop_env = _os.getenv("LOCAL_STOP")
    if stop_env:
        stop = [s for s in stop_env.split("|") if s]
    else:
        stop = default_stops

    return llm(
        prompt,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
        stop=stop
    ).strip()



def _call_local_with_timeout(llm, prompt: str, timeout: float) -> str:
    # To avoid Windows access violations, avoid background threads and serialize access.
    # We simulate a "safe" path by reducing token budget for safety and calling directly.
    os.environ.setdefault("LOCAL_MAX_NEW_TOKENS", "120")
    with _LOCAL_LOCK:
        return _call_local(llm, prompt)



def _iter_provider_attempts() -> List[str]:
    provider = _default_provider()
    raw_chain = os.getenv("MODEL_FALLBACK_CHAIN", "")
    seen = set()
    attempts: List[str] = []
    for name in [provider] + [p.strip().lower() for p in raw_chain.split(",") if p.strip()]:
        if name and name not in seen:
            attempts.append(name)
            seen.add(name)
    return attempts or ["local"]



def _provider_attempt(provider: str, prompt: str, timeout: float) -> str:
    if provider == "local":
        raise RuntimeError("local_provider_requires_llm")
    if provider == "ollama":
        return _call_ollama(prompt, timeout)
    if provider in _OPENAI_COMPAT_PRESETS:
        return _call_openai_compatible(prompt, provider, timeout)
    raise RuntimeError(f"unsupported_provider: {provider}")



def _local_fallback(prompt: str, llm_local, timeout: float) -> str:
    try:
        return _call_local_with_timeout(llm_local, prompt, timeout)
    except Exception as e:
        os.environ["LOCAL_MAX_NEW_TOKENS"] = "80"
        os.environ["LOCAL_TEMPERATURE"] = "0.15"
        os.environ["LOCAL_TOP_P"] = "0.8"
        try:
            return _call_local_with_timeout(llm_local, prompt, timeout)
        except Exception as e2:
            return f"No ha sido posible generar respuesta (local fallo): {e2}"



def generate_with_fallback(prompt: str, llm_local) -> str:
    """Generate using the configured provider chain and fall back to local llm when needed."""

    def low_response(s: str) -> bool:
        txt = s.strip()
        if not txt:
            return True
        try:
            min_chars = int(os.getenv("MODEL_MIN_RESPONSE_CHARS", "8"))
        except Exception:
            min_chars = 8
        return len(txt) < min_chars

    timeout = _get_timeout_s()
    attempts = _iter_provider_attempts()

    for provider in attempts:
        if provider == "local":
            break
        for attempt in range(2):
            try:
                ans = _provider_attempt(provider, prompt, timeout)
                if not low_response(ans):
                    return ans
            except Exception:
                pass
            time.sleep(0.8 * (2 ** attempt) + random.uniform(0, 0.2))

    return _local_fallback(prompt, llm_local, timeout)


def provider_status() -> Dict[str, object]:
    """Estado de configuración del gateway para diagnósticos (/qa/health).

    No expone claves — solo si están definidas.
    """
    provider = _default_provider()
    chain = _iter_provider_attempts()
    providers: Dict[str, object] = {}
    for name in _OPENAI_COMPAT_PRESETS:
        cfg = _get_provider_config(name)
        providers[name] = {
            "model": cfg["model_name"] or None,
            "configured": bool(cfg["api_key"] or name == "freellm"),
        }
    providers["ollama"] = {"model": os.getenv("OLLAMA_MODEL", OLLAMA_MODEL),
                           "configured": True}
    providers["local"] = {"model": "GGUF local (ctransformers)",
                          "configured": True}
    return {"provider": provider, "fallback_chain": chain,
            "providers": providers}


def stream_openai_compatible(prompt: str, provider: str,
                             timeout: float):
    """Generador de tokens vía streaming OpenAI-compatible.

    Usado por el endpoint SSE; lanza RuntimeError si el proveedor no
    está disponible para que el llamador pase al modo no-stream.
    """
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError(f"openai_sdk_missing: {e}")
    cfg = _get_provider_config(provider)
    if not cfg["model_name"]:
        raise RuntimeError(f"{provider}_model_missing")
    client_kwargs = {}
    if cfg["api_key"]:
        client_kwargs["api_key"] = cfg["api_key"]
    if cfg["base_url"]:
        client_kwargs["base_url"] = cfg["base_url"]
    client = OpenAI(**client_kwargs)
    stream = client.chat.completions.create(
        model=cfg["model_name"],
        messages=[{"role": "user", "content": prompt}],
        temperature=_get_temperature(),
        max_tokens=_get_max_tokens(),
        timeout=timeout,
        stream=True,
    )
    for chunk in stream:
        try:
            delta = chunk.choices[0].delta.content
        except Exception:
            delta = None
        if delta:
            yield delta


def stream_with_fallback(prompt: str):
    """Itera proveedores de la cadena y devuelve el primer stream viable.

    Devuelve ``(provider, generator)``; si ningún proveedor OpenAI-
    compatible sirve, ``(None, None)`` y el llamador usa el modo
    heurístico no-stream.
    """
    timeout = _get_timeout_s()
    for provider in _iter_provider_attempts():
        if provider in ("local", "ollama"):
            continue
        if provider not in _OPENAI_COMPAT_PRESETS:
            continue
        cfg = _get_provider_config(provider)
        if not cfg["api_key"] and provider != "freellm":
            continue
        try:
            gen = stream_openai_compatible(prompt, provider, timeout)
            return provider, gen
        except Exception:
            continue
    return None, None
