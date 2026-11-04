import pandas as pd
import numpy as np
import ast
import json
from pipeline.events import event_group
from pipeline.paths import RAW_DIR, PROCESSED_DIR

# ── Load all data sources ────────────────────────────────────────────────────

metadata_df      = pd.read_csv(RAW_DIR / "gotham_2026_teams.csv")
humanscout_df    = pd.read_csv(RAW_DIR / "scouting_datanyc.csv", engine="python", on_bad_lines="warn")
opr_df           = pd.read_csv(PROCESSED_DIR / "opr_tba_gotham.csv")
rankings_df      = pd.read_csv(PROCESSED_DIR / "rankings_tba_gotham.csv")
ranking_pred_df  = pd.read_csv(PROCESSED_DIR / "ranking_predictions_tba_gotham.csv")
stats_pred_df    = pd.read_csv(PROCESSED_DIR / "stats_prediction_tba_gotham.csv")
montecarlo_df    = pd.read_csv(PROCESSED_DIR / "monte_carlo_sim_2026nyn2.csv")

# Reports only use real Gotham matches, not practice or other events
humanscout_df    = humanscout_df[humanscout_df["event"].map(event_group) == "Gotham"].copy()


# ── Normalize all team keys ──────────────────────────────────────────────────

# Based on your printout, metadata uses 'team_number'
metadata_df["team_number"]     = metadata_df["team_number"].astype(str).str.replace("frc", "")
humanscout_df["teamNumber"]    = humanscout_df["teamNumber"].astype(str).str.replace("frc", "")
opr_df["team_number"]          = opr_df["team_key"].astype(str).str.replace("frc", "")
rankings_df["team_number"]     = rankings_df["team_key"].astype(str).str.replace("frc", "")
ranking_pred_df["team_number"] = ranking_pred_df["team"].astype(str).str.replace("frc", "")
stats_pred_df["team_number"]   = stats_pred_df["team"].astype(str).str.replace("frc", "")
montecarlo_df["team_number"]   = montecarlo_df["team"].astype(str).str.replace("frc", "")



# ── Main function ────────────────────────────────────────────────────────────

def build_team_data(team_number: str) -> dict:
    """
    Aggregates all data sources for a single team into a clean dict
    """
    team_number = str(team_number)
    result = {"team": team_number}

    # ── 1. Metadata (Updated column name to team_number) ──
    summary_row = metadata_df[metadata_df["team_number"] == team_number]

    if summary_row.empty:
        result["team_found"] = False
    else:
        result["team_found"] = True
        s = summary_row.iloc[0]
        # Pulling from your confirmed column list
        result["nickname"]    = s.get("nickname")
        result["rank"]        = s.get("rank")
        result["global_opr"]  = s.get("global_opr")
        result["global_rank"] = s.get("global_rank")
        result["last_event"]  = s.get("last_event")
        result["last_rank"]   = s.get("last_rank")
        result["last_record"] = s.get("last_record")
        result["avg_pts"]     = s.get("avg_pts")
        result["event_avg"]   = s.get("event_avg")

    # ── 2. Per-match detail from human scouting ──
    detail = humanscout_df[humanscout_df["teamNumber"] == team_number]

    if detail.empty:
        result["scouted_matches"] = 0
        result.update({k: None for k in ["auto_fuel_avg", "auto_tower_avg", "teleop_cycles_avg", 
                                        "teleop_fuel_avg", "teleop_tower_avg", "fouls_avg", "avg_points"]})
        result["all_comments"] = []
    else:
        result["scouted_matches"] = len(detail)
        result["auto_fuel_avg"]  = detail["auto_fuel"].mean() if "auto_fuel" in detail.columns else None
        result["auto_tower_avg"] = detail["auto_tower"].mean() if "auto_tower" in detail.columns else None
        result["teleop_cycles_avg"] = detail["teleop_cycles"].mean() if "teleop_cycles" in detail.columns else None
        result["teleop_fuel_avg"]   = detail["teleop_fuel"].mean() if "teleop_fuel" in detail.columns else None
        result["teleop_tower_avg"]  = detail["teleop_tower"].mean() if "teleop_tower" in detail.columns else None

        if "teleop_majorFoul" in detail.columns and "teleop_minorFoul" in detail.columns:
            result["fouls_avg"] = (detail["teleop_majorFoul"] + detail["teleop_minorFoul"]).mean()
        else:
            result["fouls_avg"] = None

        result["avg_points"] = detail["totalPoints"].mean() if "totalPoints" in detail.columns else None
        result["all_comments"] = detail["comments"].dropna().tolist() if "comments" in detail.columns else []

    # ── 3. OPR / DPR / CCWM ──
    opr_row = opr_df[opr_df["team_number"] == team_number]
    if not opr_row.empty:
        result["opr"]  = round(float(opr_row.iloc[0].get("oprs", 0)), 2)
        result["dpr"]  = round(float(opr_row.iloc[0].get("dprs", 0)), 2)
        result["ccwm"] = round(float(opr_row.iloc[0].get("ccwms", 0)), 2)

    # ── 4. Ranking predictions ──
    rp = ranking_pred_df[ranking_pred_df["team_number"] == team_number]
    if not rp.empty:
        result["predicted_rank"] = int(rp.iloc[0]["rank"])
        result["predicted_ranking_points"] = float(rp.iloc[0]["ranking_points"])

    # ── 5. TBA stat predictions ──
    stats = stats_pred_df[
        (stats_pred_df["team_number"] == team_number) & 
        (stats_pred_df["level"] == "qual")
    ]
    if not stats.empty:
        for _, stat_row in stats.iterrows():
            result[f"tba_pred_{stat_row['stat']}_mean"] = round(float(stat_row["mean"]), 3)
            result[f"tba_pred_{stat_row['stat']}_var"]  = round(float(stat_row["var"]), 3)

    # ── 6. Monte Carlo results ──
    mc_row = montecarlo_df[montecarlo_df["team_number"] == team_number]
    if not mc_row.empty:
        result["mc_predicted_rank"] = int(mc_row.iloc[0]["rank"])
        result["mc_predicted_rp"]   = float(mc_row.iloc[0]["total_rp"])
    return result

# ── Quick test ───────────────────────────────────────────────────────────────

class FRCEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if pd.isna(obj):
            return None
        return super(FRCEncoder, self).default(obj)



if __name__ == "__main__":
    for team in ["6647", "3158", "4403"]:
        data = build_team_data(team)
        print(f"\n{'='*50}")
        # Use the custom encoder here
        print(json.dumps(data, indent=2, cls=FRCEncoder))


