"""_configure_live_tier2: the WINNOW_LLM_API_KEY → provider env bridge.

PydanticAI reads OPENAI_API_KEY / ANTHROPIC_API_KEY from os.environ, not
our WINNOW_LLM_API_KEY. This test locks the bridge that copies the key
into the right standard var — without it, tier-2 would be validated at
boot but silently never authenticated.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import winnow_api.main as main_mod


def _app() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


def _settings(**over):
    base = dict(llm_api_key="sk-test-123", llm_provider="openai", llm_model="gpt-4o-mini")
    base.update(over)
    return SimpleNamespace(**base)


def test_bridges_openai_key_and_builds_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    sentinel_model = object()
    built = {}

    monkeypatch.setattr(
        "winnow_api.agents.provider.get_model",
        lambda provider, model: sentinel_model,
    )
    monkeypatch.setattr(
        "winnow_api.agents.live_provider.LiveAgentProvider",
        lambda model: built.setdefault("provider", SimpleNamespace(model=model)),
    )

    app = _app()
    main_mod._configure_live_tier2(app, _settings())

    assert os.environ["OPENAI_API_KEY"] == "sk-test-123"
    assert app.state.tier_2_provider is built["provider"]
    assert app.state.tier_2_provider.model is sentinel_model


def test_anthropic_key_bridged_to_its_var(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("winnow_api.agents.provider.get_model", lambda p, m: object())
    monkeypatch.setattr(
        "winnow_api.agents.live_provider.LiveAgentProvider", lambda model: object()
    )

    app = _app()
    main_mod._configure_live_tier2(app, _settings(llm_provider="anthropic"))
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test-123"


def test_no_key_leaves_tier2_unconfigured(monkeypatch):
    app = _app()
    main_mod._configure_live_tier2(app, _settings(llm_api_key=None))
    assert app.state.tier_2_provider is None


def test_does_not_clobber_existing_env_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-preexisting")
    monkeypatch.setattr("winnow_api.agents.provider.get_model", lambda p, m: object())
    monkeypatch.setattr(
        "winnow_api.agents.live_provider.LiveAgentProvider", lambda model: object()
    )
    app = _app()
    main_mod._configure_live_tier2(app, _settings())
    # An explicitly-set OPENAI_API_KEY wins over the bridge.
    assert os.environ["OPENAI_API_KEY"] == "sk-preexisting"
