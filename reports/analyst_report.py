"""reports/analyst_report.py"""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from pathlib import Path
log = logging.getLogger(__name__)

def publish_analyst_report(event_id, card, model_outputs, sim_results, features) -> Path:
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"analyst_report_{event_id}_{ts}.json"
    report = {
        "event_id": event_id,
        "generated_at": ts,
        "total_players_modeled": len(model_outputs),
        "top_10_by_win_prob": _top_n(model_outputs, 10),
        "picks_summary": {
            "safe_bets": len(card.get("safe_bets", [])),
            "value_bets": len(card.get("value_bets", [])),
            "outrights": len(card.get("upside_outrights", [])),
            "matchups": len(card.get("matchup_bets", [])),
            "longshots": len(card.get("longshot_bets", [])),
        },
    }
    out_path.write_text(json.dumps(report, indent=2, default=str))
    log.info(f"Analyst report published: {out_path}")
    return out_path

def _top_n(model_outputs, n):
    return sorted(
        [{"player_id": pid, "win_prob": m.get("model_win_prob", 0),
          "composite_sg": m.get("composite_sg"), "course_fit": m.get("course_fit_score")}
         for pid, m in model_outputs.items()],
        key=lambda x: x["win_prob"], reverse=True
    )[:n]
