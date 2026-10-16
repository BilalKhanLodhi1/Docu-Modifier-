"""Interchangeable AI text providers.

Providers expose one method, `complete(system, user, json_mode=True)`, that
returns the model's raw text. Configuration comes from Django settings, which
in turn read environment variables — keys are never hardcoded.
"""
import json
import logging
import time


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


def _context_size(system, user):
    """Context window for one request: room for the prompt plus an answer of similar length.

    Reserving only what is needed keeps memory use and load time down on laptops.
    Roughly 3 characters per token; rounded up to a multiple of 2048, between 4096 and 16384.
    """
    prompt_tokens = (len(system) + len(user)) // 3
    needed = prompt_tokens + len(user) // 3 + 512
    return max(4096, min(16384, -(-needed // 2048) * 2048))


def _ollama_name(name):
    """Ollama treats 'llama3.1' and 'llama3.1:latest' as the same model; nothing else is interchangeable."""
    name = name.strip()
    return name if ":" in name else f"{name}:latest"


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
            if _ollama_name(self.model) not in {_ollama_name(m) for m in models}:
                have = ", ".join(sorted(models)) or "none"
                return False, (f"Ollama is running but model '{self.model}' is not installed. "
                               f"Run: ollama pull {self.model}  (installed: {have})")
            return True, f"Connected to Ollama, model {self.model}"
        except requests.RequestException:
            return False, f"Ollama is not reachable at {settings.OLLAMA_BASE_URL}. Start it with: ollama serve"

    def complete(self, system, user, json_mode=True):
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            # Streaming: text arrives as it is written, so the timeout only trips if the model goes silent.
            "stream": True,
            "keep_alive": "15m",
            "options": {"temperature": 0.2, "num_ctx": _context_size(system, user)},
        }
        if json_mode:
            payload["format"] = "json"
        url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        try:
            r = requests.post(url, json=payload, stream=True, timeout=(10, settings.AI_TIMEOUT))
        except requests.Timeout:
            raise AIProviderError(self._slow_message("start answering"))
        except requests.RequestException:
            raise AIProviderError("Could not reach Ollama. Make sure it is running (ollama serve).")
        with r:
            if r.status_code == 200:
                return self._read_stream(r)
            self._raise_for_status(r)

    def _read_stream(self, response):
        deadline = time.monotonic() + settings.AI_MAX_CALL_SECONDS
        parts = []
        try:
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise AIProviderError(f"Ollama reported an error: {chunk['error']}")
                parts.append(chunk.get("message", {}).get("content", ""))
                if chunk.get("done"):
                    break
                if time.monotonic() > deadline:
                    raise AIProviderError(
                        f"One part of the document took over {settings.AI_MAX_CALL_SECONDS // 60} minutes. "
                        "Lower AI_CHUNK_CHARS in .env (for example to 1500) or use a smaller model.")
        except (requests.Timeout, requests.ConnectionError):
            raise AIProviderError(self._slow_message("continue"))
        except ValueError:
            raise AIProviderError("Ollama sent a response DocuCraft could not read. Try again.")
        return "".join(parts)

    def _slow_message(self, what):
        return (f"The local model '{self.model}' did not {what} within {settings.AI_TIMEOUT} seconds. "
                "It may still be loading, or this computer may be busy. Try again, raise AI_TIMEOUT in .env, "
                "or use a smaller model.")

    def _raise_for_status(self, r):
        log.warning("Ollama error %s: %s", r.status_code, r.text[:300])
        try:
            detail = r.json().get("error", "")
        except ValueError:
            detail = ""
        if r.status_code == 404:
            raise AIProviderError(f"Ollama has no model named '{self.model}'. Run: ollama pull {self.model}, "
                                  "or set OLLAMA_MODEL in .env to a name shown by: ollama list")
        raise AIProviderError(f"Ollama returned an error (HTTP {r.status_code}){': ' + detail if detail else ''}.")


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
