#!/usr/bin/env python3
"""pga-betting-ai-app: run_scan

CLI entry point for manual and scheduled PGA scans.

Usage:
    python scripts/run_scan.py --packet path/to/event_packet.json
    python scripts/run_scan.py --packet path/to/event_packet.json --dry-run

Environment variables required:
    OPENAI_API_KEY   - OpenAI API key
    PGA_CHAT_MODEL   - model id (e.g. gpt-4o-mini)

Optional:
    PGA_STALE_LINE_MINUTES  - staleness threshold (default 30)
    PGA_OUTPUT_DIR          - output directory (default ./output)
    PGA_LOG_LEVEL           - log verbosity (default INFO)

Exit codes:
    0 = success
    1 = validation failure or runtime error
    2 = configuration error
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_event_packet import validate_packet  # noqa: E402

log = logging.getLogger("pga.scan")

PLACEHOLDER = {"YOUR_OPENAI_API_KEY", "CHANGE_ME", "TODO", ""}


def _configure_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=level,
    )


def _require_env(var: str) -> str:
    val = os.environ.get(var, "").strip()
    if not val or val in PLACEHOLDER:
        log.error("Required env var %s is missing or placeholder. Set it in .env.", var)
        raise SystemExit(2)
    return val


def _call_llm(packet: dict, model: str, api_key: str, dry_run: bool) -> str:
    """Send validated event packet to OpenAI for pick generation."""
    if dry_run:
        log.info("DRY RUN: skipping LLM call. Would use model=%s", model)
        return "[DRY RUN] LLM call skipped. Packet validated successfully."

    try:
        import urllib.request
        import urllib.error
    except ImportError:
        log.error("urllib not available — unexpected")
        raise SystemExit(1)

    system_prompt = (
        "You are a disciplined golf betting analyst. "
        "You receive a validated event packet as JSON. "
        "Apply the architecture principles: truth-first, edge-second, no-bet is valid. "
        "Output a structured betting recommendation card following the event_output_template format. "
        "Every pick must include: player, bet_type, edge_percent, confidence, min_acceptable_odds, "
        "no_play_below_odds, reasoning, and invalidation_conditions. "
        "If suppression rules fire, state why. Do not invent data not present in the packet."
    )

    user_prompt = f"Event packet:\n\n{json.dumps(packet, indent=2)}"

    payload = json.dumps({
        "model": model,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        log.error("OpenAI API error %s: %s", exc.code, body)
        raise SystemExit(1)
    except Exception as exc:
        log.error("LLM call failed: %s", exc)
        raise SystemExit(1)


def _write_output(result: str, packet: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    tournament = packet.get("event", {}).get("tournament", "unknown").replace(" ", "_").lower()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"picks_{tournament}_{ts}.md"
    out_path.write_text(result, encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PGA betting scan")
    parser.add_argument("--packet", type=Path, required=True, help="Path to event_packet.json")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, skip LLM call")
    parser.add_argument(
        "--stale-line-minutes", type=int,
        default=int(os.environ.get("PGA_STALE_LINE_MINUTES", "30")),
    )
    args = parser.parse_args()

    log_level = os.environ.get("PGA_LOG_LEVEL", "INFO")
    _configure_logging(log_level)

    # Config
    api_key = _require_env("OPENAI_API_KEY")
    model = _require_env("PGA_CHAT_MODEL")
    output_dir = Path(os.environ.get("PGA_OUTPUT_DIR", str(ROOT / "output")))

    # Load packet
    if not args.packet.exists():
        log.error("Packet file not found: %s", args.packet)
        return 1

    try:
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.error("Invalid JSON in packet file: %s", exc)
        return 1

    # Validate
    log.info("Validating event packet: %s", args.packet)
    errors = validate_packet(
        packet,
        now=datetime.now(timezone.utc),
        stale_line_minutes=args.stale_line_minutes,
    )

    # Warnings vs hard failures
    hard_failures = [e for e in errors if "MISSING" in e and "confidence should be downgraded" not in e]
    warnings = [e for e in errors if e not in hard_failures]

    for w in warnings:
        log.warning("VALIDATION WARNING: %s", w)

    if hard_failures:
        for f in hard_failures:
            log.error("VALIDATION FAILURE: %s", f)
        log.error("Packet failed validation. Fix errors and re-run.")
        return 1

    log.info("Packet validated (warnings: %d)", len(warnings))

    # LLM call
    log.info("Calling LLM model=%s dry_run=%s", model, args.dry_run)
    result = _call_llm(packet, model=model, api_key=api_key, dry_run=args.dry_run)

    # Write output
    out_path = _write_output(result, packet, output_dir)
    log.info("Output written: %s", out_path)
    print(f"\n{'='*60}")
    print(result)
    print(f"{'='*60}")
    print(f"\nSaved: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
