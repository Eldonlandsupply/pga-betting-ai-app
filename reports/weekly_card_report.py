"""reports/weekly_card_report.py"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from pathlib import Path
from picks.card_builder import build_markdown_card
log = logging.getLogger(__name__)

def publish_weekly_card(event_id: str, reviewed_card: dict) -> Path:
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"betting_card_{event_id}_{ts}.md"
    md = build_markdown_card(event_id, reviewed_card)
    out_path.write_text(md, encoding="utf-8")
    log.info(f"Weekly card published: {out_path}")
    return out_path
