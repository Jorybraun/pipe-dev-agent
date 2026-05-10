"""Token budget tracking for developer agents."""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage


WARN_THRESHOLD = 120_000
FORCE_THRESHOLD = 140_000
RESERVE_HANDOFF = 20_000


class TokenBudget:
    """Tracks cumulative input tokens for a single ephemeral developer.

    Warns at 120K, forces handoff at 140K (reserving 20K for the handoff write).
    """

    def __init__(self, limit: int = FORCE_THRESHOLD) -> None:
        self.used: int = 0
        self.limit: int = limit
        self.warned: bool = False

    def add_turn(self, messages: list[BaseMessage]) -> dict[str, Any]:
        """Count tokens from the latest turn and return status."""
        turn_tokens = 0
        for msg in messages:
            if isinstance(msg, AIMessage):
                meta = msg.usage_metadata or {}
                turn_tokens += meta.get("input_tokens", 0) or meta.get("prompt_tokens", 0)
            else:
                # Rough approximation for non-AI messages: ~4 chars per token
                turn_tokens += len(msg.content) // 4 if isinstance(msg.content, str) else 0

        self.used += turn_tokens
        status = "ok"
        if self.used >= self.limit - RESERVE_HANDOFF and not self.warned:
            self.warned = True
            status = "warn"
        if self.used >= self.limit:
            status = "exhausted"

        return {
            "turn_tokens": turn_tokens,
            "cumulative": self.used,
            "remaining": max(0, self.limit - self.used),
            "status": status,
            "message": self._message(status),
        }

    def _message(self, status: str) -> str:
        if status == "warn":
            return (
                f"TOKEN WARNING: {self.used} / {self.limit} tokens used. "
                f"You have ~{self.limit - self.used} tokens left. "
                f"Start wrapping up and prepare your Handoff."
            )
        if status == "exhausted":
            return (
                f"TOKEN LIMIT REACHED: {self.used} / {self.limit} tokens. "
                f"You MUST exit now via submit_handoff with status=context_exhausted."
            )
        return f"Token budget: {self.used} / {self.limit} used."

    def reset(self) -> None:
        self.used = 0
        self.warned = False
