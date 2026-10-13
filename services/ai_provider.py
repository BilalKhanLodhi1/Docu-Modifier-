"""Interchangeable AI text providers.

Providers expose one method, `complete(system, user, json_mode=True)`, that
returns the model's raw text. Configuration comes from Django settings, which
in turn read environment variables — keys are never hardcoded.
"""
import logging

import requests
from django.conf import settings

from .exceptions import AIProviderError

log = logging.getLogger("docucraft.ai")


class AIProvider:
    name = "base"
    label = "Base"
    is_cloud = False

    def available(self):
        """Return (ok: bool, message: str) without raising."""
        raise NotImplementedError

    def complete(self, system, user, json_mode=True):
        raise NotImplementedError

    @property
    def model(self):
        return ""


class NullProvider(AIProvider):
    name = "none"
    label = "No AI provider"

    def available(self):
        return False, "No AI provider is configured. Set AI_PROVIDER in your .env file."

    def complete(self, system, user, json_mode=True):
        raise AIProviderError("AI rewriting is unavailable because no AI provider is configured. "
                              "Formatting, splitting, image and conversion tools still work.")


class OllamaProvider(AIProvider):
    name = "ollama"
    label = "Ollama (local)"

    @property
    def model(self):
        return settings.OLLAMA_MODEL

    def available(self):
        try:
            r = requests.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=4)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            if not any(m == self.model or m.split(":")[0] == self.model.split(":")[0] for m in models):
                return False, f"Ollama is running but model '{self.model}' is not pulled. Run: ollama pull {self.model}"
            return True, f"Connected to Ollama, model {self.model}"
        except requests.RequestException:
            return False, f"Ollama is not reachable at {settings.OLLAMA_BASE_URL}. Start it with: ollama serve"

    def complete(self, system, user, json_mode=True):
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": 16384},
        }
        if json_mode:
            payload["format"] = "json"
        try:
            r = requests.post(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat", json=payload,
                              timeout=settings.AI_TIMEOUT)
        except requests.Timeout:
            raise AIProviderError("The local AI model took too long to respond. Try a smaller model or a shorter document.")
        except requests.RequestException:
            raise AIProviderError("Could not reach Ollama. Make sure it is running (ollama serve).")
        if r.status_code != 200:
            log.warning("Ollama error %s: %s", r.status_code, r.text[:300])
            raise AIProviderError(f"Ollama returned an error (HTTP {r.status_code}). Check that the model is installed.")
        return r.json().get("message", {}).get("content", "")


class AnthropicProvider(AIProvider):
    name = "anthropic"
    label = "Anthropic Claude (cloud)"
    is_cloud = True

    @property
    def model(self):
        return settings.ANTHROPIC_MODEL

    def available(self):
        if not settings.ANTHROPIC_API_KEY:
            return False, "ANTHROPIC_API_KEY is not set."
        return True, f"Configured, model {self.model}"

    def complete(self, system, user, json_mode=True):
        if not settings.ANTHROPIC_API_KEY:
            raise AIProviderError("ANTHROPIC_API_KEY is not set.")
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": self.model, "max_tokens": 8192, "temperature": 0.2, "system": system,
                      "messages": [{"role": "user", "content": user}]},
                timeout=settings.AI_TIMEOUT,
            )
        except requests.Timeout:
            raise AIProviderError("The cloud AI provider timed out.")
        except requests.RequestException:
            raise AIProviderError("Could not reach the cloud AI provider.")
        if r.status_code != 200:
            log.warning("Anthropic error %s: %s", r.status_code, r.text[:300])
            raise AIProviderError(f"The cloud AI provider returned an error (HTTP {r.status_code}).")
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


class OpenAICompatibleProvider(AIProvider):
    name = "openai"
    label = "OpenAI-compatible API (cloud)"
    is_cloud = True

    @property
    def model(self):
        return settings.OPENAI_MODEL

    def available(self):
        if not settings.OPENAI_API_KEY:
            return False, "OPENAI_API_KEY is not set."
        return True, f"Configured, model {self.model}"

    def complete(self, system, user, json_mode=True):
        if not settings.OPENAI_API_KEY:
            raise AIProviderError("OPENAI_API_KEY is not set.")
        body = {"model": self.model, "temperature": 0.2,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            r = requests.post(f"{settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions",
                              headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                              json=body, timeout=settings.AI_TIMEOUT)
        except requests.RequestException:
            raise AIProviderError("Could not reach the cloud AI provider.")
        if r.status_code != 200:
            log.warning("OpenAI-compatible error %s: %s", r.status_code, r.text[:300])
            raise AIProviderError(f"The cloud AI provider returned an error (HTTP {r.status_code}).")
        return r.json()["choices"][0]["message"]["content"]


PROVIDERS = {p.name: p for p in (OllamaProvider, AnthropicProvider, OpenAICompatibleProvider, NullProvider)}


def get_provider(name=None):
    name = (name or settings.AI_PROVIDER or "none").lower()
    return PROVIDERS.get(name, NullProvider)()


def provider_choices():
    return [(n, cls.label) for n, cls in PROVIDERS.items() if n != "none"]
