"""
ui/app.py
----------
Main Streamlit dashboard for the PGA Betting AI system.

Pages:
  1. Weekly Card       — Current event picks, ranked by edge
  2. Player Deep-Dive  — Per-player model breakdown
  3. Value Board       — Edge board across all market types
  4. Line Movement     — Live line tracking and sharp signal alerts
  5. Post-Event Audit  — Historical pick grades and ROI
  6. Model Health      — Calibration, CLV, weight status
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Streamlit import guard
try:
    import streamlit as st
except ImportError:
    print("Streamlit not installed. Run: pip install streamlit")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Page configuration ---
st.set_page_config(
    page_title="PGA Betting AI",
    page_icon="⛳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Sidebar navigation ---
st.sidebar.title("⛳ PGA Betting AI")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    ["Weekly Card", "Player Deep-Dive", "Value Board",
     "Line Movement", "Post-Event Audit", "Model Health"],
)

# Current event selector
output_dir = ROOT / "output"
event_files = sorted(output_dir.glob("betting_card_*.md"), reverse=True) if output_dir.exists() else []
event_options = [f.stem for f in event_files] if event_files else ["No events yet"]
selected_event = st.sidebar.selectbox("Event", event_options)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Model version**: v1.0\n\n"
    "**Data freshness**: Manual input\n\n"
    "**Last run**: —"
)

# ---------------------------------------------------------------------------
# PAGE: WEEKLY CARD
# ---------------------------------------------------------------------------
if page == "Weekly Card":
    st.title("📋 Weekly Betting Card")

    if not event_files:
        st.info("No betting cards generated yet. Run `python run_weekly.py` to generate picks.")
        st.code("python run_weekly.py --mode pre_event", language="bash")
    else:
        card_path = output_dir / f"{selected_event}.md"
        if card_path.exists():
            content = card_path.read_text()
            st.markdown(content)
        else:
            st.warning("Card file not found.")

    with st.expander("Run Pipeline Now"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Run Pre-Event Pipeline", use_container_width=True):
                st.info("Running pipeline... check terminal for progress.")
                os.system("python run_weekly.py --mode pre_event --dry_run")
        with col2:
            if st.button("📊 Dry Run (Validate Only)", use_container_width=True):
                st.info("Validating event packet...")
                os.system("python scripts/validate_event_packet.py input/current_event.json")


# ---------------------------------------------------------------------------
# PAGE: PLAYER DEEP-DIVE
# ---------------------------------------------------------------------------
elif page == "Player Deep-Dive":
    st.title("🔍 Player Deep-Dive")

    # Try to load latest analyst report
    analyst_files = sorted(output_dir.glob("analyst_report_*.json"), reverse=True) if output_dir.exists() else []

    if not analyst_files:
        st.info("No analyst reports yet. Generate picks first.")
    else:
        report_path = analyst_files[0]
        report = json.loads(report_path.read_text())
        top_players = report.get("top_10_by_win_prob", [])

        st.subheader(f"Top Players — {report.get('event_id', 'Unknown Event')}")
        st.caption(f"Generated: {report.get('generated_at', '—')}")

        if top_players:
            # Build display table
            table_data = []
            for i, p in enumerate(top_players, 1):
                table_data.append({
                    "Rank":       i,
                    "Player":     p.get("player_id", "").replace("_", " ").title(),
                    "Win Prob":   f"{p.get('win_prob',0)*100:.1f}%",
                    "SG Total":   f"{p.get('composite_sg',0):+.2f}" if p.get("composite_sg") else "—",
                    "Course Fit": f"{p.get('course_fit',0):+.2f}" if p.get("course_fit") else "—",
                })
            st.table(table_data)
        else:
            st.warning("No player data available.")


# ---------------------------------------------------------------------------
# PAGE: VALUE BOARD
# ---------------------------------------------------------------------------
elif page == "Value Board":
    st.title("💰 Value Edge Board")
    st.caption("All picks ranked by model edge, filtered by market type.")

    # Load latest picks log
    picks_logs = sorted((ROOT / "picks/logs").glob("*_picks.json"), reverse=True) if (ROOT / "picks/logs").exists() else []

    if not picks_logs:
        st.info("No picks logs found. Run the pipeline to generate picks.")
    else:
        picks = json.loads(picks_logs[0].read_text())

        # Market type filter
        market_types = list({p.get("market_type","") for p in picks if p.get("market_type")})
        selected_markets = st.multiselect("Market Types", sorted(market_types), default=market_types)

        # Tour filter
        tours = list({p.get("tour","PGA") for p in picks})
        selected_tours = st.multiselect("Tour", tours, default=tours)

        # Min edge filter
        min_edge = st.slider("Min Edge %", 0.0, 20.0, 4.0, 0.5)

        filtered = [
            p for p in picks
            if p.get("market_type") in selected_markets
            and p.get("tour") in selected_tours
            and (p.get("edge_pct") or 0) >= min_edge
        ]
        filtered = sorted(filtered, key=lambda x: x.get("edge_pct", 0), reverse=True)

        st.subheader(f"{len(filtered)} picks matching filters")

        for pick in filtered[:30]:
            col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 2])
            with col1:
                name = (pick.get("player_name") or pick.get("player_id", "")).replace("_"," ").title()
                st.markdown(f"**{name}**")
            with col2:
                mt_labels = {"outright":"Win","top_5":"Top 5","top_10":"Top 10",
                             "top_20":"Top 20","h2h":"H2H","make_cut":"Make Cut","frl":"FRL"}
                label = mt_labels.get(pick.get("market_type",""), pick.get("market_type",""))
                st.markdown(f"`{label}` @ **{pick.get('price',0):.2f}**")
            with col3:
                edge = pick.get("edge_pct", 0)
                color = "🟢" if edge >= 8 else ("🟡" if edge >= 4 else "🔴")
                st.markdown(f"{color} **+{edge:.1f}%**")
            with col4:
                sharp = "⚡" if pick.get("sharp_signal") else ""
                st.markdown(f"{sharp} {pick.get('confidence_tier','').replace('tier_','T')}")
            with col5:
                book = pick.get("book","").replace("_"," ").title()
                st.caption(f"{book} | {pick.get('stake_units',0)*100:.1f}% stake")


# ---------------------------------------------------------------------------
# PAGE: LINE MOVEMENT
# ---------------------------------------------------------------------------
elif page == "Line Movement":
    st.title("📈 Line Movement Tracker")
    st.caption("Track sharp vs recreational book divergence and line drift.")

    picks_logs = sorted((ROOT / "picks/logs").glob("*_picks.json"), reverse=True) if (ROOT / "picks/logs").exists() else []

    if not picks_logs:
        st.info("No market data yet.")
    else:
        picks = json.loads(picks_logs[0].read_text())
        movers = [p for p in picks if p.get("line_movement_flag") and "significant" in p.get("line_movement_flag","")]
        sharp_alerts = [p for p in picks if p.get("sharp_signal")]

        col1, col2 = st.columns(2)
        with col1:
            st.subheader(f"⚡ Sharp Signals ({len(sharp_alerts)})")
            for p in sharp_alerts[:10]:
                name = (p.get("player_name") or p.get("player_id","")).replace("_"," ").title()
                st.markdown(f"- **{name}** {p.get('market_type','')} @ {p.get('price',0):.2f}")
        with col2:
            st.subheader(f"📉 Significant Line Movement ({len(movers)})")
            for p in movers[:10]:
                name = (p.get("player_name") or p.get("player_id","")).replace("_"," ").title()
                flag = p.get("line_movement_flag","")
                icon = "📈" if "shortening" in flag else "📉"
                st.markdown(f"- {icon} **{name}** — `{flag}`")


# ---------------------------------------------------------------------------
# PAGE: POST-EVENT AUDIT
# ---------------------------------------------------------------------------
elif page == "Post-Event Audit":
    st.title("🔎 Post-Event Audit")

    audit_files = sorted((ROOT / "output").glob("post_event_audit_*.md"), reverse=True) if (ROOT / "output").exists() else []

    if not audit_files:
        st.info("No audit reports yet.")
        st.code("python run_weekly.py --mode post_event", language="bash")
    else:
        selected_audit = st.selectbox("Audit Report", [f.name for f in audit_files])
        audit_path = ROOT / "output" / selected_audit
        if audit_path.exists():
            st.markdown(audit_path.read_text())


# ---------------------------------------------------------------------------
# PAGE: MODEL HEALTH
# ---------------------------------------------------------------------------
elif page == "Model Health":
    st.title("🏥 Model Health")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Current Weights")
        try:
            import yaml
            with open(ROOT / "configs/model_weights.yaml") as f:
                weights = yaml.safe_load(f)
            st.caption(f"Version: {weights.get('version')} | Last updated: {weights.get('last_updated')}")
            gw = weights.get("global_weights", {})
            for k, v in gw.items():
                bar_val = int(v * 100)
                st.markdown(f"**{k}**: {v:.3f}")
                st.progress(bar_val)
        except Exception as e:
            st.error(f"Could not load weights: {e}")

    with col2:
        st.subheader("Changelog (Last 20 lines)")
        changelog = ROOT / "CHANGELOG.md"
        if changelog.exists():
            lines = changelog.read_text().split("\n")
            st.code("\n".join(lines[-20:]), language="markdown")

        st.subheader("Kill Switch Status")
        ks_path = ROOT / "configs/kill_switches.yaml"
        if ks_path.exists():
            import yaml
            ks = yaml.safe_load(ks_path.read_text())
            for name, cfg in ks.get("switches", {}).items():
                status = "🟢 Active" if not cfg.get("triggered") else "🔴 Triggered"
                st.markdown(f"- **{name}**: {status}")
        else:
            st.info("kill_switches.yaml not yet configured.")
