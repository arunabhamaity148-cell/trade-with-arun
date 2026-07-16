# Telegram Signal Format Upgrade

## Before

```text
🟢 BTCUSDT • 1h • TREND_UP
LONG (confidence bar)
Entry zone, targets, invalidation, rationale, factor dump
⚠️ Signal only — no orders are placed.
```

## After

```text
🟢 BTCUSDT · 1h · 🟢 TREND_UP
Bias LONG   Confidence ███████░░░ 0.72 (72.0%)

Entry zone 29900 → 30100
TP1 30600   TP2 31200   TP3 31800
Invalidation / SL 29400
Expected edge (bps) +7.0
News dampening 1.00

Why now
• Regime trend_up (regime confidence 0.72).
• Score +0.201 → confidence 0.72.

Top factors
📈 trend_strength_48 n +0.70 · w +0.30 · c +0.210

⚠️ Signal only — no orders are placed.
Signal ID abc123   Expiry 2026-07-16 09:30 UTC
```

## Notes

- TP1 / TP2 / TP3 map directly to `SignalIdea.targets[0:3]`.
- Regime emojis are derived from `RegimeLabel` values.
- The confidence bar uses the raw confidence float without cosmetic inflation.
- Dynamic values are escaped for Telegram Markdown so formatting stays stable.
- The compliance disclaimer remains permanently present.
