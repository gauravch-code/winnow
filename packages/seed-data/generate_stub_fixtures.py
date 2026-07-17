"""Offline deterministic fixture generator — no LLM call, $0 cost.

Purpose: the demo needs *some* tier-2 fixtures committed to the repo so
new visitors see prerecorded responses out of the box, but the real
``generate.py`` requires an API key nobody but the repo owner has.
This script fills the gap with rule-based outputs that are:

- **Plausible** — informed by the same category + featurizer signals a
  real LLM would consider, so panel content reads like real triage.
- **Honest** — every fixture is stamped ``generator.provider='stub'``
  and ``generator.model='rule-based-stub-v1'``. The demo UI can (and
  should) display these differently from real fixtures so nobody
  mistakes them for LLM output.
- **Idempotent** — same seeds → same fixtures. CI's freshness check
  is meaningful.

When the repo owner runs the real ``generate.py``, its output
overwrites stub fixtures with real ones (same filenames).

Usage:
    uv run python packages/seed-data/generate_stub_fixtures.py [--only seed_001]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

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
from winnow_seed_data.seed_email_schema import Category, Lane, SeedEmail

SEED_DIR = Path(__file__).parent / "emails"
OUT_DIR = Path(__file__).parent / "llm-responses"

STUB_PROVIDER = "stub"
STUB_MODEL = "rule-based-stub-v1"
STUB_AGENT_VERSION = "triage-agent-stub@0.1.0"
# Placeholder prompt hash — not a real prompt, but stable across runs so
# the freshness check has something to compare against.
STUB_PROMPT_HASH = "sha256:" + "0" * 64


# Per-category rule table. Confidence, tone, and reasoning template are
# what a well-behaved LLM would produce for these categories. Signals
# are drawn from the featurizer's actual signals for interpretability
# parity with tier-1's explainability panel.
CATEGORY_RULES: dict[Category, dict] = {
    "work": {
        "confidence": 0.86,
        "reasoning_template": (
            "Work correspondence from {sender_short}. "
            "{ask_note} Tier-1 was probably fine but the LLM confirms."
        ),
        "signals": [
            ("known_sender_domain", 0.32),
            ("thread_depth_gt_1", 0.18),
            ("direct_question", 0.24),
        ],
        "draft_tone": "collegial",
    },
    "personal": {
        "confidence": 0.83,
        "reasoning_template": (
            "Personal note from {sender_short}. "
            "{ask_note} Reader would notice if this slipped through."
        ),
        "signals": [
            ("personal_domain", 0.34),
            ("direct_question", 0.29),
            ("short_body", 0.11),
        ],
        "draft_tone": "warm",
    },
    "newsletter": {
        "confidence": 0.91,
        "reasoning_template": (
            "Newsletter from {sender_short}. Subscribed content — "
            "worth existing in the inbox but does not require action."
        ),
        "signals": [
            ("has_unsubscribe", 0.42),
            ("marketing_domain", 0.27),
        ],
        "draft_tone": None,
    },
    "notification": {
        "confidence": 0.88,
        "reasoning_template": (
            "Automated notification from {sender_short}. "
            "Reader already sees this activity in the source app."
        ),
        "signals": [
            ("notification_service_domain", 0.38),
            ("automated_sender", 0.24),
        ],
        "draft_tone": None,
    },
    "calendar": {
        "confidence": 0.9,
        "reasoning_template": (
            "Calendar notification. Reader isn't the organizer; "
            "no action needed beyond the calendar itself."
        ),
        "signals": [
            ("calendar_service", 0.36),
            ("automated_sender", 0.22),
        ],
        "draft_tone": None,
    },
    "receipt": {
        "confidence": 0.94,
        "reasoning_template": (
            "Receipt from {sender_short}. Filed for records, not action."
        ),
        "signals": [
            ("receipt_service_domain", 0.44),
            ("has_unsubscribe", 0.16),
        ],
        "draft_tone": None,
    },
    "spam": {
        "confidence": 0.96,
        "reasoning_template": (
            "Unsolicited message from {sender_short}. "
            "Suspicious pattern (unfamiliar sender, urgency framing, "
            "or off-TLD). Safe to hide."
        ),
        "signals": [
            ("suspicious_tld", 0.41),
            ("urgency_words", 0.28),
            ("unknown_sender", 0.19),
        ],
        "draft_tone": None,
    },
}


def _sender_short(seed: SeedEmail) -> str:
    return seed.sender_name or seed.sender_email.split("@")[0]


def _ask_note(seed: SeedEmail) -> str:
    if "?" in seed.subject or "?" in seed.body_text:
        return "Contains a direct ask."
    if seed.is_reply:
        return "Continues an existing thread."
    return "One-off message."


def _stub_output(seed: SeedEmail) -> tuple[TriageDecisionFixture, DraftReply, int, int]:
    rules = CATEGORY_RULES[seed.category]
    lane: Lane = seed.ground_truth_lane

    reasoning = rules["reasoning_template"].format(
        sender_short=_sender_short(seed),
        ask_note=_ask_note(seed),
    )
    signals = [TriageSignal(name=n, weight=w) for n, w in rules["signals"]]

    draft_included = (
        lane == "needs_you"
        and ("?" in seed.subject or "?" in seed.body_text)
    )
    if draft_included:
        draft = DraftReply(
            included=True,
            subject=f"Re: {seed.subject}",
            body_markdown=(
                f"Hi {_sender_short(seed).split()[0]},\n\n"
                "Thanks for the note — I'll take a look and get back to you.\n\n"
                "Best,\nMe"
            ),
            tone=rules["draft_tone"],
            assumptions=["User can respond to this specific request without more context"],
        )
    else:
        draft = DraftReply(included=False)

    # Rough token estimate for the trace — good enough for demo cost display.
    est_input_tokens = 60 + len(seed.subject.split()) + len(seed.body_text.split())
    est_output_tokens = 40 + len(reasoning.split())
    return (
        TriageDecisionFixture(
            lane=lane,
            confidence=rules["confidence"],
            reasoning=reasoning,
            signals=signals,
        ),
        draft,
        est_input_tokens,
        est_output_tokens,
    )


def _build_fixture(seed: SeedEmail) -> FixtureResponse:
    triage, draft, in_toks, out_toks = _stub_output(seed)
    return FixtureResponse(
        schema_version="1",
        seed_email_id=seed.id,
        # Fixed timestamp so re-runs produce identical bytes.
        generated_at=datetime(2026, 7, 16, 0, 0, 0, tzinfo=timezone.utc),
        generator=GeneratorInfo(
            provider=STUB_PROVIDER,
            model=STUB_MODEL,
            agent_version=STUB_AGENT_VERSION,
            prompt_hash=STUB_PROMPT_HASH,
            seed_email_hash=seed_email_hash(seed),
        ),
        triage=triage,
        draft_reply=draft,
        trace=TraceInfo(
            agent_steps=[
                AgentStep(
                    step=1,
                    tool=None,
                    thought=f"stub: category={seed.category}, lane={triage.lane}",
                    output_snippet=triage.reasoning[:120],
                ),
            ],
            tokens=TokenUsage(input=in_toks, output=out_toks),
            # Simulated cost — what the real Opus call would have cost.
            cost_usd_at_generation=(in_toks * 15 + out_toks * 75) / 1_000_000,
            latency_ms_live=1200,
        ),
        playback=PlaybackHints(
            simulated_latency_ms_range=(1000, 1500),
            stream_chunks=None,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate offline stub fixtures.")
    parser.add_argument("--only", default=None, help="Comma-separated seed ids; default is all.")
    args = parser.parse_args()

    only: set[str] | None = set(args.only.split(",")) if args.only else None

    seeds = [
        SeedEmail.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(SEED_DIR.glob("seed_*.json"))
    ]
    if only:
        seeds = [s for s in seeds if s.id in only]
    if not seeds:
        print(f"No seeds matched in {SEED_DIR}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        fixture = _build_fixture(seed)
        (OUT_DIR / f"{seed.id}.json").write_text(
            fixture.model_dump_json(indent=2), encoding="utf-8"
        )

    by_lane: dict[str, int] = {}
    for seed in seeds:
        by_lane[seed.ground_truth_lane] = by_lane.get(seed.ground_truth_lane, 0) + 1
    print(f"Wrote {len(seeds)} stub fixtures to {OUT_DIR}")
    print(f"  by lane: {by_lane}")


if __name__ == "__main__":
    main()
