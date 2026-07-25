# TripPlanner M3 Evaluation Report

Generated: 2026-07-25

Gate M3: PASS

## Summary

- Anchor ordering: anchor_good > anchor_scattered > anchor_overpacked
- Golden itineraries: 8
- Judge runs per golden itinerary: 3
- Overall mean: 4.20
- Latency: p50 0 ms, p95 0 ms
- Prompt tokens: 5508
- Completion tokens: 648
- Total tokens: 6156

## Dimension means

| Dimension | Mean |
|---|---:|
| groundedness | 5.00 |
| interest_match | 4.00 |
| geographic_coherence | 4.00 |
| pacing | 4.00 |
| budget_respect | 4.00 |

## Gate failures

- None

## Limitations

- Uses an offline scripted judge by default; optional live judging is disabled without explicit credentials.
- Makes no live provider calls and does not connect provider MCP servers.
- Evaluation code remains outside the product runtime; there is no runtime evaluator in `POST /plan`.
