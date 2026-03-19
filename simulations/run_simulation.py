"""
simulations/run_simulation.py
------------------------------
Orchestrates tournament simulation by preparing player inputs from
ensemble model outputs and running the Monte Carlo engine.
"""
from __future__ import annotations
import logging
from simulations.monte_carlo import simulate_tournament
log = logging.getLogger(__name__)

def run_tournament_simulation(
    event_id: str,
    model_outputs: dict,
    n_simulations: int = 10_000,
) -> dict:
    """
    Prepare player inputs from ensemble outputs and run simulation.
    Returns per-player finish distributions from monte_carlo.py.
    """
    tour = _detect_tour(model_outputs)

    players = []
    for pid, model in model_outputs.items():
        sg = model.get("composite_sg") or 0.0
        form = model.get("raw_components", {}).get("s_form", 0.0)
        vol_tier = model.get("volatility_tier", "grinder")

        players.append({
            "player_id":      pid,
            "skill_composite": sg,
            "volatility_sd":  _vol_sd(vol_tier),
            "ceiling_boost":  _ceiling_boost(vol_tier),
            "form_adjustment": form * 0.3,   # Form is partial driver
        })

    log.info(f"Simulating {len(players)} players | n={n_simulations} | tour={tour}")
    return simulate_tournament(
        event_id=event_id,
        players=players,
        n_simulations=n_simulations,
        tour=tour,
        apply_cut=(tour == "PGA"),
    )

def _detect_tour(model_outputs: dict) -> str:
    tours = [v.get("tour", "PGA") for v in model_outputs.values()]
    return "LIV" if tours.count("LIV") > len(tours) / 2 else "PGA"

def _vol_sd(tier: str) -> float:
    return {"elite_consistent": 2.5, "grinder": 2.7, "high_ceiling": 3.2,
            "boom_bust": 3.8, "volatile": 4.2}.get(tier, 3.0)

def _ceiling_boost(tier: str) -> float:
    return {"elite_consistent": 0.1, "high_ceiling": 0.25,
            "boom_bust": 0.30, "grinder": 0.0, "volatile": 0.05}.get(tier, 0.0)
