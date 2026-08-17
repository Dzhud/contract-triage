"""
Provider-agnostic LLM interface.

The whole system talks to *this* interface, never directly to a specific
vendor's SDK. That means we can swap the model behind it — Claude today,
a locally-hosted model tomorrow — without touching any of the triage logic.

Why this matters for a *legal* contract-review tool specifically:
contract text is confidential. A production deployment might well choose to
run a smaller model on-prem to keep sensitive data in-house, trading some
capability for privacy. Keeping the provider behind an interface makes that
a config change, not a rewrite.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    raw: object = None  # the underlying provider response, for debugging


class LLMProvider(ABC):
    """Any model backend must implement this. That's the whole contract."""

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 1500) -> LLMResponse:
        ...

    def complete_json(self, system: str, user: str, max_tokens: int = 1500) -> dict:
        """
        Ask the model for JSON and parse it defensively.

        LLMs sometimes wrap JSON in prose or code fences even when told not to,
        so we extract the first well-formed JSON object rather than trusting
        the response to be clean. If we still can't parse it, we fail loudly
        rather than silently returning junk — important in a legal context.
        """
        resp = self.complete(system, user, max_tokens=max_tokens)
        return _extract_json(resp.text)


class AnthropicProvider(LLMProvider):
    """Claude backend. Reads the key from the environment, never hard-coded."""

    def __init__(self, model: str = "claude-sonnet-4-5", api_key: str | None = None):
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "Install the Anthropic SDK: pip install anthropic"
            ) from e
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "No API key found. Set ANTHROPIC_API_KEY in your environment "
                "(see .env.example). Never commit your key."
            )
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> LLMResponse:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        return LLMResponse(text=text, raw=msg)


class LocalGGUFProvider(LLMProvider):
    """
    Local model backend (e.g. a GGUF file via llama-cpp-python).

    Included to demonstrate the privacy angle: the exact same pipeline can run
    entirely on-prem with no contract text leaving the building. A 1.1B model
    like TinyLlama is too weak for reliable clause analysis, so this is here as
    a proof of swappability, not a recommendation for production accuracy.
    """

    def __init__(self, model_path: str, n_ctx: int = 4096):
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise ImportError(
                "Install llama-cpp-python to use a local GGUF model."
            ) from e
        self._llm = Llama(model_path=model_path, n_ctx=n_ctx, verbose=False)

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> LLMResponse:
        prompt = f"<|system|>\n{system}\n<|user|>\n{user}\n<|assistant|>\n"
        out = self._llm(prompt, max_tokens=max_tokens, stop=["<|user|>"])
        text = out["choices"][0]["text"]
        return LLMResponse(text=text, raw=out)


class StubProvider(LLMProvider):
    """
    Deterministic stub for offline development and testing.

    Lets the whole pipeline (and the eval harness) run with no API key and no
    network — so tests are fast, free and reproducible. Returns canned but
    plausibly-shaped JSON based on simple keyword checks.
    """

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> LLMResponse:
        """
        A deliberately simple, keyword-driven stand-in for a real model.

        It is good enough to make the pipeline and evals run offline and route
        the sample contracts sensibly, but it is NOT a substitute for a capable
        model on real contracts — it has no genuine language understanding.
        That gap is the point: swap in Claude (LLM_PROVIDER=anthropic) for
        real analysis.
        """
        low = user.lower()
        sys_low = system.lower()

        if "classify" in sys_low:
            is_nda = "non-disclosure agreement" in low or "mutual non-disclosure" in low
            is_order = "order form" in low or ("invoice" in low and "supplier" in low)
            ctype = "mutual_nda" if is_nda else ("order_form" if is_order else "unknown")
            return LLMResponse(text=json.dumps({
                "contract_type": ctype,
                "confidence": 0.9 if ctype != "unknown" else 0.3,
                "reasoning": "stubbed keyword match",
            }))

        if "extract" in sys_low:
            terms = {}
            terms["governing_law"] = ("Germany" if "laws of germany" in low
                                      else "England and Wales" if "england" in low
                                      else "not specified")
            terms["liability_cap"] = ("unlimited/uncapped" if "uncapped" in low or "unlimited" in low
                                      else "12 months fees" if "fees paid in the twelve" in low
                                      else "not specified")
            terms["term"] = ("perpetual" if "perpetuity" in low or "never expire" in low
                             else "3 years" if "three (3) years" in low
                             else "12 months" if "twelve (12) months" in low
                             else "not specified")
            return LLMResponse(text=json.dumps(terms))

        # clause comparison: decide matches/deviates from the excerpt + standard
        if "compare one clause" in sys_low:
            status = "matches"
            if "liability" in low and ("uncapped" in low or "unlimited" in low):
                status = "deviates"
            elif "perpetuity" in low or "never expire" in low or "laws of germany" in low:
                status = "deviates"
            elif "any and all purposes" in low or "any purposes" in low:
                status = "deviates"
            elif "customer claims ownership" in low:
                status = "deviates"
            else:
                # matches only when the contract wording aligns with the standard
                status = "matches"
            return LLMResponse(text=json.dumps({
                "status": status, "found": "see excerpt", "explanation": "stubbed"
            }))

        return LLMResponse(text=json.dumps({"note": "stub"}))


def _extract_json(text: str) -> dict:
    """Pull the first well-formed JSON object out of a model response."""
    # strip code fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    # find the first balanced-looking object
    start = candidate.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in model output: {text[:200]!r}")
    depth = 0
    for i in range(start, len(candidate)):
        if candidate[i] == "{":
            depth += 1
        elif candidate[i] == "}":
            depth -= 1
            if depth == 0:
                blob = candidate[start:i + 1]
                return json.loads(blob)
    raise ValueError(f"Unbalanced JSON in model output: {text[:200]!r}")


def get_provider(name: str | None = None, **kwargs) -> LLMProvider:
    """Factory: pick a backend by name (defaults to env or stub)."""
    name = name or os.environ.get("LLM_PROVIDER", "stub")
    name = name.lower()
    if name == "anthropic":
        return AnthropicProvider(**kwargs)
    if name == "local":
        return LocalGGUFProvider(**kwargs)
    if name == "stub":
        return StubProvider()
    raise ValueError(f"Unknown provider: {name}")
