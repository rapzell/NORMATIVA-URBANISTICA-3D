import os
import time
import random
import threading
from typing import Optional

# Environment-driven configuration
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "local").lower()  # initial read; actual selection is re-read per call
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # initial default
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")  # initial default
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")  # initial default
TIMEOUT_S = float(os.getenv("TIMEOUT_S", "45"))


def _call_openai(prompt: str, timeout: float) -> str:
    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError(f"openai_sdk_missing: {e}")

    client = OpenAI()
    try:
        model_name = os.getenv("OPENAI_MODEL", OPENAI_MODEL)
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=600,
            timeout=timeout,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        raise RuntimeError(f"openai_error: {e}")


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
        "\n\n",           # salto doble de párrafo
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


# Global lock to serialize local generation calls (ctransformers is not thread-safe on Windows)
_LOCAL_LOCK = threading.Lock()

def _call_local_with_timeout(llm, prompt: str, timeout: float) -> str:
    # To avoid Windows access violations, avoid background threads and serialize access.
    # We simulate a "safe" path by reducing token budget for safety and calling directly.
    os.environ.setdefault("LOCAL_MAX_NEW_TOKENS", "120")
    with _LOCAL_LOCK:
        return _call_local(llm, prompt)


def generate_with_fallback(prompt: str, llm_local) -> str:
    """Generate using OpenAI if configured; otherwise use local llm.
    Falls back to GPT-4o then local if low response or errors.
    """
    def low_response(s: str) -> bool:
        # very short or empty
        return len(s.strip()) < 40

    # Re-read provider dynamically per call
    provider = os.getenv("MODEL_PROVIDER", MODEL_PROVIDER).lower()

    # Try OpenAI primary model if enabled
    if provider == "openai":
        # up to 2 attempts on the chosen model
        for attempt in range(2):
            try:
                ans = _call_openai(prompt, TIMEOUT_S)
                if not low_response(ans):
                    return ans
            except Exception:
                pass
            time.sleep(0.8 * (2 ** attempt) + random.uniform(0, 0.2))

        # fallback to gpt-4o if different from primary
        if os.getenv("OPENAI_MODEL", OPENAI_MODEL).lower() != "gpt-4o":
            try:
                os.environ["OPENAI_MODEL"] = "gpt-4o"
                ans = _call_openai(prompt, TIMEOUT_S)
                if not low_response(ans):
                    return ans
            except Exception:
                pass

    # Try Ollama primary model if enabled
    if provider == "ollama":
        for attempt in range(2):
            try:
                ans = _call_ollama(prompt, TIMEOUT_S)
                if not low_response(ans):
                    return ans
            except Exception:
                pass
            time.sleep(0.8 * (2 ** attempt) + random.uniform(0, 0.2))

    # final fallback: local model with timeout and fast retry
    try:
        return _call_local_with_timeout(llm_local, prompt, TIMEOUT_S)
    except Exception as e:
        # As última opción, reducir aún más y reintentar una vez
        os.environ["LOCAL_MAX_NEW_TOKENS"] = "80"
        os.environ["LOCAL_TEMPERATURE"] = "0.15"
        os.environ["LOCAL_TOP_P"] = "0.8"
        try:
            return _call_local_with_timeout(llm_local, prompt, TIMEOUT_S)
        except Exception as e2:
            return f"No ha sido posible generar respuesta (local fallo): {e2}"
