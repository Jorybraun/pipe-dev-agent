"""Model factory — pluggable LLM configuration."""
from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI


def default_model_factory() -> Any:
    """Create a ChatOpenAI model from environment variables.

    Env vars:
        OPENAI_API_KEY or KIMI_API_KEY — API key
        DEV_MODEL or OPENAI_MODEL — model name (default: gpt-4o)
        DEV_BASE_URL or OPENAI_BASE_URL — base URL
        DEV_TEMPERATURE — temperature (default: 0.2)
        DEV_MAX_TOKENS — max tokens (default: 8192)
    """
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("KIMI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set OPENAI_API_KEY or KIMI_API_KEY environment variable."
        )

    model = os.getenv("DEV_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o")
    base_url = os.getenv("DEV_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    temperature = float(os.getenv("DEV_TEMPERATURE", "0.2"))
    max_tokens = int(os.getenv("DEV_MAX_TOKENS", "8192"))

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_key": api_key,
        "timeout": 120,
        "max_retries": 2,
    }
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)


def default_summarizer_factory() -> Any:
    """Create a model for context compaction / summarization.

    Uses the same env vars as default_model_factory, but can be overridden
    with SUMMARIZER_MODEL, SUMMARIZER_MAX_TOKENS, etc.
    """
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("KIMI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set OPENAI_API_KEY or KIMI_API_KEY environment variable."
        )

    model = (
        os.getenv("SUMMARIZER_MODEL")
        or os.getenv("DEV_MODEL")
        or os.getenv("OPENAI_MODEL", "gpt-4o")
    )
    base_url = os.getenv("DEV_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    temperature = float(os.getenv("SUMMARIZER_TEMPERATURE", "0.1"))
    max_tokens = int(os.getenv("SUMMARIZER_MAX_TOKENS", "4096"))

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_key": api_key,
        "timeout": 120,
        "max_retries": 2,
    }
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)
