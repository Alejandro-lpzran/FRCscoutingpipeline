"""
Crunches every pipeline output into one JSON file for the HTML dashboard.

    python -m pipeline.export

Writes data/processed/dashboard.json. Run it after any backend stage, then reload the page.
All the pandas work lives here, so the page only has to display things.
"""
import ast
import json
import math
import re
from datetime import datetime, timezone

import pandas as pd

from pipeline.events import event_group
from pipeline.paths import RAW_DIR, PROCESSED_DIR, REPORTS_DIR

EVENT_KEY = "2026nyn2"
HOME_TEAM = "3158"
OUTPUT = PROCESSED_DIR / "dashboard.json"

# Alliance-wide RP thresholds at regionals
THRESHOLDS = {"energized_fuel": 100, "supercharged_fuel": 360, "traversal_tower": 50}

FILES = {
    "teams":      RAW_DIR / "gotham_2026_teams.csv",
    "scouting":   RAW_DIR / "scouting_datanyc.csv",
    "opr":        PROCESSED_DIR / "opr_tba_gotham.csv",
    "rankings":   PROCESSED_DIR / "rankings_tba_gotham.csv",
    "rank_pred":  PROCESSED_DIR / "ranking_predictions_tba_gotham.csv",
    "stats_pred": PROCESSED_DIR / "stats_prediction_tba_gotham.csv",
    "matches":    PROCESSED_DIR / "match_predictions_tba_gotham_slim.csv",
    "montecarlo": PROCESSED_DIR / f"monte_carlo_sim_{EVENT_KEY}.csv",
}
REPORT_DIRS = {
    "gemini": REPORTS_DIR / "gemini_reports",
    "gpt":    REPORTS_DIR / "gpt_reports",
}
SCOUTING_NUMERIC = ["auto_fuel", "auto_tower", "teleop_cycles", "teleop_fuel", "teleop_tower",
                    "teleop_majorFoul", "teleop_minorFoul", "totalPoints"]


# ── Loading ───────────────────────────────────────────────────────────────────

def read_csv(name, team_column=None, **kwargs):
    path = FILES[name]
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, **kwargs)
    if team_column:
        df["team"] = df[team_column].astype(str).str.replace("frc", "")
    return df


def load_scouting():
    df = read_csv("scouting", "teamNumber", engine="python", on_bad_lines="skip")
    if df.empty:
        return df
    for column in SCOUTING_NUMERIC:
        if column not in df.columns:
            df[column] = None
    df[SCOUTING_NUMERIC] = df[SCOUTING_NUMERIC].apply(pd.to_numeric, errors="coerce")
    # Negative fouls are data entry errors
    df["negative_foul"] = (df["teleop_majorFoul"] < 0) | (df["teleop_minorFoul"] < 0)
    df["fouls"] = (df["teleop_majorFoul"] + df["teleop_minorFoul"]).where(~df["negative_foul"])
    df["tower"] = df["auto_tower"] + df["teleop_tower"]
    df["event_group"] = df["event"].map(event_group)
    df["match"] = df["event"].astype(str) + " #" + df["matchNumber"].astype(str)
    if "lastUpdated_seconds" in df.columns:
        df = df.sort_values("lastUpdated_seconds")
    return df


def parse_report(text):
    """Split a report into prose and JSON fields. fields is None when the JSON is missing or cut off."""
    found = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    prose = text[:found.start()] if found else text
    prose = prose.replace("PROSE REPORT:", "").strip().rstrip("-").strip()
    try:
        fields = json.loads(found.group(1)) if found else None
    except json.JSONDecodeError:
        fields = None
    return {"prose": prose, "fields": fields}


def load_reports():
    reports = {}
    for model, folder in REPORT_DIRS.items():
        reports[model] = {}
        for path in sorted(folder.glob(f"{model}_*.txt")):
            team = path.stem.replace(f"{model}_", "")
            reports[model][team] = parse_report(path.read_text(encoding="utf-8"))
    return reports


# ── Building ──────────────────────────────────────────────────────────────────

def build_team_table(data, scouting, reports):
    """One row per team at the event, from every source that has run so far."""
    teams = set()
    for name in ["rankings", "opr", "montecarlo"]:
        if not data[name].empty:
            teams |= set(data[name]["team"])
    table = pd.DataFrame({"team": sorted(teams, key=int)})
    if table.empty:
        return table

    def add(df, columns):
        nonlocal table
        if df.empty:
            for column in columns.values():
                table[column] = None
            return
        table = table.merge(df[["team", *columns]].rename(columns=columns), on="team", how="left")

    add(data["teams"].drop_duplicates("team") if not data["teams"].empty else data["teams"], {"nickname": "nickname"})

    rankings = data["rankings"]
    if not rankings.empty:
        rankings = rankings.copy()
        records = rankings["record"].map(ast.literal_eval)
        rankings["record"] = records.map(lambda r: f"{r['wins']}-{r['losses']}-{r['ties']}")
        rankings["rp"] = rankings["extra_stats"].map(lambda v: ast.literal_eval(v)[0])
        rankings["ranking_score"] = rankings["sort_orders"].map(lambda v: ast.literal_eval(v)[0])
    add(rankings, {"rank": "rank", "record": "record", "rp": "rp", "ranking_score": "ranking_score"})
    add(data["opr"], {"oprs": "opr", "dprs": "dpr", "ccwms": "ccwm"})
    add(data["rank_pred"], {"rank": "tba_rank", "ranking_points": "tba_rp"})
    add(data["montecarlo"], {"rank": "mc_rank", "total_rp": "mc_rp"})

    if scouting.empty:
        averages = pd.DataFrame()
    else:
        grouped = scouting.groupby("team")
        averages = grouped[["auto_fuel", "teleop_fuel", "teleop_cycles", "tower", "fouls", "totalPoints"]].mean().reset_index()
        averages["scouted"] = averages["team"].map(grouped.size())
        averages["total_fuel"] = averages["auto_fuel"] + averages["teleop_fuel"]
        averages["fuel_per_cycle"] = averages["teleop_fuel"] / averages["teleop_cycles"].where(averages["teleop_cycles"] > 0)
    add(averages, {"scouted": "scouted", "auto_fuel": "auto_fuel", "teleop_fuel": "teleop_fuel",
                   "total_fuel": "total_fuel", "teleop_cycles": "cycles", "fuel_per_cycle": "fuel_per_cycle",
                   "tower": "tower", "fouls": "fouls", "totalPoints": "points"})

    for model in reports:
        def field(team, key):
            fields = reports[model].get(team, {}).get("fields") or {}
            value = fields.get(key)
            return None if value is None else str(value)
        table[f"tier_{model}"] = table["team"].map(lambda team: field(team, "tier"))
        table[f"profile_{model}"] = table["team"].map(lambda team: field(team, "cycle_profile"))

    text_columns = ["team", "nickname", "record"] + [c for c in table.columns if c.startswith(("tier_", "profile_"))]
    for column in table.columns.difference(text_columns):
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table["scouted"] = table["scouted"].fillna(0)
    return table


