#Imports
import requests
import pandas as pd
import json
from dotenv import load_dotenv
import os
from pipeline.paths import PROCESSED_DIR

load_dotenv()

#//Important
baseurl = "https://www.thebluealliance.com/api/v3"
headers = {"X-TBA-Auth-Key": os.getenv("TBAKEY")}
session = requests.Session()
session.headers.update(headers)

EVENT_KEY = "2026nyn2"

#Scrapers // OPR, more coming // autonom points, game points,

def EventOPR(eventkey):
    EventOPR = f"{baseurl}/event/{eventkey}/oprs"
    print("Calling:", EventOPR)
    return session.get(EventOPR).json()
def predi(eventkey):
    predi = f"{baseurl}/event/{eventkey}/predictions"
    print("CALLING:", predi)
    return session.get(predi).json()
def coprs(eventkey):
    coprs = f"{baseurl}/event/{eventkey}/coprs"
    print("CALLING:", coprs)
    return session.get(coprs).json()
def rankings(eventkey):
    rankings = f"{baseurl}/event/{eventkey}/rankings"
    print("CALLING:", rankings)
    return session.get(rankings).json()


def main():
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    #OPR
    opr_raw = EventOPR(EVENT_KEY)
    oprdf = pd.DataFrame({
        "oprs": opr_raw.get("oprs", {}),
        "dprs": opr_raw.get("dprs", {}),
        "ccwms": opr_raw.get("ccwms", {})
    })

    #Predictions
    result = predi(EVENT_KEY)

    # 1. Match predictions (qual + playoff) — one row per match
    match_rows = []
    for match_level in ["qual", "playoff"]:
        level_data = result.get("match_predictions", {}).get(match_level, {})
        for match_key, match in level_data.items():
            row = {"match_key": match_key, "level": match_level}
            row["win_prob"] = match.get("prob")
            row["predicted_winner"] = match.get("winning_alliance")
            for alliance in ["blue", "red"]:
                alliance_data = match.get(alliance, {})
                for stat, val in alliance_data.items():
                    row[f"{alliance}_{stat}"] = val
            match_rows.append(row)
    match_pred_df = pd.DataFrame(match_rows)

    match_pred_slim = match_pred_df[["match_key", "level", "predicted_winner", "win_prob", "red_score", "blue_score"]].copy()
    match_pred_slim.to_csv(PROCESSED_DIR / "match_predictions_tba_gotham_slim.csv", index=False)
    print("match_predictions_tba_gotham")

    # 2. Ranking predictions — one row per team
    ranking_rows = []
    for team, stats in result.get("ranking_predictions", []):
        ranking_rows.append({
            "team": team,
            "rank": stats[0],
            "ranking_points": stats[4]
        })
    ranking_pred_df = pd.DataFrame(ranking_rows)

    # 3. Stat mean/vars per team — one row per team per stat
    stat_rows = []
    for match_level in ["qual", "playoff"]:
        level_stats = result.get("stat_mean_vars", {}).get(match_level, {})
        for stat_name, stat_data in level_stats.items():
            means = stat_data.get("mean", {})
            vars_ = stat_data.get("var", {})
            for team in means:
                stat_rows.append({
                    "team": team,
                    "level": match_level,
                    "stat": stat_name,
                    "mean": means[team],
                    "var": vars_.get(team)
                })
    stat_df = pd.DataFrame(stat_rows)

    #Rankings Data Frame
    rkdf = pd.DataFrame(rankings(EVENT_KEY)["rankings"])


    #csv makers
    match_pred_df.to_csv(PROCESSED_DIR / "match_predictions_tba_gotham.csv", index=False)
    ranking_pred_df.to_csv(PROCESSED_DIR / "ranking_predictions_tba_gotham.csv", index=False)
    stat_df.to_csv(PROCESSED_DIR / "stats_prediction_tba_gotham.csv", index=False)
    oprdf.index.name = "team_key"
    oprdf.to_csv(PROCESSED_DIR / "opr_tba_gotham.csv", index=True)
    rkdf.to_csv(PROCESSED_DIR / "rankings_tba_gotham.csv", index=False)
    matches = session.get(f"{baseurl}/event/{EVENT_KEY}/matches").json()
    completed = [m for m in matches if m.get("actual_time") and m.get("comp_level") == "qm"]
    if completed:
        print("Sample breakdown:", completed[0].get("score_breakdown", {}).get("red"))


if __name__ == "__main__":
    main()
