"""reports/post_event_report.py"""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from pathlib import Path
log = logging.getLogger(__name__)

def publish_post_event_report(event_id: str, audit_output: dict, weight_changes) -> Path:
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"post_event_audit_{event_id}_{ts}.md"

    m = audit_output.get("metrics", {})
    lines = [
        f"# Post-Event Audit — {event_id}",
        f"*{ts}*", "",
        "## Performance",
        f"- Picks: {m.get('total_picks')} | Settled: {m.get('settled_picks')}",
        f"- ROI: **{m.get('realized_roi_pct')}%** | Hit Rate: **{m.get('hit_rate_pct')}%**",
        f"- Avg CLV: {m.get('avg_clv')} | Model Right: {m.get('model_right_pct')}%",
        f"- EV Expected: {m.get('total_ev_expected')} | Luck Factor: {m.get('ev_luck_factor')}",
        "", "## Failures",
    ]
    for f in audit_output.get("failures", []):
        lines.append(f"- {f.get('player_id')} | {f.get('market_type')} | "
                     f"Cause: `{f.get('failure_cause')}` | Dir: `{f.get('direction_flag')}`")

    lines += ["", "## Repeated Patterns"]
    for p in audit_output.get("cross_week_patterns", []):
        lines.append(f"- ⚠ **{p['cause']}** ({p['occurrences']}x) — REPEATED PATTERN")

    lines += ["", "## What We Missed"]
    missed = audit_output.get("missed_report", {}).get("top_performers_we_missed", [])
    for m_item in missed:
        lines.append(f"- P{m_item.get('final_position')}: {m_item.get('player_id')} — {m_item.get('reason_missed')}")

    lines += ["", "## Model Adjustment Recommendations"]
    for rec in audit_output.get("model_adjustment_recommendations", []):
        lines.append(f"- [{rec.get('priority','').upper()}] {rec.get('change')} — {rec.get('evidence')}")

    if weight_changes:
        lines += ["", "## Weight Changes Applied"]
        for wc in weight_changes:
            lines.append(f"- `{wc.get('field')}`: {wc.get('old_value')} → {wc.get('new_value')} (Δ{wc.get('delta'):+.4f})")
    else:
        lines += ["", "## Weight Changes Applied", "- None (evidence gates not met)"]

    out_path.write_text("\n".join(lines))
    log.info(f"Post-event report published: {out_path}")
    return out_path
