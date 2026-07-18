"""The three triage strategies under comparison.

Each strategy takes the held-out test emails and returns a
``StrategyRun``: per-email predicted lane, latency, cost, plus which
tier handled each email. Downstream ``metrics.py`` turns these into the
published comparison table.

Provenance honesty:
- ``pure_classifier`` numbers are fully real (measured inference).
- ``pure_llm`` / ``tiered`` LLM figures come from the fixtures. When
  fixtures are stubs, the *lanes* mirror ground truth (so accuracy is
  not meaningful) but latency and cost are still modeled from the
  recorded token counts / timings. The caller records provenance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from winnow_api.classifier import Classifier
from winnow_api.classifier.embeddings import embed_batch
from winnow_api.classifier.features import extract_features, to_vector
from winnow_api.demo.fixtures import FixtureLoader
from winnow_seed_data.seed_email_schema import SeedEmail

# Lane the tiered/LLM strategies fall back to when an email has no
# fixture. Matches the orchestrator's "unavailable" behavior: tier-1's
# guess stands. For pure_llm we treat a missing fixture as an abstention
# scored against ground truth (counts as whatever the fixture would have
# said — here we fall back to informational, the modal lane, and flag it).
_NO_FIXTURE_FALLBACK = "informational"


@dataclass
class EmailOutcome:
    seed_email_id: str
    true_lane: str
    pred_lane: str
    tier: int  # 1 or 2
    latency_ms: float
    cost_usd: float
    escalated: bool = False
    had_fixture: bool = True


@dataclass
class StrategyRun:
    name: str
    outcomes: list[EmailOutcome] = field(default_factory=list)

    @property
    def y_true(self) -> list[str]:
        return [o.true_lane for o in self.outcomes]

    @property
    def y_pred(self) -> list[str]:
        return [o.pred_lane for o in self.outcomes]


def _classify_batch(
    classifier: Classifier, emails: list[SeedEmail]
) -> tuple[list[str], list[float], float]:
    """Return (pred_lanes, confidences, total_wall_ms) for a batch.

    Timed as a batch (one embed pass + one predict) because that's how
    tier-1 actually runs in production; per-email latency is the batch
    time amortized, which is the honest per-email cost under batching.
    """
    started = time.perf_counter()
    engineered = np.asarray(
        [to_vector(extract_features(e)) for e in emails], dtype=np.float32
    )
    embeddings = embed_batch([(e.subject, e.body_text) for e in emails])
    X = np.hstack([engineered, embeddings])
    scaler = classifier.model.pipeline.named_steps["scaler"]
    clf = classifier.model.pipeline.named_steps["clf"]
    probs = clf.predict_proba(scaler.transform(X))
    total_ms = (time.perf_counter() - started) * 1000.0

    classes = list(clf.classes_)
    preds = [classes[int(np.argmax(row))] for row in probs]
    confs = [float(np.max(row)) for row in probs]
    return preds, confs, total_ms


def pure_classifier(classifier: Classifier, emails: list[SeedEmail]) -> StrategyRun:
    """Tier-1 only. Cost $0, latency = amortized batch inference."""
    preds, _confs, total_ms = _classify_batch(classifier, emails)
    per_email_ms = total_ms / max(1, len(emails))
    run = StrategyRun(name="pure_classifier")
    for email, pred in zip(emails, preds):
        run.outcomes.append(
            EmailOutcome(
                seed_email_id=email.id,
                true_lane=email.ground_truth_lane,
                pred_lane=pred,
                tier=1,
                latency_ms=per_email_ms,
                cost_usd=0.0,
            )
        )
    return run


def pure_llm(loader: FixtureLoader, emails: list[SeedEmail]) -> StrategyRun:
    """Every email goes to the LLM tier (fixtures). No classifier."""
    run = StrategyRun(name="pure_llm")
    for email in emails:
        fixture = loader.get(email.id)
        if fixture is None:
            run.outcomes.append(
                EmailOutcome(
                    seed_email_id=email.id,
                    true_lane=email.ground_truth_lane,
                    pred_lane=_NO_FIXTURE_FALLBACK,
                    tier=2,
                    latency_ms=0.0,
                    cost_usd=0.0,
                    had_fixture=False,
                )
            )
            continue
        run.outcomes.append(
            EmailOutcome(
                seed_email_id=email.id,
                true_lane=email.ground_truth_lane,
                pred_lane=fixture.triage.lane,
                tier=2,
                latency_ms=float(fixture.trace.latency_ms_live),
                cost_usd=float(fixture.trace.cost_usd_at_generation),
            )
        )
    return run


def tiered(
    classifier: Classifier,
    loader: FixtureLoader,
    emails: list[SeedEmail],
    threshold: float,
) -> StrategyRun:
    """Tier-1 first; escalate to the LLM only when confidence < threshold.

    Latency for an escalated email is tier-1 + tier-2 (the classifier
    still runs before we decide to escalate). Cost is only incurred on
    escalation. This is the core value proposition the eval quantifies.
    """
    preds, confs, total_ms = _classify_batch(classifier, emails)
    per_email_ms = total_ms / max(1, len(emails))

    run = StrategyRun(name="tiered")
    for email, pred, conf in zip(emails, preds, confs):
        if conf >= threshold:
            run.outcomes.append(
                EmailOutcome(
                    seed_email_id=email.id,
                    true_lane=email.ground_truth_lane,
                    pred_lane=pred,
                    tier=1,
                    latency_ms=per_email_ms,
                    cost_usd=0.0,
                    escalated=False,
                )
            )
            continue

        fixture = loader.get(email.id)
        if fixture is None:
            # No fixture to escalate to — tier-1's guess stands, no cost.
            run.outcomes.append(
                EmailOutcome(
                    seed_email_id=email.id,
                    true_lane=email.ground_truth_lane,
                    pred_lane=pred,
                    tier=1,
                    latency_ms=per_email_ms,
                    cost_usd=0.0,
                    escalated=True,
                    had_fixture=False,
                )
            )
            continue
        run.outcomes.append(
            EmailOutcome(
                seed_email_id=email.id,
                true_lane=email.ground_truth_lane,
                pred_lane=fixture.triage.lane,
                tier=2,
                latency_ms=per_email_ms + float(fixture.trace.latency_ms_live),
                cost_usd=float(fixture.trace.cost_usd_at_generation),
                escalated=True,
            )
        )
    return run
