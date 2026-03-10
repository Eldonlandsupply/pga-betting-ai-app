"""openclaw_integration/pga_tasks.py

OpenClaw task registry entries for pga-betting-ai-app.

Registers the following approved commands:
  - run pga scan
  - refresh pga data
  - generate pga picks
  - check pga status

This module is designed to be imported by OpenClaw's task router.
It does not invent its own dispatch mechanism — it plugs into whatever
command registry/router OpenClaw exposes.

Usage (OpenClaw task router):
    from openclaw_integration.pga_tasks import PGA_TASKS
    # Register each task in your router's task registry.

Each task entry is a dict with:
    name         - canonical command string
    aliases      - list of alternate phrasings
    handler      - async callable(args: dict) -> str
    description  - human-readable description
    requires_confirm - bool (True for actions that cost money or mutate state)
    log_invocation   - bool (always True for audit trail)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger("openclaw.pga")

PGA_REPO = Path(__file__).resolve().parents[1]
VENV_PYTHON = PGA_REPO / ".venv" / "bin" / "python3"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run subprocess, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "PYTHONPATH": str(PGA_REPO)},
    )
    return result.returncode, result.stdout, result.stderr


# ── Handlers ──────────────────────────────────────────────────────────────────

async def handle_check_pga_status(args: dict[str, Any]) -> str:
    """Run healthcheck and return status string."""
    log.info("PGA task: check_pga_status")
    try:
        rc, stdout, stderr = await asyncio.to_thread(
            _run,
            [PYTHON, str(PGA_REPO / "scripts" / "healthcheck.py")],
            timeout=30,
        )
        output = (stdout + stderr).strip()
        status = "✅ PGA system healthy" if rc == 0 else "❌ PGA system unhealthy"
        return f"{status}\n\n{output}"
    except subprocess.TimeoutExpired:
        return "❌ PGA healthcheck timed out"
    except Exception as exc:
        log.exception("check_pga_status failed")
        return f"❌ PGA healthcheck error: {exc}"


async def handle_run_pga_scan(args: dict[str, Any]) -> str:
    """Validate and run PGA scan on provided packet file."""
    log.info("PGA task: run_pga_scan args=%s", args)
    packet_path = args.get("packet_path", "")
    if not packet_path:
        return (
            "❌ run pga scan requires --packet_path argument.\n"
            "Example: run pga scan --packet_path /home/pi/events/this_week.json"
        )
    packet_path = Path(packet_path)
    if not packet_path.exists():
        return f"❌ Packet file not found: {packet_path}"

    dry_run = args.get("dry_run", False)
    cmd = [PYTHON, str(PGA_REPO / "scripts" / "run_scan.py"), "--packet", str(packet_path)]
    if dry_run:
        cmd.append("--dry-run")

    try:
        rc, stdout, stderr = await asyncio.to_thread(_run, cmd, timeout=120)
        output = (stdout + stderr).strip()
        status = "✅ PGA scan complete" if rc == 0 else "❌ PGA scan failed"
        return f"{status}\n\n{output}"
    except subprocess.TimeoutExpired:
        return "❌ PGA scan timed out (120s)"
    except Exception as exc:
        log.exception("run_pga_scan failed")
        return f"❌ PGA scan error: {exc}"


async def handle_generate_pga_picks(args: dict[str, Any]) -> str:
    """Generate picks from packet file via LLM. Requires confirmation."""
    log.info("PGA task: generate_pga_picks args=%s", args)
    # Same as run_scan but always live (no dry-run)
    packet_path = args.get("packet_path", "")
    if not packet_path:
        return (
            "❌ generate pga picks requires --packet_path.\n"
            "Example: generate pga picks --packet_path /home/pi/events/this_week.json"
        )
    packet_path = Path(packet_path)
    if not packet_path.exists():
        return f"❌ Packet file not found: {packet_path}"

    cmd = [PYTHON, str(PGA_REPO / "scripts" / "run_scan.py"), "--packet", str(packet_path)]
    try:
        rc, stdout, stderr = await asyncio.to_thread(_run, cmd, timeout=180)
        output = (stdout + stderr).strip()
        status = "✅ Picks generated" if rc == 0 else "❌ Pick generation failed"
        return f"{status}\n\n{output}"
    except subprocess.TimeoutExpired:
        return "❌ Pick generation timed out (180s)"
    except Exception as exc:
        log.exception("generate_pga_picks failed")
        return f"❌ Pick generation error: {exc}"


async def handle_refresh_pga_data(args: dict[str, Any]) -> str:
    """
    Refresh PGA data sources.

    OPEN ITEM: This repo has no live data ingestion pipeline yet (Phase 2+).
    Currently returns status and instructions for manual data update.
    Once a data fetcher is added to scripts/, wire it here.
    """
    log.info("PGA task: refresh_pga_data")
    return (
        "ℹ️  PGA data refresh is not yet automated.\n\n"
        "Current state: The repo uses manually-provided event_packet.json files.\n"
        "Live data ingestion (odds API, DataGolf) is Phase 2 of the roadmap.\n\n"
        "To update data manually:\n"
        "  1. Build your event_packet.json per schemas/event_packet.schema.json\n"
        "  2. Run: python scripts/validate_event_packet.py your_packet.json\n"
        "  3. Run: run pga scan --packet_path your_packet.json\n\n"
        "OPEN ITEM: Implement scripts/fetch_odds.py and scripts/fetch_datagolf.py "
        "once ODDS_API_KEY and DATAGOLF_API_KEY are available."
    )


# ── Task Registry ─────────────────────────────────────────────────────────────

PGA_TASKS = [
    {
        "name": "check pga status",
        "aliases": ["pga status", "pga health", "is pga running"],
        "handler": handle_check_pga_status,
        "description": "Run PGA system healthcheck and report status.",
        "requires_confirm": False,
        "log_invocation": True,
    },
    {
        "name": "run pga scan",
        "aliases": ["pga scan", "scan pga", "pga validate"],
        "handler": handle_run_pga_scan,
        "description": "Validate and run PGA betting scan on an event packet (dry-run safe).",
        "requires_confirm": False,
        "log_invocation": True,
    },
    {
        "name": "generate pga picks",
        "aliases": ["pga picks", "pga recommendations", "get pga picks"],
        "handler": handle_generate_pga_picks,
        "description": "Generate PGA betting picks via LLM. Uses OpenAI API (costs tokens).",
        "requires_confirm": True,  # costs money
        "log_invocation": True,
    },
    {
        "name": "refresh pga data",
        "aliases": ["pga refresh", "update pga data", "pga update"],
        "handler": handle_refresh_pga_data,
        "description": "Refresh PGA data sources (OPEN ITEM: live ingestion not yet implemented).",
        "requires_confirm": False,
        "log_invocation": True,
    },
]


def register(router: Any) -> None:
    """
    Register PGA tasks with an OpenClaw task router.

    The router is expected to have a register(task_def) method
    or equivalent. Adapt to match OpenClaw's actual router API.
    """
    for task in PGA_TASKS:
        if hasattr(router, "register"):
            router.register(task)
        elif hasattr(router, "add_task"):
            router.add_task(task)
        else:
            log.warning(
                "Cannot register PGA task '%s': router has no register/add_task method. "
                "Adapt this module to match OpenClaw's router API.",
                task["name"],
            )
