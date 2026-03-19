# Data Schema Reference

Complete schema definitions for all data structures in the PGA Betting AI system.

---

## 1. Event Schema

```json
{
  "event_id": "pga_masters_2025",
  "display_name": "Masters Tournament 2025",
  "tour": "PGA",
  "tournament_type": "major",
  "start_date": "2025-04-10",
  "end_date": "2025-04-13",
  "venue": "Augusta National Golf Club",
  "course_key": "augusta_national",
  "purse_usd": 20000000,
  "field_size": 88,
  "has_cut": true,
  "cut_line_position": 50,
  "no_cut_event": false,
  "rounds": 4,
  "status": "upcoming",
  "weather_window": {
    "r1_forecast": "partly_cloudy_15mph_wind",
    "r2_forecast": "rain_likely",
    "r3_forecast": "clear",
    "r4_forecast": "clear",
    "resolved": false
  }
}
```

---

## 2. Player Schema

```json
{
  "player_id": "player_12345",
  "display_name": "Scottie Scheffler",
  "tour_primary": "PGA",
  "world_rank": 1,
  "nationality": "USA",
  "age": 28,
  "status": "active",
  "injury_flag": null,
  "injury_detail": null,
  "rust_flag": false,
  "last_event_date": "2025-04-06",
  "schedule_load_recent": "normal",
  "archetypes": ["elite_ball_striker", "iron_player", "poa_specialist"],
  "pga_to_liv_transfer": false
}
```

---

## 3. Player Stats Schema

```json
{
  "player_id": "player_12345",
  "season": 2025,
  "last_updated": "2025-04-08",
  
  "sg_total": 3.21,
  "sg_ott": 0.82,
  "sg_app": 1.45,
  "sg_atg": 0.38,
  "sg_putt": 0.56,
  
  "sg_total_l20": 3.45,
  "sg_ott_l20": 0.91,
  "sg_app_l20": 1.52,
  "sg_atg_l20": 0.41,
  "sg_putt_l20": 0.61,
  
  "driving_distance": 304.2,
  "driving_accuracy_pct": 62.4,
  "gir_pct": 71.2,
  "scrambling_pct": 62.8,
  "birdie_or_better_pct": 24.1,
  "bogey_avoidance": -0.21,
  
  "par3_scoring_avg": 2.94,
  "par4_scoring_avg": 3.89,
  "par5_scoring_avg": 4.62,
  
  "proximity_100_125": 18.2,
  "proximity_125_150": 22.1,
  "proximity_150_175": 26.4,
  "proximity_175_200": 32.1,
  
  "bent_grass_sg_putt": 0.72,
  "bermuda_sg_putt": 0.41,
  "poa_sg_putt": 0.55,
  
  "wind_20plus_sg": 2.91,
  "final_round_sg": 0.68,
  "major_sg": 2.45,
  
  "make_cut_rate": 0.88,
  "top10_rate": 0.38,
  "win_rate": 0.12,
  
  "rounds_played_l12_months": 58,
  
  "rounds": [
    {
      "event_id": "pga_players_2025",
      "round": 1,
      "date": "2025-03-13",
      "score": -5,
      "sg_ott": 1.2,
      "sg_app": 2.1,
      "sg_atg": 0.4,
      "sg_putt": 0.9,
      "field_strength_percentile": 95,
      "no_cut_event": false,
      "tournament_type": "signature"
    }
  ],
  
  "comp_course_history": {
    "riviera_cc": [
      {
        "event_id": "pga_genesis_2024",
        "final_position": 3,
        "sg_total": 3.1,
        "age_years": 1.1
      }
    ]
  }
}
```

---

## 4. Market Data Schema

```json
{
  "event_id": "pga_masters_2025",
  "market_type": "outright",
  "retrieved_at": "2025-04-08T14:00:00Z",
  "player_id": "player_12345",
  "prices": {
    "pinnacle": [
      {"price": 5.50, "timestamp": "2025-04-07T08:00:00Z"},
      {"price": 5.00, "timestamp": "2025-04-08T12:00:00Z"}
    ],
    "draftkings": [
      {"price": 5.50, "timestamp": "2025-04-07T09:00:00Z"},
      {"price": 5.25, "timestamp": "2025-04-08T11:00:00Z"}
    ],
    "fanduel": [
      {"price": 5.50, "timestamp": "2025-04-07T09:30:00Z"},
      {"price": 5.00, "timestamp": "2025-04-08T13:00:00Z"}
    ]
  }
}
```

