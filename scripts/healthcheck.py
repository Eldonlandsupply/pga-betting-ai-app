#!/usr/bin/env python3
"""Health check for pga-betting-ai-app.

Verifies:
- Required env vars are set and not placeholder values
- Config YAML files parse correctly
- Validator script is importable
- Output directory is writable (creates if absent)

Exit 0 = healthy. Exit 1 = unhealthy (prints all failures).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = {"YOUR_OPENAI_API_KEY", "YOUR_ODDS_API_KEY", "CHANGE_ME", "TODO", ""}

failures: list[str] = []


def check_env(var: str, *, required: bool = True) -> str | None:
    val = os.environ.get(var, "").strip()
    if required and (not val or val in PLACEHOLDER):
        failures.append(f"ENV MISSING or placeholder: {var}")
        return None
    return val or None


def check_yaml(rel_path: str) -> None:
    try:
        import yaml  # type: ignore
    except ImportError:
        # PyYAML not installed; skip silently (not a hard dep)
        return
    p = ROOT / rel_path
    if not p.exists():
        failures.append(f"CONFIG MISSING: {rel_path}")
        return
    try:
        yaml.safe_load(p.read_text())
    except Exception as exc:
        failures.append(f"CONFIG PARSE ERROR {rel_path}: {exc}")


def check_import(module_path: str) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        import importlib
        importlib.import_module(module_path)
    except Exception as exc:
        failures.append(f"IMPORT ERROR {module_path}: {exc}")


def check_output_dir(path_str: str) -> None:
    p = Path(path_str)
    try:
        p.mkdir(parents=True, exist_ok=True)
        test_file = p / ".healthcheck_probe"
        test_file.write_text("ok")
        test_file.unlink()
    except Exception as exc:
        failures.append(f"OUTPUT DIR NOT WRITABLE {path_str}: {exc}")


def main() -> int:
    print("pga-betting-ai-app healthcheck")
    print(f"root: {ROOT}")

    # Required env
    api_key = check_env("OPENAI_API_KEY", required=True)
    model = check_env("PGA_CHAT_MODEL", required=True)

    # Optional env (just report presence)
    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    datagolf_key = os.environ.get("DATAGOLF_API_KEY", "").strip()
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

    # Config files
    check_yaml("config/tour_weights.yaml")
    check_yaml("config/risk_policy.yaml")

    # Core import
    check_import("scripts.validate_event_packet")

    # Output directory
    output_dir = os.environ.get("PGA_OUTPUT_DIR", str(ROOT / "output"))
    check_output_dir(output_dir)

    # Report
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  ✗ {f}")
        return 1

    print("\nSTATUS: OK")
    print(f"  chat_model  = {model}")
    print(f"  api_key     = {'SET' if api_key else 'MISSING'}")
    print(f"  odds_api    = {'SET' if odds_key and odds_key not in PLACEHOLDER else 'not set (optional)'}")
    print(f"  datagolf    = {'SET' if datagolf_key and datagolf_key not in PLACEHOLDER else 'not set (optional)'}")
    print(f"  telegram    = {'SET' if telegram_token and telegram_token not in PLACEHOLDER else 'not set (optional)'}")
    print(f"  output_dir  = {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
