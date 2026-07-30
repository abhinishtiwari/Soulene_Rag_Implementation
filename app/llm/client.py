"""Thin OpenAI wrapper (Responses API + moderation) with retries and timeouts.

Mirrors the behaviour of the reference project's core/client.py so the new bot
"feels" the same, but with a smaller, cleaner surface.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from app.config.settings import Settings
from app.types import ModerationSignal


class LLMError(RuntimeError):
    """Raised when an OpenAI request fails after retries."""


class LLMClient:
    """Wraps the OpenAI SDK. Accepts an injected client for testing."""

    def __init__(self, settings: Settings, client: Optional[Any] = None):
        self.settings = settings
        if client is not None:
            self._client = client
            return
        try:
            from openai import OpenAI  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'openai' package is not installed. Run: pip install openai"
            ) from exc
        self._client = OpenAI(api_key=settings.openai_api_key)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(self, *, instructions: str, input_text: str, session_id: str,
                 temperature: Optional[float] = None,
                 max_output_tokens: Optional[int] = None) -> str:
        response = self._with_retries(
            self._client.responses.create,
            model=self.settings.primary_model,
            instructions=instructions,
            input=input_text,
            temperature=self.settings.temperature if temperature is None else temperature,
            max_output_tokens=self.settings.max_output_tokens if max_output_tokens is None else max_output_tokens,
            truncation="auto",
            store=False,
            user=session_id,
        )
        return (response.output_text or "").strip()

    def generate_stream(self, *, instructions: str, input_text: str, session_id: str,
                        temperature: Optional[float] = None,
                        max_output_tokens: Optional[int] = None):
        """Yield reply text deltas as they arrive from the Responses API.

        Falls back to yielding the full text once if streaming is unavailable.
        """
        try:
            stream = self._client.responses.create(
                model=self.settings.primary_model,
                instructions=instructions,
                input=input_text,
                temperature=self.settings.temperature if temperature is None else temperature,
                max_output_tokens=self.settings.max_output_tokens if max_output_tokens is None else max_output_tokens,
                truncation="auto",
                store=False,
                user=session_id,
                stream=True,
            )
        except Exception:
            # Streaming not supported by this client/mock -> single chunk.
            yield self.generate(instructions=instructions, input_text=input_text,
                                session_id=session_id, temperature=temperature,
                                max_output_tokens=max_output_tokens)
            return

        for event in stream:
            etype = getattr(event, "type", "")
            if etype == "response.output_text.delta":
                delta = getattr(event, "delta", "")
                if delta:
                    yield delta
            elif etype == "response.error":
                raise LLMError(str(getattr(event, "error", "stream error")))

    # ------------------------------------------------------------------
    # Moderation
    # ------------------------------------------------------------------
    def moderate(self, text: str) -> ModerationSignal:
        try:
            result = self._with_retries(
                self._client.moderations.create,
                input=text,
                model=self.settings.moderation_model,
            )
        except Exception as exc:  # fail-open: never block on moderation failure
            return ModerationSignal(flagged=False, categories={}, error=str(exc))

        results = getattr(result, "results", None)
        if not results:
            return ModerationSignal(flagged=False, categories={})
        item = results[0]
        try:
            categories = item.categories.model_dump()
        except Exception:
            categories = dict(getattr(item, "categories", {}) or {})
        return ModerationSignal(
            flagged=bool(getattr(item, "flagged", False)),
            categories={k: bool(v) for k, v in categories.items()},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _with_retries(self, func: Callable[..., Any], **kwargs: Any) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                return func(timeout=self.settings.request_timeout_seconds, **kwargs)
            except TypeError:
                # Injected/mocked clients may not accept a timeout kwarg.
                return func(**kwargs)
            except Exception as exc:  # pragma: no cover - exercised via mocks
                last_error = exc
                if attempt >= self.settings.max_retries:
                    break
                time.sleep(0.5 * (2 ** attempt))
        raise LLMError(str(last_error) if last_error else "Unknown OpenAI error")
