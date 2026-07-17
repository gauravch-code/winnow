"""Generate real tier-2 LLM fixtures for the demo.

Costs money — this is the script the repo owner runs locally with their
own API key. Every fixture it writes represents one live PydanticAI
call, and the aggregate cost is stamped on the marketing site as the
demo's "would have been $X.XX to serve live" figure.

For local dev / CI, use ``generate_stub_fixtures.py`` instead — that
one is deterministic, offline, and produces fixtures marked
``provider='stub'`` so nobody mistakes them for real LLM output.

Usage:
    export WINNOW_LLM_API_KEY=sk-ant-...
    uv run python packages/seed-data/generate.py [--only seed_001,seed_042]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Real script depends on winnow_api for the agent + prompts. This is a
# build-time script, not a runtime library, so the layered dep is fine.
from winnow_api.agents.prompts import prompt_hash
from winnow_api.agents.provider import DEFAULT_MODELS, resolve_model_string
from winnow_api.agents.triage_agent import (
    AGENT_VERSION,
    build_triage_agent,
    render_email_for_agent,
)
from winnow_seed_data.fixture_schema import (
    AgentStep,
    DraftReply,
    FixtureResponse,
    GeneratorInfo,
    PlaybackHints,
    TokenUsage,
    TraceInfo,
    TriageDecisionFixture,
    TriageSignal,
)
from winnow_seed_data.hashes import seed_email_hash
from winnow_seed_data.seed_email_schema import SeedEmail

SEED_DIR = Path(__file__).parent / "emails"
OUT_DIR = Path(__file__).parent / "llm-responses"


def _load_seeds(only: set[str] | None) -> list[SeedEmail]:
    seeds = [
        SeedEmail.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(SEED_DIR.glob("seed_*.json"))
    ]
    if only:
        seeds = [s for s in seeds if s.id in only]
    return seeds


async def _generate_one(agent, seed: SeedEmail, provider: str, model: str) -> FixtureResponse:
    prompt = render_email_for_agent(
        sender_email=seed.sender_email,
        sender_name=seed.sender_name,
        subject=seed.subject,
        body_text=seed.body_text,
        received_at_iso=seed.received_at.isoformat(),
        thread_depth=seed.thread_depth,
        has_unsubscribe=seed.has_unsubscribe,
        is_reply=seed.is_reply,
        # Fixtures are generated fresh — no tier-1 confidence to pass in.
        tier1_lane=None,
        tier1_confidence=None,
    )
    started = time.perf_counter()
    result = await agent.run(prompt)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    out = result.output

    usage = result.usage()
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0

    fixture = FixtureResponse(
        schema_version="1",
        seed_email_id=seed.id,
        generated_at=datetime.now(timezone.utc),
        generator=GeneratorInfo(
            provider=provider,
            model=model,
            agent_version=AGENT_VERSION,
            prompt_hash=prompt_hash(),
            seed_email_hash=seed_email_hash(seed),
        ),
        triage=TriageDecisionFixture(
            lane=out.lane,
            confidence=out.confidence,
            reasoning=out.reasoning,
            signals=[TriageSignal(name=s.name, weight=s.weight) for s in out.signals],
        ),
        draft_reply=DraftReply(
            included=out.draft_reply.included,
            subject=out.draft_reply.subject,
            body_markdown=out.draft_reply.body_markdown,
            tone=out.draft_reply.tone,
            assumptions=list(out.draft_reply.assumptions),
        ),
        trace=TraceInfo(
            agent_steps=[
                AgentStep(
                    step=1,
                    tool=None,
                    thought="single-shot structured output",
                    output_snippet=out.reasoning[:120],
                ),
            ],
            tokens=TokenUsage(input=input_tokens, output=output_tokens),
            # Rough Claude Opus pricing; caller can override in the marketing page.
            cost_usd_at_generation=(input_tokens * 15 + output_tokens * 75) / 1_000_000,
            latency_ms_live=elapsed_ms,
        ),
        playback=PlaybackHints(),
    )
    return fixture


async def _main_async(provider: str, model: str, only: set[str] | None) -> int:
    seeds = _load_seeds(only)
    if not seeds:
        print(f"No seeds matched in {SEED_DIR}", file=sys.stderr)
        return 1

    print(f"Generating {len(seeds)} fixture(s) via {provider}:{model}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    agent = build_triage_agent(resolve_model_string(provider, model))

    total_cost = 0.0
    for i, seed in enumerate(seeds, start=1):
        try:
            fixture = await _generate_one(agent, seed, provider, model)
        except Exception as exc:  # noqa: BLE001 — one bad email must not abort the batch
            print(f"  [{i}/{len(seeds)}] {seed.id}: FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        (OUT_DIR / f"{seed.id}.json").write_text(
            fixture.model_dump_json(indent=2), encoding="utf-8"
        )
        total_cost += fixture.trace.cost_usd_at_generation
        print(f"  [{i}/{len(seeds)}] {seed.id}: {fixture.triage.lane} @ {fixture.triage.confidence:.2f}")

    print(f"\nTotal cost: ${total_cost:.4f}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate real tier-2 LLM fixtures.")
    parser.add_argument(
        "--provider", default="anthropic", choices=list(DEFAULT_MODELS.keys()),
    )
    parser.add_argument("--model", default=None, help="Override default model for the provider.")
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated seed ids to regenerate; default is all.",
    )
    args = parser.parse_args()

    model = args.model or DEFAULT_MODELS[args.provider]
    only = set(args.only.split(",")) if args.only else None
    sys.exit(asyncio.run(_main_async(args.provider, model, only)))


if __name__ == "__main__":
    main()
