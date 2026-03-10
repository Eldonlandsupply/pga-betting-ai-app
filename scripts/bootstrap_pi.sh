#!/usr/bin/env bash
# bootstrap_pi.sh
# One-shot setup for pga-betting-ai-app on Raspberry Pi (arm64/armv7).
# Run once from the repo root after cloning.
# Usage: bash scripts/bootstrap_pi.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
ENV_FILE="$REPO_DIR/.env"
ENV_EXAMPLE="$REPO_DIR/.env.example"

echo "=== pga-betting-ai-app bootstrap ==="
echo "Repo: $REPO_DIR"
echo "Python: $(python3 --version)"

# 1) Create virtualenv
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "[1/4] Virtual environment already exists, skipping."
fi

# 2) Install dependencies
echo "[2/4] Installing dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"
echo "      Done."

# 3) Create .env if missing
if [ ! -f "$ENV_FILE" ]; then
    echo "[3/4] Creating .env from .env.example..."
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "      IMPORTANT: Edit $ENV_FILE and fill in your API keys before running."
else
    echo "[3/4] .env already exists, skipping."
fi

# 4) Create output directory
echo "[4/4] Creating output directory..."
mkdir -p "$REPO_DIR/output"

echo ""
echo "=== Bootstrap complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $ENV_FILE and fill in OPENAI_API_KEY and PGA_CHAT_MODEL"
echo "  2. source $VENV_DIR/bin/activate"
echo "  3. python scripts/healthcheck.py"
echo "  4. python scripts/run_scan.py --packet path/to/event_packet.json --dry-run"
echo ""
