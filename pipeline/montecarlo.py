# Imports
import pandas as pd
import numpy as np
import random
import requests
import os
from math import ceil
from dotenv import load_dotenv
from pipeline.paths import PROCESSED_DIR

load_dotenv()

# TBA Setup
baseurl = "https://www.thebluealliance.com/api/v3"
headers = {"X-TBA-Auth-Key": os.getenv("TBAKEY")}
session = requests.Session()
session.headers.update(headers)

EVENT_KEY = "2026nyn2"
TOTAL_REGIONALS = 1000

# Load OPR data
df = pd.read_csv(PROCESSED_DIR / "opr_tba_gotham.csv", index_col=0)
df.index.name = "team_key"
df = df.reset_index()
df = df.rename(columns={"team_key": "team", "oprs": "opr", "dprs": "dpr", "ccwms": "ccwm"})
scale_factor = 364 / df["opr"].max()
df["opr"] = df["opr"] * scale_factor
teams = df["team"].tolist()
stats = df.set_index("team").to_dict("index")

def get_rp_rates(event_key):
    """
    Pulls completed qual matches and calculates how often each RP
    was achieved. Falls back to defaults if no matches are completed.
    """
    print(f"Fetching match data for {event_key}...")
    matches = session.get(f"{baseurl}/event/{event_key}/matches").json()

    if isinstance(matches, (str, dict)):
        print("TBA error response:", matches)
        return _fallback_rp_rates()

    completed = [
        m for m in matches
        if m.get("actual_time")
        and m.get("comp_level") == "qm"
        and m.get("score_breakdown")
    ]

    print(f"Completed qual matches with breakdown: {len(completed)}")

    if not completed:
        print("No completed matches yet -- using fallback RP rates")
        return _fallback_rp_rates()

    energized_hits = supercharged_hits = traversal_hits = 0
    total_alliances = total_fuel = total_tower = 0

    for match in completed:
        for alliance in ["red", "blue"]:
            bd = match["score_breakdown"].get(alliance, {})
            if not bd:
                continue

            total_alliances += 1
            fuel = bd.get("hubScore", {}).get("totalCount", 0)
            tower = bd.get("totalTowerPoints", 0)

            total_fuel += fuel
            total_tower += tower

            if bd.get("energizedAchieved"):    energized_hits += 1
            if bd.get("superchargedAchieved"): supercharged_hits += 1
            if bd.get("traversalAchieved"):    traversal_hits += 1

    avg_fuel  = total_fuel  / total_alliances if total_alliances else 80
    avg_tower = total_tower / total_alliances if total_alliances else 15

    rates = {
        "energized_threshold":    100,
        "supercharged_threshold": 360,
        "traversal_threshold":    50,
        "energized_rate":         energized_hits    / total_alliances,
        "supercharged_rate":      supercharged_hits / total_alliances,
        "traversal_rate":         traversal_hits    / total_alliances,
        "avg_alliance_fuel":      round(avg_fuel, 1),
        "avg_alliance_tower":     round(avg_tower, 1),
    }

    print(f"RP rates from {total_alliances} alliance performances:")
    print(f"  Energized:    {rates['energized_rate']:.1%} (avg fuel: {avg_fuel:.1f})")
    print(f"  Supercharged: {rates['supercharged_rate']:.1%}")
    print(f"  Traversal:    {rates['traversal_rate']:.1%} (avg tower: {avg_tower:.1f})")

    return rates


def _fallback_rp_rates():
    """Default RP rates when no match data is available."""
    return {
        "energized_threshold":    100,
        "supercharged_threshold": 360,
        "traversal_threshold":    50,
        "energized_rate":         0.509,
        "supercharged_rate":      0.018,
        "traversal_rate":         0.0,
        "avg_alliance_fuel":      125.2,
        "avg_alliance_tower":     0.4,
    }


def get_real_rp_per_team(event_key):
    """Pull actual RP totals per team from TBA rankings."""
    rankings_data = session.get(f"{baseurl}/event/{event_key}/rankings").json()
    if not rankings_data.get("rankings"):
        return {}
    return {
        r["team_key"]: r["extra_stats"][0]
        for r in rankings_data["rankings"]
    }


def matchsim(red_alliance, blue_alliance, rp_rates):
    """Simulate a single match and return RP for each alliance."""
    red_rp = blue_rp = 0

    red_raw  = sum(stats[t]["opr"] for t in red_alliance)
    blue_raw = sum(stats[t]["opr"] for t in blue_alliance)

    red_final  = np.random.normal(red_raw,  12)
    blue_final = np.random.normal(blue_raw, 12)

    if red_final > blue_final + 2:
        red_rp += 2
    elif blue_final > red_final + 2:
        blue_rp += 2
    else:
        red_rp += 1
        blue_rp += 1

    avg_opr = sum(s["opr"] for s in stats.values()) / len(stats)

    for alliance, raw in [("red", red_raw), ("blue", blue_raw)]:
        scale = (raw / (avg_opr * 3)) if avg_opr > 0 else 1
        p_energized = min(rp_rates["energized_rate"] * max(scale, 1.0), 0.92)
        if np.random.random() < p_energized:
            if alliance == "red": red_rp += 1
            else:                 blue_rp += 1

    return red_rp, blue_rp


def simulate_regional(rp_rates):
    rankings = {team: 0 for team in teams}
    matches_played = {team: 0 for team in teams}
    target_matches = 10

    while any(v < target_matches for v in matches_played.values()):
        eligible = [t for t in teams if matches_played[t] < target_matches]
        if len(eligible) < 6:
            break
        match_pool = random.sample(eligible, 6)
        red, blue = match_pool[:3], match_pool[3:]

        red_rp = blue_rp = 0
        for _ in range(10):
            r, b = matchsim(red, blue, rp_rates)
            red_rp += r
            blue_rp += b

        for t in red:
            rankings[t] += ceil(red_rp / 10)
            matches_played[t] += 1
        for t in blue:
            rankings[t] += ceil(blue_rp / 10)
            matches_played[t] += 1

    return pd.DataFrame(list(rankings.items()), columns=["team", "total_rp"])


if __name__ == "__main__":
    rp_rates = get_rp_rates(EVENT_KEY)

    print(f"\nRunning {TOTAL_REGIONALS} simulated regionals...")
    results = simulate_regional(rp_rates)

    for i in range(TOTAL_REGIONALS - 1):
        rN = simulate_regional(rp_rates)
        results["total_rp"] += rN["total_rp"]

    # Keep decimals. Rounding to whole RP creates ties that get ranked arbitrarily.
    results["total_rp"] = (results["total_rp"] / TOTAL_REGIONALS).round(2)
    results = results.sort_values(by="total_rp", ascending=False).reset_index(drop=True)
    results["rank"] = results.index + 1

    print("\nPredicted Seedings:")
    print(results.to_string())

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    output_path = PROCESSED_DIR / f"monte_carlo_sim_{EVENT_KEY}.csv"
    results.to_csv(output_path, index=False)
    print(f"Saved to {output_path}")

    real_rp = get_real_rp_per_team(EVENT_KEY)
    if real_rp:
        print("\nReal RP from TBA rankings:")
        for team, rp in sorted(real_rp.items(), key=lambda x: -x[1])[:10]:
            print(f"  {team}: {rp} RP")
    else:
        print("Rankings not available yet")

    print("\nRP rates being used:")
    for k, v in rp_rates.items():
        print(f"  {k}: {v}")