def build_checks(data, scouting_all, table, reports):
    """Everything the old Data checks tab showed, as plain data."""
    files = []
    for name, path in FILES.items():
        exists = path.exists()
        rows = None
        if exists:
            rows = len(scouting_all) if name == "scouting" else len(data[name])
        files.append({
            "file": str(path.relative_to(path.parents[2])),
            "found": exists,
            "rows": rows,
            "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes") if exists else None,
        })

    report_status = {
        model: {
            "found": len(found),
            "cut_off": sorted((t for t, r in found.items() if r["fields"] is None), key=int),
        }
        for model, found in reports.items()
    }

    checks = {"files": files, "reports": report_status}
    if scouting_all.empty:
        return checks

    at_event = set(table["team"]) if not table.empty else set()
    unknown = scouting_all[~scouting_all["team"].isin(at_event)]
    checks["unknown_teams"] = [
        {"team": team, "rows": len(rows), "events": sorted(set(rows["event"].astype(str)))}
        for team, rows in unknown.groupby("team")
    ]
    checks["unscouted_teams"] = table.loc[~table["team"].isin(scouting_all["team"]), "team"].tolist() if not table.empty else []
    checks["negative_foul_rows"] = int(scouting_all["negative_foul"].sum())
    if "documentId" in scouting_all.columns:
        duplicates = scouting_all[scouting_all.duplicated(["team", "documentId"], keep=False)]
        checks["duplicate_rows"] = records(duplicates[["team", "documentId", "auto_fuel", "teleop_fuel", "totalPoints", "comments"]]
                                           .sort_values(["team", "documentId"]))
    checks["event_groups"] = records(scouting_all.groupby(["event_group", "event"]).size().reset_index(name="rows"))
    return checks


# ── JSON helpers ──────────────────────────────────────────────────────────────

def clean(value):
    """NaN and numpy types become plain JSON values."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def records(df):
    return [{k: clean(v) for k, v in row.items()} for row in df.to_dict("records")]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    data = {
        "teams":      read_csv("teams", "team_number"),
        "opr":        read_csv("opr", "team_key"),
        "rankings":   read_csv("rankings", "team_key"),
        "rank_pred":  read_csv("rank_pred", "team"),
        "stats_pred": read_csv("stats_pred", "team"),
        "matches":    read_csv("matches"),
        "montecarlo": read_csv("montecarlo", "team"),
    }
    scouting_all = load_scouting()
    reports = load_reports()

    # Team averages use Gotham matches by default, same as the old dashboard.
    # Every raw row still goes out with its event_group, so the page can re-average with a filter.
    gotham = scouting_all[scouting_all["event_group"] == "Gotham"] if not scouting_all.empty else scouting_all
    table = build_team_table(data, gotham, reports)

    scouting_columns = ["team", "match", "event", "event_group", "auto_fuel", "teleop_fuel", "teleop_cycles",
                        "tower", "fouls", "totalPoints", "comments"]
    season_columns = ["team", "global_opr", "global_rank", "last_event", "last_rank", "last_record", "avg_pts", "event_avg"]

    matches = data["matches"]
    if not matches.empty:
        matches = matches.copy()
        matches["code"] = matches["match_key"].str.split("_").str[-1]

    output = {
        "meta": {
            "event_key": EVENT_KEY,
            "home_team": HOME_TEAM,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "thresholds": THRESHOLDS,
        },
        "teams": records(table),
        "season": {row["team"]: row for row in records(data["teams"][[c for c in season_columns if c in data["teams"].columns]])}
                  if not data["teams"].empty else {},
        "scouting": records(scouting_all[[c for c in scouting_columns if c in scouting_all.columns]]) if not scouting_all.empty else [],
        "stats_pred": records(data["stats_pred"][["team", "level", "stat", "mean", "var"]]) if not data["stats_pred"].empty else [],
        "matches": records(matches) if not matches.empty else [],
        "reports": {model: {team: {"prose": r["prose"], "fields": r["fields"]} for team, r in found.items()}
                    for model, found in reports.items()},
        "checks": build_checks(data, scouting_all, table, reports),
    }

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, default=clean), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(output['teams'])} teams, {len(output['scouting'])} scouted rows, "
          f"{len(output['matches'])} match predictions)")


if __name__ == "__main__":
    main()
