#!/usr/bin/env python3
"""Provider facade for Smiteless' optional local LLM CLIs."""

import claudecli
import codexcli


PROVIDERS = ("claude", "codex")
LABELS = {"claude": "Claude", "codex": "Codex"}


def normalize_provider(provider):
    value = str(provider or "").strip().lower()
    return value if value in PROVIDERS else "claude"


def provider_label(provider):
    return LABELS[normalize_provider(provider)]


def find(provider):
    provider = normalize_provider(provider)
    if provider == "codex":
        return codexcli.find_codex()
    return claudecli.find_claude()


def availability():
    return {provider: find(provider) for provider in PROVIDERS}


def call(prompt, provider, allow_web=False, timeout=None, model=None,
         cancel_handle=None):
    """Call only the selected provider; provider failures never trigger failover."""
    provider = normalize_provider(provider)
    if provider == "codex":
        return codexcli.call_codex(
            prompt, timeout=timeout, model=model, allow_web=allow_web,
            cancel_handle=cancel_handle,
        )
    tools = "WebSearch,WebFetch" if allow_web else None
    return claudecli.call_claude(
        prompt, allow_tools=tools, timeout=timeout, model=model,
        cancel_handle=cancel_handle,
    )
