"""Hugging Face transport with bounded retries, token accounting and a spend ceiling.

All generation calls use this boundary. The historical AnthropicClient name is
an import alias for old callers; no requests are sent to Anthropic.
"""

import contextvars
import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
from pydantic import BaseModel

from sabermetrics.errors import FatalError, LLMCostCeilingExceeded, RecoverableError

logger = logging.getLogger(__name__)
_cost_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "saber_cost_context", default=None
)


@contextmanager
def cost_attribution(user_id: str | None, deck_id: str | None) -> Iterator[None]:
    token = _cost_context.set({"user_id": user_id, "deck_id": deck_id})
    try:
        yield
    finally:
        _cost_context.reset(token)


ALLOWED_MODELS = {"deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"}
KNOWN_RETIRED_MODELS = {"deepseek-v4-flash", "claude-3-opus-20240229"}
# DeepInfra standard-tier estimates via Hugging Face, checked 2026-09-12.
# https://deepinfra.com/deepseek-ai/DeepSeek-V4-Flash-0731/api
MODEL_PRICING = {
    "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra": {
        "input": 0.06,
        "cached_input": 0.015,
        "output": 0.18,
    }
}


def validate_models() -> None:
    if (
        not ALLOWED_MODELS <= MODEL_PRICING.keys()
        or ALLOWED_MODELS & KNOWN_RETIRED_MODELS
    ):
        raise FatalError("Model allowlist and pricing are inconsistent")


def validate_configured_models(configured: dict[str, str]) -> None:
    for setting, model in configured.items():
        if model in KNOWN_RETIRED_MODELS:
            raise FatalError(
                f"Configured model '{model}' is retired; use deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
            )
        if model not in ALLOWED_MODELS:
            raise FatalError(
                f"Configured model '{model}' ({setting}) is not in ALLOWED_MODELS"
            )


validate_models()


class CallResult(BaseModel):
    content: str
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cost_usd: float
    request_id: str


class ModelClient:
    """One configured client per database; provider secrets never enter logs."""

    _instance: "ModelClient | None" = None

    def __init__(self, db_path: Path) -> None:
        from sabermetrics.config import settings

        self.db_path = Path(db_path)
        validate_configured_models(
            {
                key: getattr(settings.llm, key)
                for key in (
                    "profile_model",
                    "fit_model",
                    "synthesis_model",
                    "refresh_model",
                    "template_model",
                )
            }
        )
        key = os.environ.get("HF_TOKEN", "").strip()
        if not key:
            raise FatalError("HF_TOKEN is not configured")
        # Pin the credential origin and disable redirects to prevent token forwarding.
        self._client = httpx.Client(
            base_url="https://router.huggingface.co/v1",
            timeout=httpx.Timeout(180, connect=15),
            headers={"Authorization": "Bearer " + key},
            follow_redirects=False,
        )

    @classmethod
    def get_instance(cls, db_path: Path | None = None) -> "ModelClient":
        path = Path(db_path or "data/sabermetrics.db")
        if cls._instance is None or cls._instance.db_path.resolve() != path.resolve():
            cls.reset_instance()
            cls._instance = cls(path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        if cls._instance is not None:
            cls._instance._client.close()
        cls._instance = None

    def call_with_cache(
        self,
        model: str,
        system: str,
        messages: list[dict],
        cache_breakpoints: list[int] | None = None,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        call_type: str = "unknown",
    ) -> CallResult:
        """Return final answer text; existing callers validate their own schemas.

        DeepSeek caches matching prefixes automatically. Anthropic cache markers
        are removed without mutating the caller's messages. Non-thinking mode
        preserves the existing small completion budgets and bounds token spend.
        """
        from sabermetrics.config import settings

        validate_configured_models({"request": model})
        api_messages = [{"role": "system", "content": system}]
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, list):
                if any(block.get("type") != "text" for block in content):
                    raise FatalError(
                        "Generator model requests support text content only"
                    )
                content = "\n".join(block["text"] for block in content)
            api_messages.append(
                {"role": message.get("role", "user"), "content": content}
            )
        payload = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "reasoning_effort": "none",
        }
        for attempt in range(3):
            if self.get_monthly_spend() >= settings.llm.monthly_cost_ceiling_usd:
                raise LLMCostCeilingExceeded("Monthly model spend ceiling reached")
            try:
                response = self._client.post("/chat/completions", json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code != 429 and code < 500:
                    raise FatalError(
                        f"Hugging Face API rejected the request (HTTP {code})"
                    ) from None
            except httpx.TransportError:
                pass
            else:
                break
            if attempt == 2:
                raise RecoverableError(
                    "Hugging Face request failed after three attempts"
                )
            time.sleep(2 ** (attempt + 1))
        try:
            body = response.json()
            usage = body["usage"]
            total_input = usage["prompt_tokens"]
            cached = usage.get(
                "prompt_cache_hit_tokens",
                usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
            )
            output = usage["completion_tokens"]  # includes any billed reasoning tokens
            if (
                any(type(n) is not int or n < 0 for n in (total_input, cached, output))
                or cached > total_input
            ):
                raise ValueError("Invalid usage counters")
            choice = body["choices"][0]
            content = choice["message"].get("content")
            result = CallResult(
                content=content if isinstance(content, str) else "",
                model=model,
                input_tokens=total_input,
                cached_input_tokens=cached,
                output_tokens=output,
                cost_usd=self.estimate_cost(model, total_input, cached, output),
                request_id=body.get("id", ""),
            )
        except (ValueError, KeyError, IndexError, TypeError):
            raise FatalError(
                "Hugging Face returned a malformed response or usage record"
            ) from None
        # Even a truncated/empty answer consumed tokens. Record it before rejection.
        self._log_cost(result, call_type)
        if choice.get("finish_reason") != "stop" or not result.content.strip():
            raise RecoverableError(
                "Hugging Face returned an incomplete answer; usage was recorded"
            )
        logger.info(
            "Model call: model=%s type=%s input=%d cached=%d output=%d estimated_cost=$%.6f",
            model,
            call_type,
            total_input,
            cached,
            output,
            result.cost_usd,
        )
        return result

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
    ) -> float:
        validate_configured_models({"pricing": model})
        from sabermetrics.config import settings

        pricing = settings.llm.provider_pricing
        return round(
            (
                (input_tokens - cached_input_tokens) * pricing.input
                + cached_input_tokens * pricing.cached_input
                + output_tokens * pricing.output
            )
            / 1_000_000,
            8,
        )

    def get_monthly_spend(self) -> float:
        """Query cost_log for spend in last 30 days."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_log "
                "WHERE timestamp >= datetime('now', '-30 days')"
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def _log_cost(self, result: CallResult, call_type: str) -> None:
        """Log API call cost to the cost_log table."""
        ctx = _cost_context.get() or {}
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT INTO cost_log "
                "(call_type, model, input_tokens, cached_input_tokens, "
                "output_tokens, cost_usd, request_id, user_id, deck_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    call_type,
                    result.model,
                    result.input_tokens,
                    result.cached_input_tokens,
                    result.output_tokens,
                    result.cost_usd,
                    result.request_id,
                    ctx.get("user_id"),
                    ctx.get("deck_id"),
                ),
            )
            conn.commit()
        finally:
            conn.close()


# Compatibility for the original pipeline and third-party imports.
AnthropicClient = ModelClient
