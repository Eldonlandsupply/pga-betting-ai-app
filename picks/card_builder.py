"""
picks/card_builder.py
---------------------
Formats raw picks into a clean, publishable weekly betting card.

Two output formats:
1. Structured dict (for downstream UI, audit, and API use)
2. Markdown report (for human consumption and the report system)

The card has a fixed structure so every week's output is comparable
and auditable. Order within categories is always by edge descending.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

MARKET_LABELS = {
    "outright":  "Win",
    "top_5":     "Top 5",
    "top_10":    "Top 10",
    "top_20":    "Top 20",
    "make_cut":  "Make Cut",
    "miss_cut":  "Miss Cut",
    "h2h":       "H2H Matchup",
    "frl":       "First Round Leader",
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def build_betting_card(raw_picks: dict) -> dict:
    """
    Build a structured betting card from raw picks.

    Returns structured card ready for adversarial review and reporting.
    """
    card = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "safe_bets":         _format_category(raw_picks.get("safe_bets", [])),
        "value_bets":        _format_category(raw_picks.get("value_bets", [])),
        "upside_outrights":  _format_category(raw_picks.get("upside_outrights", [])),
        "matchup_bets":      _format_category(raw_picks.get("matchup_bets", [])),
        "placement_bets":    _format_category(raw_picks.get("placement_bets", [])),
        "longshot_bets":     _format_category(raw_picks.get("longshot_bets", [])),
        "avoid_list":        raw_picks.get("avoid_list", []),
        "total_candidates":  sum(
            len(raw_picks.get(k, []))
            for k in ("safe_bets","value_bets","upside_outrights",
                      "matchup_bets","placement_bets","longshot_bets")
        ),
    }
    return card


def build_markdown_card(event_id: str, reviewed_card: dict) -> str:
    """
    Render the final reviewed betting card as a Markdown document.
    This is the human-readable output published weekly.
    """
    lines = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines += [
        f"# Weekly Betting Card — {event_id}",
        f"*Generated: {ts}*",
        "",
        "---",
        "",
    ]

    # Adversarial summary
    adv = reviewed_card.get("adversarial_summary", {})
    if adv:
        lines += [
            "## Adversarial Review Summary",
            f"- ✅ Passed: **{adv.get('passed', 0)}** picks",
            f"- ↓ Downgraded: **{adv.get('downgraded', 0)}** picks",
            f"- ✗ Killed: **{adv.get('killed', 0)}** picks",
        ]
        concerns = adv.get("top_concerns_this_week", [])
        if concerns:
            lines.append("- Top concerns this week:")
            for c in concerns:
                lines.append(f"  - `{c['flag']}` ({c['occurrences']}x): {c['description']}")
        lines += ["", "---", ""]

    # Each pick category
    categories = [
        ("safe_bets",        "🟢 Safe Bets",           "High confidence, accessible prices"),
        ("value_bets",       "💰 Value Bets",          "Strong edge at various price points"),
        ("upside_outrights", "🏆 Outright Value",      "Win bets with genuine model edge"),
        ("matchup_bets",     "⚔️  H2H Matchups",       "Head-to-head picks ranked by edge"),
        ("placement_bets",   "📊 Placement Bets",      "Top 5/10/20 value plays"),
        ("longshot_bets",    "🎯 Longshot Value",       "30/1+ plays with edge — small stakes"),
    ]

    for key, title, subtitle in categories:
        picks = reviewed_card.get(key) or reviewed_card.get("reviewed_picks", [])
        # Filter to this category if we're using reviewed_picks
        if key != "reviewed_picks":
            picks = reviewed_card.get(key, [])

        if not picks:
            continue

        lines += [f"## {title}", f"*{subtitle}*", ""]
        lines += [
            "| Player | Market | Price | Model% | Implied% | Edge | Stake | Confidence | Sharp |",
            "|--------|--------|------:|-------:|---------:|-----:|------:|------------|-------|",
        ]

        for p in picks:
            player  = p.get("player_name") or p.get("player_id", "?")
            market  = MARKET_LABELS.get(p.get("market_type", ""), p.get("market_type", ""))
            price   = f"{p.get('price', 0):.2f}"
            model_p = f"{p.get('model_probability',0)*100:.1f}%"
            imp_p   = f"{p.get('implied_probability',0)*100:.1f}%"
            edge    = f"+{p.get('edge_pct',0):.1f}%"
            stake   = f"{p.get('stake_units',0)*100:.1f}%"
            conf    = p.get("confidence_tier", "").replace("tier_", "T")
            sharp   = "⚡" if p.get("sharp_signal") else "—"
            book    = p.get("book", "")
            lines.append(f"| {player} | {market} @ {book} | {price} | {model_p} | {imp_p} | {edge} | {stake} | {conf} | {sharp} |")

        lines.append("")

        # Reasons and flags for each pick
        for p in picks:
            player  = p.get("player_name") or p.get("player_id", "?")
            market  = MARKET_LABELS.get(p.get("market_type", ""), "")
            reasons = p.get("supporting_reasons", [])
            flags   = p.get("risk_flags", [])
            challenges = p.get("adversarial_challenges", [])

            if reasons or flags or challenges:
                lines.append(f"**{player} ({market})**")
                for r in reasons:
                    lines.append(f"- ✓ {r}")
                for f in flags:
                    lines.append(f"- ⚠ `{f}`")
                for ch in challenges:
                    lines.append(f"- 🔶 {ch.get('flag')}: {ch.get('detail', '')}")
                lines.append("")

        lines += ["---", ""]

    # Avoid list
    avoid = reviewed_card.get("avoid_list", [])
    if avoid:
        lines += ["## 🚫 Avoid / Trap List", ""]
        lines += [
            "| Player | Market | Best Price | Model% | Overvalued By | Reason |",
            "|--------|--------|----------:|-------:|:-------------:|--------|",
        ]
        for a in avoid[:8]:
            player = a.get("player_name") or a.get("player_id", "?")
            market = MARKET_LABELS.get(a.get("market_type", ""), "")
            price  = f"{a.get('best_price',0):.2f}"
            model_p = f"{a.get('model_probability',0)*100:.1f}%"
            over   = f"{a.get('overvaluation_pct',0):.0f}%"
            reason = a.get("avoid_reason", "")[:60]
            lines.append(f"| {player} | {market} | {price} | {model_p} | +{over} | {reason} |")
        lines.append("")

    # Correlated stacks warning
    corr = reviewed_card.get("correlated_pairs", [])
    if corr:
        lines += ["## ⚠️ Correlated Exposure Warnings", ""]
        for pair in corr:
            lines.append(
                f"- **{pair.get('player_id')}** appears in {pair.get('markets')} — "
                f"{pair.get('recommendation', 'review combined exposure')}"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## Model Notes",
        "",
        "- All probabilities are model output before calibration to closing line.",
        "- Edge is calculated vs hold-adjusted implied probability (5% hold assumed).",
        "- Stake % is of total bankroll. Never exceed combined weekly exposure limit.",
        "- Sharp signal (⚡) indicates Pinnacle/Circa moved differently from recreational books.",
        "- All picks have passed adversarial self-review. Attached challenges indicate residual risk.",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_category(picks: list) -> list:
    """Clean up a list of picks for card output."""
    return [_format_pick(p) for p in picks]


def _format_pick(p: dict) -> dict:
    """Return a clean, display-ready version of a pick."""
    return {
        "pick_id":           p.get("pick_id"),
        "player_id":         p.get("player_id"),
        "player_name":       p.get("player_name"),
        "tour":              p.get("tour"),
        "market_type":       p.get("market_type"),
        "price":             p.get("price"),
        "book":              p.get("book"),
        "model_probability": p.get("model_probability"),
        "implied_probability": p.get("implied_probability"),
        "edge_pct":          p.get("edge_pct"),
        "confidence_tier":   p.get("confidence_tier"),
        "stake_units":       p.get("stake_units"),
        "supporting_reasons": p.get("supporting_reasons", []),
        "risk_flags":        p.get("risk_flags", []),
        "sharp_signal":      p.get("sharp_signal", False),
        "line_movement_flag":p.get("line_movement_flag"),
        "adversarial_verdict": p.get("adversarial_verdict"),
        "adversarial_challenges": p.get("adversarial_challenges", []),
        "course_fit_score":  p.get("course_fit_score"),
        "composite_sg":      p.get("composite_sg"),
        "data_confidence":   p.get("data_confidence"),
    }
