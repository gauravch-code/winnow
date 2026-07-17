"""Provider factory for the tier-2 agent.

PydanticAI's ``Agent(model=...)`` already handles multi-provider dispatch
via a "provider:model" string. This wrapper adds two things:

- One place to change the default model per provider (so upgrading from
  claude-opus-4-7 to whatever ships next is a one-line change).
- Explicit handling of Ollama's local-only URL, which PydanticAI's
  string form doesn't fully cover in older versions.

The wrapper stays deliberately thin — providers are a hot area and I
don't want a heavy abstraction to maintain as the LLM landscape shifts.
"""

from __future__ import annotations

from typing import Any

# Default model per provider. Bumping any of these is a fixture-drift
# event (the fixture generator records the model in generator.model),
# so CI's check-fixtures-fresh will demand regeneration if you change it.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-7",
    "openai": "gpt-5",
    "ollama": "llama3.1:8b",
}


def resolve_model_string(provider: str, model: str | None = None) -> str:
    """Return the PydanticAI ``"provider:model"`` string for the given inputs."""
    provider = provider.strip().lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(
            f"Unknown provider {provider!r}. Supported: {sorted(DEFAULT_MODELS)}."
        )
    resolved = model or DEFAULT_MODELS[provider]
    if provider == "ollama":
        # PydanticAI reads OLLAMA_BASE_URL from env; we don't force a URL
        # here so users can point at a remote Ollama if they want.
        return f"ollama:{resolved}"
    return f"{provider}:{resolved}"


def get_model(provider: str, model: str | None = None) -> Any:
    """Return a PydanticAI model instance ready to plug into ``Agent(model=...)``.

    Kept as ``Any`` because PydanticAI's model type surface changes
    between minors and the value is opaque to callers anyway.
    """
    from pydantic_ai.models import infer_model

    return infer_model(resolve_model_string(provider, model))
