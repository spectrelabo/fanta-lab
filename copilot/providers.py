"""
Spectre - FantaMoneyball Copilot — LLM Provider Implementations.

Provider priority (first available wins):
1. OllamaProvider   — LLM_BASE_URL set (default http://localhost:11434/v1)
2. OpenAIProvider   — LLM_API_KEY set without LLM_BASE_URL pointing to Ollama
3. GeminiProvider   — GEMINI_API_KEY set
4. None             — Falls back to HeuristicProvider in app.py
"""

import os
import json
import requests


class CopilotProvider:
    """Base interface for LLM providers."""
    engine_name: str = "unknown"

    def query(self, system_prompt: str, user_prompt: str, temperature: float = 0.35, max_tokens: int = 650) -> str | None:
        raise NotImplementedError


class OllamaProvider(CopilotProvider):
    """Local Ollama via OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.engine_name = f"ollama/{model}"

    def query(self, system_prompt: str, user_prompt: str, temperature: float = 0.35, max_tokens: int = 650) -> str | None:
        endpoint = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        resp = requests.post(endpoint, json=payload, headers=headers, timeout=12)
        if resp.status_code == 200:
            return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return None


class OpenAIProvider(CopilotProvider):
    """Any OpenAI-compatible cloud API (OpenAI, DeepSeek, Groq, vLLM, etc.)."""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.engine_name = model

    def query(self, system_prompt: str, user_prompt: str, temperature: float = 0.35, max_tokens: int = 650) -> str | None:
        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return None


class GeminiProvider(CopilotProvider):
    """Google Gemini native REST API."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash-lite"):
        self.api_key = api_key
        self.model = model
        self.engine_name = model

    def query(self, system_prompt: str, user_prompt: str, temperature: float = 0.35, max_tokens: int = 650) -> str | None:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

        payload = {
            "contents": [{
                "role": "user",
                "parts": [{"text": f"System Context:\n{system_prompt}\n\n{user_prompt}"}]
            }],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }

        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return (resp.json()
                    .get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "").strip())
        return None


class GroqProvider(OpenAIProvider):
    """Zero-cost cloud LLM inference via Groq Free Tier (Llama 3.3 / Llama 3.1 / Qwen)."""
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        super().__init__(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
            model=model
        )
        self.engine_name = f"Groq ({model})"


class CascadeProvider(CopilotProvider):
    """Chains multiple LLM providers. Falls through on 429 rate limit or connection errors."""
    def __init__(self, providers: list[CopilotProvider]):
        self.providers = providers
        self.engine_name = "Cascade (" + " → ".join(p.engine_name for p in providers) + ")"
        self.last_successful_engine = None

    def query(self, system_prompt: str, user_prompt: str, temperature: float = 0.35, max_tokens: int = 650) -> str | None:
        for p in self.providers:
            try:
                reply = p.query(system_prompt, user_prompt, temperature, max_tokens)
                if reply:
                    self.last_successful_engine = p.engine_name
                    return reply
            except Exception:
                continue
        return None


def get_copilot_provider() -> CopilotProvider | None:
    """
    Factory: returns a cascading failover chain based on available free tiers and env vars.
    Cascade Order:
      1. Groq Free Tier (if GROQ_API_KEY present)
      2. Gemini Free Tier (if GEMINI_API_KEY present)
      3. Ollama local (if LLM_BASE_URL present and not on Vercel)
      4. None -> Fallback to Local Quantitative Reasoner in app.py (0$ Cost)
    """
    is_vercel = bool(os.environ.get("VERCEL"))
    available_providers: list[CopilotProvider] = []

    # 1. Groq Free Tier (Ultra-fast, 0 token cost, no credit card required)
    groq_key = os.environ.get("GROQ_API_KEY")
    groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    if groq_key:
        available_providers.append(GroqProvider(api_key=groq_key, model=groq_model))

    # 2. Google Gemini Free Tier
    gemini_key = os.environ.get("GEMINI_API_KEY")
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")
    if gemini_key:
        available_providers.append(GeminiProvider(api_key=gemini_key, model=gemini_model))

    # 3. Generic OpenAI-compatible / Remote endpoint (if explicitly set and different from Groq)
    llm_api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    llm_base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    llm_model = os.environ.get("LLM_MODEL", "qwen2.5:3b")

    if is_vercel and llm_base_url and ("localhost" in llm_base_url or "127.0.0.1" in llm_base_url):
        llm_base_url = None

    if llm_api_key and llm_api_key != groq_key:
        base = llm_base_url or "https://api.openai.com/v1"
        available_providers.append(OpenAIProvider(base_url=base, api_key=llm_api_key, model=llm_model))

    # 4. Ollama / Local inference (only when running on local machine, not on Vercel)
    if llm_base_url and not llm_api_key and not is_vercel:
        available_providers.append(OllamaProvider(base_url=llm_base_url, model=llm_model))

    if not available_providers:
        # None -> app.py activates the zero-cost local quantitative engine
        return None

    if len(available_providers) == 1:
        return available_providers[0]

    return CascadeProvider(available_providers)
