# Setup Guide

## Prerequisites

- Python 3.11+
- Git
- (Optional) DataGolf API key — for automated stat ingestion
- (Optional) The Odds API key — for live market ingestion
- (Optional) Streamlit — for the UI dashboard

---

## Installation

```bash
# 1. Clone the repo
git clone <repo_url>
cd pga-betting-ai

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
cp .env.example .env
# Edit .env — add API keys if available
```

---

## Running Without API Keys (Manual Mode)

The system works fully without live API connections.
You build input files manually and the system models and picks from them.

### Step 1 — Build your event packet

Copy the template from `input/current_event.json` and fill in:
- Event metadata (tournament, tour, course, format)
- Player list with stats and form notes
- Sportsbook lines with timestamps
- Data quality flags

Validate it:
```bash
python scripts/validate_event_packet.py input/current_event.json
```

### Step 2 — Run the pipeline

```bash
# Validate + model + generate picks (no LLM cost in dry-run)
python run_weekly.py --mode pre_event --dry_run

# Full run with report output
python run_weekly.py --mode pre_event
```

### Step 3 — View output

```bash
# See generated picks
ls output/

# Launch dashboard
streamlit run ui/app.py
```

---

## Running Tests

```bash
pytest tests/ -v

# With coverage
pytest tests/ --cov=. --cov-report=term-missing
```

Tests cover: features, simulation, markets, audit, picks, adversarial review.

---

## Weekly Workflow

| Day | Action |
|---|---|
| Monday | Update `input/current_event.json` with field and opening markets |
| Tuesday | Run `--mode pre_event` for preliminary picks |
| Wednesday | Update markets with latest prices, re-run |
| Thursday AM | Final card published |
| Sunday/Monday | Add results file, run `--mode post_event` |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATAGOLF_API_KEY` | No (Phase 2) | DataGolf API key for automated stat ingestion |
| `ODDS_API_KEY` | No (Phase 2) | The Odds API key for live market prices |
| `PGA_LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING` |
| `PGA_OUTPUT_DIR` | No | Output directory (default: `./output`) |
