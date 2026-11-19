"""Open-source VLM client. Default: local Ollama (Qwen2.5-VL) — zero credits, fully local.

Provider is selectable by env so you can point at a free hosted OpenAI-compatible
endpoint (e.g. NVIDIA build.nvidia.com, OpenRouter) without changing the pipeline:

  LAB_VLM_PROVIDER = "ollama" (default) | "openai"
  LAB_VLM_MODEL    = "qwen2.5vl:7b" (default for ollama)
  LAB_OLLAMA_URL   = "http://localhost:11434"
  LAB_OPENAI_BASE  = e.g. "https://integrate.api.nvidia.com/v1"
  LAB_OPENAI_KEY   = api key for the hosted endpoint
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests


def _load_env_file() -> None:
    """Load lab/.env (KEY=VALUE lines) so secrets stay out of the shell/chat/git."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()

PROVIDER = os.getenv("LAB_VLM_PROVIDER", "ollama").strip().lower()
OLLAMA_URL = os.getenv("LAB_OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("LAB_VLM_MODEL", "qwen2.5vl:7b")
OPENAI_BASE = os.getenv("LAB_OPENAI_BASE", "").rstrip("/")
OPENAI_KEY = os.getenv("LAB_OPENAI_KEY", "")
OPENAI_MODEL = os.getenv("LAB_VLM_MODEL", "qwen/qwen2.5-vl-7b-instruct")


def model_name() -> str:
    return OLLAMA_MODEL if PROVIDER == "ollama" else OPENAI_MODEL


def run_vlm(images_b64: list[str], prompt: str) -> dict[str, Any]:
    """Send page images + prompt to the VLM. Returns {text, model, error, latency_ms}."""
    t0 = time.time()
    try:
        if PROVIDER == "openai":
            text = _run_openai(images_b64, prompt)
        else:
            text = _run_ollama(images_b64, prompt)
        return {"text": text, "model": model_name(), "error": None,
                "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"text": "", "model": model_name(), "error": str(e),
                "latency_ms": int((time.time() - t0) * 1000)}


def _run_ollama(images_b64: list[str], prompt: str) -> str:
    body = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt, "images": images_b64}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=900)
    r.raise_for_status()
    data = r.json()
    return (data.get("message") or {}).get("content", "") or ""


def _run_openai(images_b64: list[str], prompt: str) -> str:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for b64 in images_b64:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    headers = {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}
    use_json = True  # force valid JSON so the model can't lapse into prose
    last = ""
    for attempt in range(4):
        body = {
            "model": OPENAI_MODEL,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            # Small per-band output → faster generation → the request completes
            # before the hosted gateway's timeout (a big cause of 504s).
            "max_tokens": 2000,
        }
        if use_json:
            body["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(f"{OPENAI_BASE}/chat/completions", json=body, headers=headers, timeout=240)
            if r.status_code == 400 and use_json:
                use_json = False  # endpoint doesn't support JSON mode — drop it and retry
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"{r.status_code} from endpoint"
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except requests.exceptions.RequestException as e:
            last = str(e)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"endpoint failed after retries: {last}")


def health() -> dict[str, Any]:
    """Report whether the configured VLM is reachable and the model is present."""
    if PROVIDER != "ollama":
        return {"provider": PROVIDER, "model": model_name(), "reachable": bool(OPENAI_BASE)}
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        return {"provider": "ollama", "model": OLLAMA_MODEL, "reachable": True,
                "model_present": OLLAMA_MODEL in names, "available_models": names}
    except Exception as e:  # noqa: BLE001
        return {"provider": "ollama", "model": OLLAMA_MODEL, "reachable": False, "error": str(e)}
