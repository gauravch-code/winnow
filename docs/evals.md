# Winnow evals

_Generated 2026-07-18T21:39:55.201410+00:00 · held-out test set: 60 emails (30% of the synthetic corpus, seed 42) · tiered threshold 0.75._

> ⚠️ **Tier-2 is stubbed in this run.** The LLM fixtures are rule-based placeholders whose lanes mirror ground truth, so the **accuracy** columns for _Pure LLM_ and _Tiered_ are not meaningful. **Latency and cost are modeled** from token counts at Claude Opus pricing. Classifier accuracy, escalation rate, and all timing/cost figures are real.

## Strategy comparison

| Strategy | Accuracy | Macro-F1 | Mean latency | p95 latency | Cost / 1000 | Escalated |
|---|---|---|---|---|---|---|
| Pure classifier (tier-1 only) | 100.0% | 1.000 | 4.6 ms | 4.6 ms | $0.0000 | 0.0% |
| Pure LLM (tier-2 only) | 100.0% | 1.000 | 1.20 s | 1.20 s | $5.3012 | 100.0% |
| Tiered (Winnow) | 100.0% | 1.000 | 5.1 ms | 5.1 ms | $0.0000 | 0.0% |

## Threshold selection

How the tiered strategy behaves as the tier-1 confidence threshold moves. Higher threshold → more emails escalate to the LLM → higher cost and latency. This is the sweep behind the default `confidence_threshold`.

| Threshold | Escalated | Accuracy | Macro-F1 | Cost / 1000 | Mean latency |
|---|---|---|---|---|---|
| 0.75 | 0.0% | 100.0% | 1.000 | $0.0000 | 5.3 ms |
| 0.99 | 0.0% | 100.0% | 1.000 | $0.0000 | 4.7 ms |
| 0.995 | 10.0% | 100.0% | 1.000 | $0.5307 | 127.2 ms |
| 0.999 | 86.7% | 100.0% | 1.000 | $4.6082 | 1.05 s |
| 0.9995 | 98.3% | 100.0% | 1.000 | $5.2088 | 1.19 s |
| 0.9999 | 100.0% | 100.0% | 1.000 | $5.3012 | 1.21 s |

## Per-lane breakdown (tiered)

| Lane | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| needs_you | 1.000 | 1.000 | 1.000 | 11 |
| informational | 1.000 | 1.000 | 1.000 | 37 |
| hidden | 1.000 | 1.000 | 1.000 | 12 |

## Notes

- Classifier accuracy, all latencies, cost modeling, and escalation rate are measured on a held-out 30% of the synthetic corpus.
- The synthetic corpus is intentionally clean and near-separable so the demo reads clearly; a real inbox is harder and tier-1 accuracy would be lower.
- Tier-1 confidences saturate near 1.0 on this near-separable data (logistic regression pushes separable classes to the extremes), so the default 0.75 threshold escalates nothing — Winnow correctly spends $0 on the LLM when the classifier is sure. Escalation only turns on above ~0.99; the sweep below uses thresholds in that range to make the tradeoff visible. On a real inbox, confidences spread out and the threshold does meaningful work at more ordinary values.
- TIER-2 IS STUBBED: the LLM fixtures used here are rule-based placeholders whose lanes mirror ground truth, so pure_llm and tiered ACCURACY are not meaningful. Latency and cost are modeled from token counts at Claude Opus pricing. Run packages/seed-data/generate.py with a real API key to publish genuine LLM accuracy.

_Regenerate with `winnow eval`. Numbers are reproducible from the seeded split._
