# Raspberry Pi Deployment — pga-betting-ai-app

## Deployment Recommendation: Hybrid (Pi as orchestrator, OpenAI as compute)

The Pi orchestrates, schedules, validates, and triggers. Heavy LLM inference runs on OpenAI's API.
No local model weights. No GPU required. Works on Pi 3B+, 4, or 5.

**Why not fully local?**
- Local LLM inference (llama.cpp, ollama) on a Pi 4/5 is feasible but slow (~5–30 tokens/sec).
- The betting analysis prompt is long. Response latency on-device would be 2–10 minutes.
- OpenAI API costs ~$0.01–0.05 per scan run (gpt-4o-mini). Negligible.
- Recommendation: keep Pi as the trigger/validator; keep LLM calls remote.

---

## What Lives on the Pi

| Component | Location | Purpose |
|---|---|---|
| Repo | `/home/pi/pga-betting-ai-app` | All code and config |
| Virtual env | `.venv/` | Isolated Python deps |
| Config | `config/tour_weights.yaml`, `config/risk_policy.yaml` | Betting model weights |
| Schema | `schemas/event_packet.schema.json` | Input contract |
| Secrets | `.env` (never committed) | API keys |
| Output | `output/` | Generated picks and audit files |
| Logs | journald / `output/` | Scan logs |

---

## What Runs Remotely

| Service | Purpose | Required |
|---|---|---|
| OpenAI API | LLM pick generation | Yes |
| The Odds API | Live market prices (future) | Optional |
| DataGolf API | Player ratings/stats (future) | Optional |

---

## Initial Setup

```bash
# 1. Clone
cd /home/pi
git clone https://github.com/Eldonlandsupply/pga-betting-ai-app.git
cd pga-betting-ai-app

# 2. Bootstrap (creates venv, installs deps, creates .env)
bash scripts/bootstrap_pi.sh

# 3. Fill in secrets
nano .env
# Set: OPENAI_API_KEY, PGA_CHAT_MODEL

# 4. Run healthcheck
source .venv/bin/activate
python scripts/healthcheck.py

# 5. Validate a packet (dry run)
python scripts/run_scan.py --packet path/to/event_packet.json --dry-run
```

---

## Running a Scan

```bash
# Validate only (no LLM call, no API cost)
python scripts/run_scan.py --packet input/current_event.json --dry-run

# Full scan (validates + calls OpenAI + writes output)
python scripts/run_scan.py --packet input/current_event.json
```

Output is written to `output/picks_<tournament>_<timestamp>.md`.

---

## Updating the Repo

```bash
cd /home/pi/pga-betting-ai-app
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
python scripts/healthcheck.py
```

---

## OpenClaw Integration

The `openclaw_integration/pga_tasks.py` module registers these commands:

| Command | Action | Confirm required |
|---|---|---|
| `check pga status` | Run healthcheck | No |
| `run pga scan` | Validate packet + dry run | No |
| `generate pga picks` | Full LLM scan (costs tokens) | Yes |
| `refresh pga data` | Data refresh (OPEN ITEM) | No |

To register in OpenClaw's task router:

```python
from openclaw_integration.pga_tasks import register
register(your_router)
```

If OpenClaw uses a YAML task registry, add entries manually from `PGA_TASKS` in `pga_tasks.py`.

---

## Scheduled Runs (systemd timer)

```bash
# Copy service and timer
sudo cp systemd/pga-betting-ai.service /etc/systemd/system/
sudo cp systemd/pga-betting-ai.timer /etc/systemd/system/

# Edit service to match your paths and user
sudo nano /etc/systemd/system/pga-betting-ai.service

# Enable and start timer
sudo systemctl daemon-reload
sudo systemctl enable pga-betting-ai.timer
sudo systemctl start pga-betting-ai.timer

# Verify
systemctl status pga-betting-ai.timer
```

The timer fires every Tuesday at 08:00. Adjust `OnCalendar=` for your tournament schedule.

---

## Logs

```bash
# Systemd service logs
journalctl -u pga-betting-ai.service -f

# Manual run logs (stdout)
python scripts/run_scan.py --packet ... 2>&1 | tee output/run.log

# List all output files
ls -lt output/
```

---

## Required Env Vars

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `PGA_CHAT_MODEL` | Yes | Model ID (e.g. `gpt-4o-mini`) |
| `ODDS_API_KEY` | Optional | The Odds API key (future) |
| `DATAGOLF_API_KEY` | Optional | DataGolf API key (future) |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram push notifications |
| `TELEGRAM_CHAT_ID` | Optional | Telegram chat ID |
| `PGA_STALE_LINE_MINUTES` | Optional | Staleness threshold (default 30) |
| `PGA_OUTPUT_DIR` | Optional | Output directory (default `./output`) |
| `PGA_LOG_LEVEL` | Optional | Log level (default `INFO`) |

---

## Stopping a Scheduled Run

```bash
sudo systemctl stop pga-betting-ai.timer
sudo systemctl disable pga-betting-ai.timer
```

---

## ARM Compatibility

| Component | ARM compatible | Notes |
|---|---|---|
| Python 3.11+ | ✅ | Native |
| jsonschema | ✅ | Pure Python |
| pytest | ✅ | Dev only |
| OpenAI API calls | ✅ | urllib only, no openai SDK required |
| Local LLM | ⚠️ | Feasible on Pi 5 with llama.cpp, but slow. Not recommended. |
| Browser automation | N/A | Not used in this repo |
| Docker | ✅ | Available on Pi, not required here |

---

## OPEN ITEMS

1. **Live data ingestion**: `scripts/fetch_odds.py` (Odds API) and `scripts/fetch_datagolf.py` not yet implemented. Phase 2 of roadmap.
2. **Telegram trigger**: `TELEGRAM_BOT_TOKEN` wiring to OpenClaw command handler not yet implemented. Depends on OpenClaw's Telegram connector being active.
3. **OpenClaw router API**: `openclaw_integration/pga_tasks.py` calls `router.register()`. Adapt to match OpenClaw's actual router method signature.
4. **Event packet source**: Currently manual. No automated ingestion. Operator must provide `event_packet.json`.
5. **Post-event audit loop**: Phase 4 of roadmap. Not yet implemented.
6. **CLV tracking**: Phase 4. Not yet implemented.

---

## Hard Limitations

- This repo has **no production scoring code yet** (roadmap Phase 2+). The validator and config are complete; the actual player rating engine and market edge engine are OPEN ITEMS.
- The LLM is doing the heavy analytical lift based on structured prompts. This is appropriate for the Pi's capabilities but depends entirely on input packet quality.
- **No live data ingestion** = operator must manually build `event_packet.json`. Until Phase 2 is built, the system is only as good as the data you put in.
- **OpenAI API key required**. No key = no picks. The Pi cannot run a local LLM fast enough for practical use.
