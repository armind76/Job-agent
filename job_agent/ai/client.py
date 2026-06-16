"""Anthropic API wrapper with retry logic and token cost logging."""
import time
from typing import Optional

import anthropic

from config.settings import settings

# Approximate cost per token (claude-sonnet-4-6, June 2025)
_INPUT_COST_PER_MTOK = 3.0   # $ per million input tokens
_OUTPUT_COST_PER_MTOK = 15.0  # $ per million output tokens

_session_input_tokens = 0
_session_output_tokens = 0


def session_cost() -> float:
    """Return approximate USD cost for this session."""
    return (
        _session_input_tokens / 1_000_000 * _INPUT_COST_PER_MTOK
        + _session_output_tokens / 1_000_000 * _OUTPUT_COST_PER_MTOK
    )


def session_token_counts() -> dict:
    return {
        "input": _session_input_tokens,
        "output": _session_output_tokens,
        "cost_usd": round(session_cost(), 4),
    }


class AIClient:
    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or settings.claude_model
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        retries: int = 3,
    ) -> str:
        """
        Send a completion request to Claude and return the text response.
        Retries on rate limit errors with exponential backoff.
        """
        global _session_input_tokens, _session_output_tokens

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        for attempt in range(retries):
            try:
                response = self._client.messages.create(**kwargs)
                _session_input_tokens += response.usage.input_tokens
                _session_output_tokens += response.usage.output_tokens
                return response.content[0].text
            except anthropic.RateLimitError:
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise
            except anthropic.APIError as e:
                if attempt < retries - 1:
                    time.sleep(2)
                else:
                    raise RuntimeError(f"Claude API error: {e}") from e

        raise RuntimeError("Max retries exceeded")