---

## 5. Pick Schema

```json
{
  "pick_id": "pick_20250408_001",
  "event_id": "pga_masters_2025",
  "player_id": "player_12345",
  "player_name": "Scottie Scheffler",
  "market_type": "top_10",
  "price": 1.80,
  "american_odds": -125,
  "book": "draftkings",
  "tour": "PGA",
  "tournament_type": "major",
  
  "model_probability": 0.64,
  "implied_probability": 0.556,
  "hold_adjusted_probability": 0.529,
  "edge_pct": 0.111,
  "confidence_tier": "strong",
  "confidence_band_low": 0.58,
  "confidence_band_high": 0.70,
  
  "stake_units": 2.0,
  "kelly_fraction_used": 0.15,
  
  "dominant_signal": "course_fit",
  "signal_diversity_score": 0.78,
  "form_driven": false,
  
  "supporting_reasons": [
    "Elite SG profile matches Augusta's demand for precision iron play (+1.45 sg_app)",
    "Strong comp course history at Muirfield Village and Quail Hollow",
    "3 of last 4 Masters in contention — demonstrated major performance",
    "Sharp book movement: Pinnacle shortened 5.50 → 5.00 in 24h"
  ],
  
  "risk_flags": [],
  "adversarial_verdict": "PASSED",
  "adversarial_challenges": [],
  "kill_score": 0,
  
  "course_fit_score": 0.72,
  "composite_sg": 3.21,
  "data_confidence": 0.95,
  "world_rank": 1,
  
  "line_movement_flag": "shortening_mild",
  "sharp_signal": true,
  "book_disagreement_score": 0.02,
  
  "created_at": "2025-04-08T15:00:00Z",
  "published_at": "2025-04-09T08:00:00Z",
  "result": null,
  "grade": null,
  "pnl_units": null
}
```

---

## 6. Audit Schema

```json
{
  "event_id": "pga_masters_2025",
  "audit_timestamp": "2025-04-15T18:00:00Z",
  "picks_graded": 14,
  
  "metrics": {
    "total_picks": 14,
    "settled_picks": 13,
    "wins": 6,
    "losses": 7,
    "hit_rate_pct": 46.2,
    "realized_roi_pct": -8.4,
    "total_pnl_units": -1.2,
    "model_right_pct": 61.5,
    "avg_clv": 0.012
  },
  
  "graded_picks": [],
  
  "failures": [
    {
      "player_id": "player_67890",
      "market_type": "top_10",
      "model_probability": 0.38,
      "implied_probability": 0.28,
      "final_position": 28,
      "failure_cause": "missed_course_fit_penalty",
      "direction_flag": "wrong_wrong"
    }
  ],
  
  "cross_week_patterns": [
    {
      "cause": "missed_course_fit_penalty",
      "occurrences": 4,
      "flag": "REPEATED_PATTERN"
    }
  ],
  
  "missed_report": {
    "top_performers_we_missed": [
      {
        "player_id": "player_11111",
        "final_position": 2,
        "reason_missed": "Undervalued comp course history at Muirfield Village"
      }
    ]
  },
  
  "model_adjustment_recommendations": [
    {
      "target": "features/course_fit.py",
      "change": "Increase comp_course_history weight in course fit calculation",
      "evidence": "Repeated miss on comp course specialists",
      "priority": "high",
      "gate_required": true
    }
  ]
}
```

---

## 7. Simulation Output Schema

```json
{
  "player_id": "player_12345",
  "win_prob": 0.0842,
  "top5_prob": 0.2341,
  "top10_prob": 0.4218,
  "top20_prob": 0.6891,
  "make_cut_prob": 0.8841,
  "median_finish": 11.2,
  "mean_finish": 14.8,
  "p10_finish": 3.0,
  "p90_finish": 38.0,
  "finish_sd": 12.4,
  "n_simulations": 10000
}
```
